# 004 · Spotify tokens in Secrets Manager, written outside Terraform

**Context.** The collector needs each friend's Spotify refresh token. Terraform stores every
attribute of the resources it manages in plain text in its state file.

**Decision.** `scripts/connect_spotify.py` runs the OAuth2 Authorization Code + PKCE login
(no client secret exists anywhere) and writes the refresh token straight to Secrets Manager
as `<env>/spotify/<user_id>`. Terraform never creates or reads these secrets; IAM allows the
collector to read and rotate only that prefix.

**Alternatives.**
- *Secret in Terraform (`aws_secretsmanager_secret_version`)*: the token would end up in the
  state file.
- *DynamoDB attribute encrypted with KMS*: cheaper (Secrets Manager costs 0.40 USD/secret/month),
  but we would write the encryption code ourselves.
- *Environment variable / code*: anyone with read access to the function sees it.

**Consequences.** `terraform destroy` does not delete the tokens (Secrets Manager keeps a
recovery window). Connecting a friend is a manual step documented in the README.
