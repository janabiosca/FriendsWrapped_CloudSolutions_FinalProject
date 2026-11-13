# 005 · AWS Academy for dev, own account for prod

**Context.** We have an AWS Academy sandbox and access to a regular AWS account. In Academy,
IAM roles cannot be created (everything runs as `LabRole`), credentials expire with each lab
session, and the sandbox is not meant to run unattended for weeks. Spotify keeps only the last
50 plays, so any collection that does not run is history lost forever.

**Decision.** Two environments from the same module:
- `dev` (Academy): `LabRole`, AWS managed encryption, destroyable. For experiments and labs.
- `prod` (own account): one least-privilege role per function, deletion protection, customer
  managed KMS key, always on. The real history is collected here. GitHub Actions logs in with
  OIDC (`infra/bootstrap/github-oidc`): no AWS keys stored in GitHub.

**Alternatives.** Everything in Academy (free, but gaps in the data and no least privilege),
or everything in the own account (no safe place to experiment).

**Consequences.** About 3 USD/month in prod. The module has two variables (`lab_role_name`,
`customer_managed_key`) that switch between both worlds, covered by `terraform test`.

## Academy S3 read restriction

The lab service control policy explicitly denies GetBucketObjectLockConfiguration.
The AWS provider reads it while managing aws_s3_bucket, so dev reuses the existing
bucket via existing_raw_bucket. Its encryption, public access block, TLS policy,
versioning and lifecycle are still managed by Terraform. The bucket itself must
be bootstrapped separately (as with the state bucket) and is retained on destroy.
Prod continues to manage its bucket normally. This does not change lab permissions.
