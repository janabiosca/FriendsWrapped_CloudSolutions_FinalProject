"""Collector tests against in-memory AWS (moto). Spotify is replaced by a fake."""
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

os.environ.update({
    "AWS_DEFAULT_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test",
    "TABLE_NAME": "sfw-test", "RAW_BUCKET": "sfw-raw-test", "GROUP_ID": "friends",
    "SPOTIFY_CLIENT_ID": "client", "SECRET_PREFIX": "sfw/spotify/",
})

import collector  # noqa: E402
import dispatcher  # noqa: E402
import spotify  # noqa: E402
import store  # noqa: E402


def play(minute, track="t1", second=0):
    return {"played_at": f"2026-11-06T10:{minute:02d}:{second:02d}.000Z", "context": {"type": "playlist"},
            "track": {"id": track, "name": f"Song {track}", "duration_ms": 180000,
                      "artists": [{"id": "a1", "name": "Artist"}], "album": {"name": "Album"}}}


class FakeSpotify:
    """Behaves like the real endpoint: only plays after the cursor, newest first, 50 at most."""

    def __init__(self, monkeypatch):
        self.plays, self.fail, self.rotate_to = [], None, None
        monkeypatch.setattr(spotify, "refresh", self.refresh)
        monkeypatch.setattr(spotify, "recently_played", self.recently_played)

    def refresh(self, client_id, refresh_token, client_secret=None):
        self.last_refresh_token = refresh_token
        token = {"access_token": "access"}
        if self.rotate_to:
            token["refresh_token"] = self.rotate_to
        return token

    def recently_played(self, access_token, after_ms=None, before_ms=None):
        if self.fail:
            raise self.fail
        newer = [p for p in self.plays if collector.played_at_ms(p["played_at"]) > (after_ms or 0)]
        if before_ms is not None:
            newer = [p for p in newer if collector.played_at_ms(p["played_at"]) < before_ms]
        newer.sort(key=lambda p: p["played_at"], reverse=True)
        return {"items": newer[:spotify.PAGE_SIZE]}


