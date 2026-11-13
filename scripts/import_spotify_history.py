"""Preview or import complete missing days from Spotify Extended Streaming History."""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat,
                        help="Last day to include")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    os.environ.setdefault("TABLE_NAME", "sfw-dev")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    if args.user_id not in store.group_members("friends") or not store.get_profile(args.user_id):
        parser.error("Connect this member's Spotify account first")
    madrid = ZoneInfo("Europe/Madrid")

    def utc_boundary(day):
        return datetime.combine(day, time.min, madrid).astimezone(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")

    existing = store.plays_between(args.user_id, utc_boundary(args.start),
                                  utc_boundary(args.end + timedelta(days=1)))
    # Prior imports can be retried using the same exact track and timestamp keys.
    occupied = {datetime.fromisoformat(p["played_at"]).astimezone(madrid).date()
                for p in existing if "ms_played" not in p}
    candidates = {}
    for path in args.files:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) or "ts" not in row for row in rows):
            parser.error(f"{path.name}: expected a Spotify extended history JSON file")
        for row in rows:
            uri = row.get("spotify_track_uri") or ""
            name = row.get("master_metadata_track_name")
            elapsed = row.get("ms_played")
            if not uri.startswith("spotify:track:") or not name or not isinstance(elapsed, int) or elapsed <= 0:
                continue
            moment = datetime.fromisoformat(row["ts"]).astimezone(timezone.utc)
            day = moment.astimezone(madrid).date()
            if not args.start <= day <= args.end or day in occupied:
                continue
            stamp = moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            track_id = uri.removeprefix("spotify:track:")
            artist = row.get("master_metadata_album_artist_name")
            candidates[(stamp, track_id)] = (day, {
                "played_at": stamp, "ms_played": elapsed,
                "track": {"id": track_id, "name": name,
                          "artists": [{"name": artist}] if artist else [],
                          "album": {"name": row.get("master_metadata_album_album_name") or ""}},
            })
    print(json.dumps({"user": args.user_id, "eligible_by_day": dict(Counter(
        day.isoformat() for day, _ in candidates.values())),
        "days_skipped_existing_plays": sorted(day.isoformat() for day in occupied),
        "written": sum(store.put_play(args.user_id, p) for _, p in candidates.values())
        if args.apply else 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
