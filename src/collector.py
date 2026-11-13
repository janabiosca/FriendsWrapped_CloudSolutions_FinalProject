"""Collects the new plays of one user. Triggered by SQS, one message per user."""
import datetime
import json
import os

import boto3

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

    access_token = _access_token(user_id)
    page = spotify.recently_played(access_token, after_ms=cursor)
    pages, plays, seen, links = [], {}, set(), set()
    previous_oldest = None
    full_page = False
    for _ in range(20):
        items = page.get("items", [])
        if not items:
            break
        signature = tuple(sorted((p["played_at"], str(p["track"].get("id") or p["track"].get("uri") or p["track"]["name"])) for p in items))
        if signature in seen:
            raise spotify.SpotifyError("History pagination repeated a page; cursor preserved")
        seen.add(signature)
        pages.append(page)
        full_page = full_page or len(items) >= spotify.PAGE_SIZE
        for play in items:
            if played_at_ms(play["played_at"]) > cursor:
                track = play["track"]
                identity = (play["played_at"], track.get("id") or track.get("uri") or track["name"])
                plays[identity] = play
        oldest = min(played_at_ms(p["played_at"]) for p in items)
        # The first connection deliberately seeds the most recent page only.
        if not cursor or oldest <= cursor:
            break
        next_url = page.get("next")
        if next_url:
            if next_url in links:
                raise spotify.SpotifyError("History pagination repeated a URL; cursor preserved")
            links.add(next_url)
            page = spotify.next_recent_page(access_token, next_url)
        elif len(items) >= spotify.PAGE_SIZE:
            # Some responses have no next URL despite being full. Try an older
            # time cursor; Spotify may return no more history, which is not proof
            # that nothing was played before the oldest available result.
            if previous_oldest is not None and oldest >= previous_oldest:
                raise spotify.SpotifyError("History pagination made no backward progress")
            previous_oldest = oldest
            page = spotify.recently_played(access_token, before_ms=oldest)
        else:
            break
    else:
        raise spotify.SpotifyError("History pagination safety limit reached; cursor preserved")

    # Finish fetching before writes. Any failed page leaves the old checkpoint.
    # Conditional writes protect against duplicates if storing or checkpointing fails.
    for raw_page in pages:
        store.archive_raw(user_id, raw_page)
    new_plays = sum(store.put_play(user_id, play) for play in plays.values())
    possible_gap = cursor > 0 and full_page
    newest = max((played_at_ms(p["played_at"]) for p in plays.values()), default=cursor)
    store.record_sync(user_id, max(cursor, newest), new_plays, possible_gap)
    return {"user_id": user_id, "fetched": len(plays), "new_plays": new_plays,
            "pages": len(pages), "possible_gap": possible_gap}


MAX_VISIBILITY_S = 12 * 3600  # SQS limit


def _status(error):
    if isinstance(error, spotify.AuthRevoked):
        return "reauth_required"
    if isinstance(error, spotify.RateLimited):
        return "rate_limited"
    return "failed"


def _delay_retry(record, seconds):
    """Hides the message for as long as Spotify asked, so the retry does not hit the limit again."""
    try:
        boto3.client("sqs").change_message_visibility(
            QueueUrl=os.environ["QUEUE_URL"], ReceiptHandle=record["receiptHandle"],
            VisibilityTimeout=min(max(int(seconds), 1), MAX_VISIBILITY_S))
    except Exception as e:  # the normal visibility timeout still applies
        print(json.dumps({"event": "delay_retry_failed", "error": repr(e)}))


def handler(event, context):
    for record in event["Records"]:
        user_id = json.loads(record["body"])["user_id"]
        try:
            print(json.dumps({"event": "collected", **collect(user_id)}))
        except Exception as e:
            status = _status(e)
            print(json.dumps({"event": "collect_failed", "user_id": user_id,
                              "status": status, "error": repr(e)}))
            if isinstance(e, spotify.RateLimited):
                _delay_retry(record, e.retry_after)
            try:
                store.record_failure(user_id, status, repr(e))
            except Exception:
                pass
            raise  # SQS retries; after 3 attempts the message goes to the dead-letter queue
