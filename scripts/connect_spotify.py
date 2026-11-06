"""Connects one friend's Spotify account to the deployed stack.

Opens the Spotify login in the browser, then stores the refresh token in Secrets Manager
and registers the user in the group. Run it once per person (each one logs in with her
own Spotify account; use a private window if several log in on the same laptop):

    python scripts/connect_spotify.py --client-id <id> --user-id jana --name Jana --email jana@example.com

Requires AWS credentials in the environment and http://127.0.0.1:8888/callback as a
redirect URI of the Spotify app.
"""
import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

import boto3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--user-id", required=True, help="short id without spaces, e.g. jana")
    parser.add_argument("--name", required=True)
    parser.add_argument("--email", default="")
    parser.add_argument("--stack", default="sfw")
    args = parser.parse_args()

    stack = boto3.client("cloudformation").describe_stacks(StackName=args.stack)["Stacks"][0]
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
    os.environ["TABLE_NAME"] = outputs["TableName"]
    os.environ["SECRET_PREFIX"] = outputs["SecretPrefix"]
    import store

    token = login(args.client_id)
    store.save_token(args.user_id, {"refresh_token": token["refresh_token"]})
    store.add_member(outputs["GroupId"], args.user_id, args.name, args.email)
    print(f"{args.name} connected to group '{outputs['GroupId']}'. "
          "Her plays will be collected on the next run.")


if __name__ == "__main__":
    main()
