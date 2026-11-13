# 003 · Idempotent collection: conditional writes and a cursor that moves last

**Context.** "Saving our songs every hour without losing or repeating any" was the first
difficulty in the project draft. Retries (SQS, Lambda) mean the same collection can run twice.

**Decision.**
- Each play is one DynamoDB item, key `USER#<id>` / `PLAY#<played_at>#<track_id>`, written
  with `attribute_not_exists(PK)`: writing it twice is a no-op, and the same song played twice
  has two different `played_at`, so it counts twice.
- The collector asks Spotify only for plays after a per-user cursor (`after=<unix ms>`), and
  moves the cursor **only after** every play is stored. A crash before that retries from the
  same cursor, and the conditional writes skip what was already saved.
- If 50 plays (Spotify's maximum) arrive after the cursor, older plays may have been dropped
  by Spotify: the run is flagged as a *possible gap* and an alarm fires.

**Alternatives.** Deduplicating later (in a batch job) would also work, but the web app
reads DynamoDB directly and would show duplicates in the meantime.

**Consequences.** Covered by tests: collecting twice, crash before the cursor moves, same
song twice, full page gap.
