"""Storage: DynamoDB (plays, profiles, membership), Secrets Manager (Spotify tokens), S3 (raw responses)."""
import datetime
import json
import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError


def _table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _secret_id(user_id):
    return os.environ["SECRET_PREFIX"] + user_id


# --- membership and profiles -------------------------------------------------

def add_member(group_id, user_id, display_name, email=None):
    table = _table()
    table.put_item(Item={"PK": f"GROUP#{group_id}", "SK": f"MEMBER#{user_id}", "user_id": user_id})
    # if_not_exists keeps the sync cursor when a user reconnects Spotify
    table.update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression="SET user_id = :u, group_id = :g, display_name = :n, email = :e, "
                         "connected_at = :t, cursor_ms = if_not_exists(cursor_ms, :zero)",
        ExpressionAttributeValues={":u": user_id, ":g": group_id, ":n": display_name,
                                   ":e": email or "", ":t": _now(), ":zero": 0},
    )


def group_members(group_id):
    response = _table().query(
        KeyConditionExpression=Key("PK").eq(f"GROUP#{group_id}") & Key("SK").begins_with("MEMBER#"))
    return [item["user_id"] for item in response["Items"]]


def get_profile(user_id):
    return _table().get_item(Key={"PK": f"USER#{user_id}", "SK": "PROFILE"}).get("Item")


# --- plays -------------------------------------------------------------------

def put_play(user_id, play):
    """Stores one play. Returns False if it was already stored, so collecting twice never duplicates."""
    track = play["track"]
    track_id = track.get("id") or track.get("uri") or track["name"]  # local files have no id
    try:
        _table().put_item(
            Item={
                "PK": f"USER#{user_id}",
                "SK": f"PLAY#{play['played_at']}#{track_id}",
                "played_at": play["played_at"],
                "track_id": track_id,
                "track_name": track["name"],
                "artists": [a["name"] for a in track.get("artists", [])],
                "artist_ids": [a["id"] for a in track.get("artists", []) if a.get("id")],
                "album": (track.get("album") or {}).get("name", ""),
                "duration_ms": track.get("duration_ms", 0),
                **({"ms_played": play["ms_played"]} if "ms_played" in play else {}),
                "context_type": (play.get("context") or {}).get("type", ""),
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def plays_between(user_id, start_iso, end_iso):
    """Plays with start_iso <= played_at < end_iso (ISO timestamps or date prefixes, UTC)."""
    table, kwargs, items = _table(), {}, []
    while True:
        response = table.query(
            KeyConditionExpression=Key("PK").eq(f"USER#{user_id}")
            & Key("SK").between(f"PLAY#{start_iso}", f"PLAY#{end_iso}"),
            **kwargs)
        items += response["Items"]
        if "LastEvaluatedKey" not in response:
            return [i for i in items if i["played_at"] < end_iso]
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


# --- sync state --------------------------------------------------------------

def record_sync(user_id, cursor_ms, new_plays, possible_gap):
    _table().update_item(
        Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
        UpdateExpression="SET cursor_ms = :c, last_sync_at = :t, last_sync_status = :ok "
                         "REMOVE last_error ADD total_plays :n, possible_gaps :g",
        ExpressionAttributeValues={":c": cursor_ms, ":t": _now(), ":ok": "ok",
                                   ":n": new_plays, ":g": 1 if possible_gap else 0},
    )


def record_failure(user_id, status, error):
    """Flags the failure on the profile. Returns False for unknown users instead of creating a ghost profile."""
    try:
        _table().update_item(
            Key={"PK": f"USER#{user_id}", "SK": "PROFILE"},
            UpdateExpression="SET last_failure_at = :t, last_sync_status = :s, last_error = :e",
            ConditionExpression="attribute_exists(PK)",
            ExpressionAttributeValues={":t": _now(), ":s": status, ":e": error[:500]},
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


# --- Spotify tokens ----------------------------------------------------------

def get_token(user_id):
    value = boto3.client("secretsmanager").get_secret_value(SecretId=_secret_id(user_id))
    return json.loads(value["SecretString"])


def save_token(user_id, token):
    client, body = boto3.client("secretsmanager"), json.dumps(token)
    try:
        client.put_secret_value(SecretId=_secret_id(user_id), SecretString=body)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        client.create_secret(Name=_secret_id(user_id), SecretString=body)


# --- raw archive -------------------------------------------------------------

def raw_key(provider, user_id, moment):
    """Hive-style partitions, so Glue and Athena can prune by provider, user and day."""
    return f"raw/provider={provider}/user={user_id}/dt={moment:%Y-%m-%d}/{moment:%H%M%S%f}.json"


def archive_raw(user_id, page, provider="spotify"):
    now = datetime.datetime.now(datetime.timezone.utc)
    key = raw_key(provider, user_id, now)
    boto3.client("s3").put_object(Bucket=os.environ["RAW_BUCKET"], Key=key,
                                  Body=json.dumps(page).encode(), ContentType="application/json")