@pytest.fixture
def aws():
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="sfw-test", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}])
        boto3.client("s3").create_bucket(Bucket="sfw-raw-test")
        queue = boto3.client("sqs").create_queue(
            QueueName="collect.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
        os.environ["QUEUE_URL"] = queue
        for user in ("jana", "helena"):
            store.save_token(user, {"refresh_token": f"refresh-{user}"})
            store.add_member("friends", user, user.title())
        yield


@pytest.fixture
def fake(monkeypatch):
    return FakeSpotify(monkeypatch)


def stored(user):
    return store.plays_between(user, "2026-11-06", "2026-11-07")


def sqs_event(user):
    return {"Records": [{"body": json.dumps({"user_id": user})}]}


def test_collecting_twice_does_not_duplicate(aws, fake):
    fake.plays = [play(1), play(5, "t2"), play(9)]
    assert collector.collect("jana")["new_plays"] == 3
    assert collector.collect("jana")["new_plays"] == 0
    assert len(stored("jana")) == 3
    assert store.get_profile("jana")["total_plays"] == 3


def test_only_new_plays_are_fetched_after_the_cursor(aws, fake):
    fake.plays = [play(1), play(5, "t2")]
    collector.collect("jana")
    fake.plays.append(play(20, "t3"))
    result = collector.collect("jana")
    assert (result["fetched"], result["new_plays"]) == (1, 1)
    assert store.get_profile("jana")["cursor_ms"] == collector.played_at_ms(play(20)["played_at"])


def test_same_song_played_twice_counts_twice(aws, fake):
    fake.plays = [play(1), play(5)]
    collector.collect("jana")
    assert len(stored("jana")) == 2


def test_retry_after_lost_cursor_update_is_idempotent(aws, fake, monkeypatch):
    """Plays were stored but the function died before moving the cursor: the retry must not double count."""
    fake.plays = [play(1), play(5, "t2")]
    real_record_sync = store.record_sync
    monkeypatch.setattr(store, "record_sync", lambda *a: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        collector.collect("jana")
    assert store.get_profile("jana")["cursor_ms"] == 0
    monkeypatch.setattr(store, "record_sync", real_record_sync)
    assert collector.collect("jana")["new_plays"] == 0
    assert len(stored("jana")) == 2
    assert store.get_profile("jana")["cursor_ms"] > 0


def test_one_user_failing_does_not_affect_the_others(aws, fake):
    fake.plays = [play(1)]
    collector.handler(sqs_event("helena"), None)
    fake.fail = spotify.SpotifyError("HTTP 500")
    with pytest.raises(spotify.SpotifyError):  # raising hands the message back to SQS for a retry
        collector.handler(sqs_event("jana"), None)
    assert store.get_profile("jana")["last_sync_status"] == "failed"
    assert store.get_profile("jana")["cursor_ms"] == 0
    assert store.get_profile("helena")["last_sync_status"] == "ok"
    assert len(stored("helena")) == 1


def test_revoked_login_is_flagged(aws, fake):
    fake.fail = spotify.AuthRevoked("invalid_grant")
    with pytest.raises(spotify.AuthRevoked):
        collector.handler(sqs_event("jana"), None)
    assert store.get_profile("jana")["last_sync_status"] == "reauth_required"


def test_rotated_refresh_token_is_saved(aws, fake):
    fake.rotate_to = "refresh-new"
    collector.collect("jana")
    assert store.get_token("jana") == {"refresh_token": "refresh-new"}
    collector.collect("jana")
    assert fake.last_refresh_token == "refresh-new"


def test_full_page_after_cursor_is_reported_as_possible_gap(aws, fake):
    fake.plays = [play(0)]
    assert collector.collect("jana")["possible_gap"] is False
    fake.plays += [play(m, f"t{m}{s}", s) for m in range(1, 7) for s in range(10)]  # 60 more plays
    result = collector.collect("jana")
    assert result["possible_gap"] is True and result["new_plays"] == 60
    assert store.get_profile("jana")["possible_gaps"] == 1


def test_dispatcher_queues_one_task_per_member_and_dedupes_repeated_ticks(aws, fake):
    event = {"time": "2026-11-06T10:00:00Z"}
    assert sorted(dispatcher.handler(event, None)["users"]) == ["helena", "jana"]
    dispatcher.handler(event, None)  # EventBridge delivering the same tick twice
    sqs = boto3.client("sqs")
    messages = sqs.receive_message(QueueUrl=os.environ["QUEUE_URL"], MaxNumberOfMessages=10).get("Messages", [])
    assert sorted(json.loads(m["Body"])["user_id"] for m in messages) == ["helena", "jana"]


def test_raw_responses_are_partitioned_by_provider_user_and_day(aws, fake):
    fake.plays = [play(1)]
    collector.collect("jana")
    keys = [o["Key"] for o in boto3.client("s3").list_objects_v2(Bucket="sfw-raw-test")["Contents"]]
    assert len(keys) == 1
    assert keys[0].startswith("raw/provider=spotify/user=jana/dt=") and keys[0].endswith(".json")


def test_failure_of_unknown_user_does_not_create_a_ghost_profile(aws, fake):
    with pytest.raises(LookupError):
        collector.handler(sqs_event("nobody"), None)
    assert store.get_profile("nobody") is None


def test_rate_limit_delays_the_retry_as_long_as_spotify_asks(aws, fake):
    sqs, queue = boto3.client("sqs"), os.environ["QUEUE_URL"]
    sqs.send_message(QueueUrl=queue, MessageBody=json.dumps({"user_id": "jana"}),
                     MessageGroupId="jana", MessageDeduplicationId="tick-1")
    # Received with visibility 0: without the fix, the message would be visible again at once
    message = sqs.receive_message(QueueUrl=queue, VisibilityTimeout=0)["Messages"][0]
    fake.fail = spotify.RateLimited(120)
    with pytest.raises(spotify.RateLimited):
        collector.handler({"Records": [{"body": message["Body"],
                                        "receiptHandle": message["ReceiptHandle"]}]}, None)
    assert sqs.receive_message(QueueUrl=queue).get("Messages", []) == []  # hidden for 120 s
    assert store.get_profile("jana")["last_sync_status"] == "rate_limited"


def test_second_page_failure_preserves_checkpoint(aws, fake, monkeypatch):
    fake.plays = [play(0)]
    collector.collect("jana")
    old = store.get_profile("jana")["cursor_ms"]
    fake.plays += [play(m, f"t{m}{s}", s) for m in range(1, 7) for s in range(10)]
    original = fake.recently_played
    def failing(access_token, after_ms=None, before_ms=None):
        if before_ms is not None:
            raise spotify.SpotifyError("second page failed")
        return original(access_token, after_ms, before_ms)
    monkeypatch.setattr(spotify, "recently_played", failing)
    with pytest.raises(spotify.SpotifyError):
        collector.collect("jana")
    assert store.get_profile("jana")["cursor_ms"] == old
    assert len(stored("jana")) == 1
    monkeypatch.setattr(spotify, "recently_played", original)
    assert collector.collect("jana")["new_plays"] == 60
    assert collector.collect("jana")["new_plays"] == 0
    assert len(stored("jana")) == 61


def test_documented_next_page_overlap_is_deduplicated(aws, fake, monkeypatch):
    fake.plays = [play(0)]
    collector.collect("jana")
    url = "https://api.spotify.com/v1/me/player/recently-played?before=123"
    monkeypatch.setattr(spotify, "recently_played", lambda *a, **kw: {"items": [play(3), play(2)], "next": url})
    monkeypatch.setattr(spotify, "next_recent_page", lambda *a: {"items": [play(2), play(1)]})
    assert collector.collect("jana")["new_plays"] == 3
    assert len(stored("jana")) == 4


def test_repeated_page_fails_without_advancing(aws, fake, monkeypatch):
    fake.plays = [play(0)]
    collector.collect("jana")
    old = store.get_profile("jana")["cursor_ms"]
    page = {"items": [play(2)], "next": "https://api.spotify.com/v1/me/player/recently-played?before=123"}
    monkeypatch.setattr(spotify, "recently_played", lambda *a, **kw: page)
    monkeypatch.setattr(spotify, "next_recent_page", lambda *a: page)
    with pytest.raises(spotify.SpotifyError):
        collector.collect("jana")
    assert store.get_profile("jana")["cursor_ms"] == old
