"""Issue a private, expiring Spotify invitation. Never commit or log the generated URL."""
import argparse
import hashlib
import secrets
import time
from urllib.parse import urlencode

import boto3


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, choices=["anna", "helena"])
    parser.add_argument("--name", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--table", default="sfw-dev-connect")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    table = boto3.resource("dynamodb", region_name=args.region).Table(args.table)
    table.put_item(Item={"id": "INVITE#" + hashlib.sha256(token.encode()).hexdigest(),
                         "user_id": args.user_id, "display_name": args.name,
                         "expires_at": int(time.time()) + 7 * 86400})
    print(args.base_url.rstrip("/") + "/connect?" + urlencode({"invite": token}))


if __name__ == "__main__":
    main()
