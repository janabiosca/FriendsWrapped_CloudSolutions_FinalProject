"""Statistics computed only from stored plays, never Spotify's unrelated top rankings."""
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def listening_ms(play):
    measured = play.get("ms_played")
    return max(0, int(play.get("duration_ms", 0) if measured is None else measured))


def summarize(plays, limit=5):
    tracks = {}
    artists = Counter()
    total_ms = 0
    for play in plays:
        key = play["track_id"]
        if key not in tracks:
            tracks[key] = {"track_id": key, "name": play["track_name"],
                           "artists": play.get("artists", []), "plays": 0}
        tracks[key]["plays"] += 1
        total_ms += listening_ms(play)
        # A collaboration counts once for each credited artist, never twice for one name.
        artists.update(set(play.get("artists", [])))
    top_tracks = sorted(tracks.values(), key=lambda t: (-t["plays"], t["name"], t["track_id"]))
    top_artists = sorted(artists.items(), key=lambda a: (-a[1], a[0]))
    return {"total_plays": len(plays), "unique_tracks": len(tracks),
            "estimated_minutes": round(total_ms / 60000, 1),
            "listening_ms": total_ms,
            "measured_plays": sum(p.get("ms_played") is not None for p in plays),
            "top_tracks": top_tracks[:limit],
            "top_artists": [{"name": name, "plays": n} for name, n in top_artists[:limit]],
            "first_play_at": min((p["played_at"] for p in plays), default=None),
            "last_play_at": max((p["played_at"] for p in plays), default=None)}


def weekly_group(members, monday, timezone="Europe/Madrid"):
    """Summarize one local calendar week using explicit full-day coverage."""
    if monday.weekday() != 0:
        raise ValueError("The week must start on Monday")
    days = {monday + timedelta(days=i) for i in range(7)}
    zone = ZoneInfo(timezone)
    ranking = []
    group_plays = []
    for member in members:
        plays = []
        for play in member["plays"]:
            instant = datetime.fromisoformat(play["played_at"].replace("Z", "+00:00"))
            if instant.tzinfo is None:
                raise ValueError("Playback timestamps must include a timezone")
            if instant.astimezone(zone).date() in days:
                plays.append(play)
        missing = sorted(days - set(member["covered_days"]))
        ranking.append({
            "name": member["name"],
            "user_id": member.get("user_id", member["name"]),
            **summarize(plays),
            "covered_days": 7 - len(missing),
            "unverified_days": [day.isoformat() for day in missing],
        })
        group_plays.extend(plays)

    ranking.sort(key=lambda row: (-row["listening_ms"], row["name"]))
    previous_ms = None
    for position, row in enumerate(ranking, 1):
        if row["listening_ms"] != previous_ms:
            rank = position
        row["rank"] = rank
        previous_ms = row["listening_ms"]
    return {"week_start": monday.isoformat(), "timezone": timezone,
            "ranking": ranking, "group": summarize(group_plays)}
