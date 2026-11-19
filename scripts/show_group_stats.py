"""Read the real group's weekly ranking from DynamoDB. Never reads Spotify tokens."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from group_stats import weekly_from_store
import store




def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", default="friends")
    parser.add_argument("--week", type=date.fromisoformat, help="Monday in YYYY-MM-DD format; defaults to this week")
    parser.add_argument("--table", default="sfw-dev")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Madrid")).date()
    monday = args.week or today - timedelta(days=today.weekday())
    if monday.weekday() != 0:
        parser.error("--week must be a Monday")
    os.environ["TABLE_NAME"] = args.table
    os.environ["AWS_DEFAULT_REGION"] = args.region
    print(json.dumps(weekly_from_store(args.group_id, monday), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
