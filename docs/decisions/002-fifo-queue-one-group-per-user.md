# 002 · SQS FIFO queue with one message group per user

**Context.** Every hour all friends must be collected. Spotify may return a new refresh token
on each refresh, and the old one stops working. If two runs refreshed the same user's token
at once, one of them would save a token that is already dead.

**Decision.** A dispatcher Lambda puts one message per user in an SQS **FIFO** queue with
`MessageGroupId = user_id`; the collector processes one message per invocation
(`batch_size = 1`). After 3 failed attempts the message moves to a dead-letter queue and a
CloudWatch alarm emails us.

**Alternatives.**
- *One Lambda looping over the 4 users*: one failure (or a timeout) affects everybody, and a
  retry repeats the users that had already succeeded.
- *Standard SQS queue*: same isolation and retries, but nothing stops two copies of the same
  user's task running in parallel.
- *Step Functions Map state*: also valid, more expensive per run and more than we need for a
  single step.

**Consequences.** Users are collected in parallel but never concurrently with themselves.
Messages deduplicate on the schedule's own timestamp, so a duplicated EventBridge delivery
queues each user only once. The queue visibility timeout is 6× the function timeout, as AWS
recommends for Lambda triggers.
