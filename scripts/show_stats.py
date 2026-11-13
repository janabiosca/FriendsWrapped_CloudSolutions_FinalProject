"""Read-only summary of one member's stored history. Does not read Spotify tokens."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import listening_stats
import store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--table", default="sfw-dev")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--start", default="0000", help="Inclusive UTC ISO timestamp or date")
    parser.add_argument("--end", default="9999", help="Exclusive UTC ISO timestamp or date")
    args = parser.parse_args()
    if args.start >= args.end:
        parser.error("start must be before end")
    os.environ["TABLE_NAME"] = args.table
    os.environ["AWS_DEFAULT_REGION"] = args.region
    profile = store.get_profile(args.user_id)
    if not profile:
        parser.error("Unknown user")
    result = listening_stats.summarize(store.plays_between(args.user_id, args.start, args.end))
    result.update({"user_id": args.user_id, "source": "stored_history",
                   "last_sync_at": profile.get("last_sync_at"),
                   "last_sync_status": profile.get("last_sync_status"),
                   "possible_gaps": int(profile.get("possible_gaps", 0)),
                   "note": "Partial recorded history. Minutes are estimated from track durations; collaborations count for each artist."})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
