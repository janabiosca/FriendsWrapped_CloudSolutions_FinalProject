# 006 · Encryption choices and accepted security findings

**Context.** Trivy (SAST for infrastructure) runs in CI and blocks on HIGH/CRITICAL findings.

**Decision.**
- Data in transit: HTTPS only (Spotify API, AWS APIs; the raw bucket denies non-TLS requests).
- Data at rest in prod: customer managed KMS key (yearly rotation) for the raw S3 bucket and
  the alarm SNS topic; key policy lets CloudWatch publish to the encrypted topic.
  DynamoDB, SQS and Secrets Manager use AWS managed encryption.
- `dev` uses AWS managed encryption everywhere (Academy limits, throwaway data).

**Accepted findings (LOW), reviewed and not fixed:**

| Trivy check | Why we accept it |
|---|---|
| AWS-0017 Log group not encrypted with a CMK | Logs contain user ids and counts, no listening data or tokens; CloudWatch already encrypts them |
| AWS-0025 DynamoDB uses the AWS managed key | Encrypted at rest with KMS; a CMK adds cost and key-policy work for little gain with 4 users |
| AWS-0089 S3 access logging disabled | Only our Lambdas write to the bucket, and CloudTrail records management events |

**Consequences.** Review this note if the data changes (e.g. emails or locations stored in
S3) or the group grows beyond friends.
