"""Weekly statistics for real group members from stored history."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import listening_stats
import store


def weekly_from_store(group_id, monday, now=None):
    zone = ZoneInfo("Europe/Madrid")
    now = now or datetime.now(timezone.utc)
    if monday.weekday() != 0:
        raise ValueError("The week must start on Monday")
    start = datetime.combine(monday, time.min, zone).astimezone(timezone.utc)
    end = min(datetime.combine(monday + timedelta(days=7), time.min, zone).astimezone(timezone.utc), now)
    members = []
    profiles = {}
    for user_id in store.group_members(group_id):
        profile = store.get_profile(user_id) or {}
        profiles[user_id] = profile
        plays = []
        if start < end:
            plays = store.plays_between(user_id, start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                                        end.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
        # A successful sync alone cannot certify a full day's listening history.
        members.append({"name": profile.get("display_name", user_id), "user_id": user_id,
                        "plays": plays, "covered_days": []})
    result = listening_stats.weekly_group(members, monday)
    for row in result["ranking"]:
        profile = profiles[row["user_id"]]
        row.update(connected_at=profile.get("connected_at"),
                   last_sync_at=profile.get("last_sync_at"), last_sync_status=profile.get("last_sync_status"),
                   possible_gaps=int(profile.get("possible_gaps", 0)))
    result.update(group_id=group_id, source="stored_history", generated_at=now.isoformat(),
                  note="Ranking of recorded plays only. Minutes use track durations unless measured playback is available. Full-day coverage is unverified.")
    return result
