"""Collects the new plays of one user. Triggered by SQS, one message per user."""
import datetime
import json
import os

import spotify
import store


def played_at_ms(played_at):
    moment = datetime.datetime.fromisoformat(played_at.replace("Z", "+00:00"))
    return round(moment.timestamp() * 1000)


def _access_token(user_id):
    token = store.get_token(user_id)
    fresh = spotify.refresh(os.environ["SPOTIFY_CLIENT_ID"], token["refresh_token"],
                            os.environ.get("SPOTIFY_CLIENT_SECRET"))
    rotated = fresh.get("refresh_token")
    if rotated and rotated != token["refresh_token"]:
        # Save first: once rotated, the old refresh token stops working
        store.save_token(user_id, {"refresh_token": rotated})
    return fresh["access_token"]


def collect(user_id):
    profile = store.get_profile(user_id)
    if not profile:
        raise LookupError(f"unknown user {user_id}")
    cursor = int(profile.get("cursor_ms", 0))

    page = spotify.recently_played(_access_token(user_id), after_ms=cursor)
    plays = page.get("items", [])
    if plays:
        store.archive_raw(user_id, page)
    new_plays = sum(store.put_play(user_id, play) for play in plays)

    # A full page after our cursor means Spotify may have already dropped older plays
    # (e.g. the lab was stopped for longer than it took the user to play 50 songs).
    possible_gap = cursor > 0 and len(plays) >= spotify.PAGE_SIZE
    newest = max((played_at_ms(p["played_at"]) for p in plays), default=cursor)

    # The cursor only moves once every play is stored. If anything above fails, the
    # message is retried from the same cursor and the conditional writes skip repeats.
    store.record_sync(user_id, max(cursor, newest), new_plays, possible_gap)
    return {"user_id": user_id, "fetched": len(plays), "new_plays": new_plays,
            "possible_gap": possible_gap}


def handler(event, context):
    for record in event["Records"]:
        user_id = json.loads(record["body"])["user_id"]
        try:
            print(json.dumps({"event": "collected", **collect(user_id)}))
        except Exception as e:
            status = "reauth_required" if isinstance(e, spotify.AuthRevoked) else "failed"
            print(json.dumps({"event": "collect_failed", "user_id": user_id,
                              "status": status, "error": repr(e)}))
            try:
                store.record_failure(user_id, status, repr(e))
            except Exception:
                pass
            raise  # SQS retries; after 3 attempts the message goes to the dead-letter queue
