"""Connects one friend's Spotify account to a deployed environment.

Opens the Spotify login in the browser, then stores the refresh token in Secrets Manager
and registers the user in the group. Run it once per person (each one logs in with her
own Spotify account; use a private window if several log in on the same laptop):

    python scripts/connect_spotify.py --env prod --client-id <id> --user-id jana --name Jana --email jana@example.com

Requires AWS credentials for the environment's account, `terraform apply` already run in
infra/envs/<env>, and http://127.0.0.1:8888/callback as a redirect URI of the Spotify app.

The token is written straight to Secrets Manager on purpose: Terraform stores everything it
manages in plain text in its state file, so secrets must never go through Terraform.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-read-recently-played user-top-read"


def login(client_id):
    """Authorization Code + PKCE flow. Returns the token response."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state,
        "show_dialog": "true",  # always ask which account, so friends do not reuse each other's session
    })
    result = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in query and query.get("state", [None])[0] == state:
                result["code"] = query["code"][0]
                body = b"<h2>Spotify connected. You can close this tab.</h2>"
            else:
                result["error"] = query.get("error", ["unknown"])[0]
                body = b"<h2>Login failed.</h2>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 8888), Callback)
    print("Open this URL to log in:\n" + url, flush=True)
    webbrowser.open(url)
    while not result:
        server.handle_request()
    server.server_close()
    if "code" not in result:
        sys.exit(f"Login failed: {result}")

    data = urllib.parse.urlencode({
        "client_id": client_id, "grant_type": "authorization_code", "code": result["code"],
        "redirect_uri": REDIRECT, "code_verifier": verifier,
    }).encode()
    request = urllib.request.Request("https://accounts.spotify.com/api/token", data=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(request))


def terraform_outputs(env, terraform="terraform"):
    """Reads the outputs of infra/envs/<env> (table name, secret prefix, group id)."""
    env_dir = os.path.join(ROOT, "infra", "envs", env)
    try:
        raw = subprocess.run([terraform, f"-chdir={env_dir}", "output", "-json"],
                             check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"Could not read the Terraform outputs of {env_dir}: {e}")
    outputs = {name: value["value"] for name, value in json.loads(raw or "{}").items()}
    missing = {"table_name", "secret_prefix", "group_id"} - outputs.keys()
    if missing:
        sys.exit(f"Missing outputs {sorted(missing)}: run `terraform apply` in {env_dir} first.")
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default="dev", choices=["dev", "prod"])
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--user-id", required=True, help="short id without spaces, e.g. jana")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--terraform", default="terraform", help="path to the terraform binary")
    args = parser.parse_args()

    outputs = terraform_outputs(args.env, args.terraform)
    os.environ["TABLE_NAME"] = outputs["table_name"]
    os.environ["SECRET_PREFIX"] = outputs["secret_prefix"]
    import store

    token = login(args.client_id)
    store.save_token(args.user_id, {"refresh_token": token["refresh_token"]})
    store.add_member(outputs["group_id"], args.user_id, args.name, args.email)
    print(f"{args.name} connected to group '{outputs['group_id']}' in {args.env}. "
          "Her plays will be collected on the next run.")


if __name__ == "__main__":
    main()
