# History pagination and checkpoints

Spotify documents 50 items per request, not guaranteed unlimited historical retention.
The first connection deliberately seeds the most recent page. Subsequent runs collect
new plays after the saved checkpoint, follow next links restricted to the Spotify
history endpoint, and attempt an older before cursor for full pages without next links.
Only plays newer than the original checkpoint are inserted. In-page and cross-page
overlap is deduplicated; conditional DynamoDB writes also protect retries.

All page reads finish before writes; the checkpoint advances only after raw pages and
plays are stored. Repeated pages/URLs, HTTP failures and the 20-page bound fail safely.
A full page after a checkpoint remains a conservative possible-gap signal, even when
additional pages are retrieved: API exhaustion is not proof of complete listening history.
Raw archive keys include microseconds to avoid same-second page overwrites.

Execution timeout is 120 seconds with a 720-second SQS visibility timeout. The page
limit is a guard, not resumable unlimited backfill. A future continuation design can
checkpoint a fixed retrieval window across tasks without skipping unfinished history.

Tests cover 60 pending plays, later-page failure and retry, overlapping pages, repeated
pages, and rejection of pagination links that could disclose a token to another host.
