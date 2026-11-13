# Design decisions

One short note per decision: context, what we chose, the alternatives we rejected and the
consequences. They answer "why this service and not another one" for the report and the
presentation. New decisions get the next number; a changed decision gets a new note that
supersedes the old one.

| # | Decision |
|---|---|
| [001](001-terraform-over-sam.md) | Terraform instead of SAM/CloudFormation |
| [002](002-fifo-queue-one-group-per-user.md) | SQS FIFO queue with one message group per user |
| [003](003-idempotent-collection.md) | Idempotent collection: conditional writes and a cursor that moves last |
| [004](004-tokens-outside-terraform-state.md) | Spotify tokens in Secrets Manager, written outside Terraform |
| [005](005-academy-sandbox-vs-own-account.md) | AWS Academy for dev, own account for prod |
| [006](006-encryption-and-accepted-findings.md) | Encryption choices and accepted security findings |
