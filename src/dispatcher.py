"""Leaves one collection task per group member in the queue. Triggered by EventBridge on a schedule,
or invoked by hand (with any payload) to force a collection during the demo."""
import datetime
import hashlib
import json
import os

import boto3

import store


def handler(event, context):
    # A scheduled event carries its own time: if EventBridge delivers it twice,
    # the deduplication id is the same and SQS keeps a single task per user.
    tick = (event or {}).get("time") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    sqs = boto3.client("sqs")
    members = store.group_members(os.environ["GROUP_ID"])
    for user_id in members:
        sqs.send_message(
            QueueUrl=os.environ["QUEUE_URL"],
            MessageBody=json.dumps({"user_id": user_id, "tick": tick}),
            MessageGroupId=user_id,
            MessageDeduplicationId=hashlib.sha256(f"{user_id}#{tick}".encode()).hexdigest(),
        )
    print(json.dumps({"event": "dispatched", "tick": tick, "users": members}))
    return {"tick": tick, "users": members}
