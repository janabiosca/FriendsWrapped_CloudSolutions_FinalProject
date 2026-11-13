# 001 · Terraform instead of SAM/CloudFormation

**Context.** The first version was a SAM template deployed with a shell script. The course
labs (5.1–5.3) use Terraform with a remote S3 backend and GitHub Actions.

**Decision.** All infrastructure is Terraform: one reusable module (`infra/modules/ingestion`)
and one root per environment (`infra/envs/dev`, `infra/envs/prod`) in a mono-repo.

**Alternatives.**
- *SAM/CloudFormation*: no state file to manage and automatic rollback, and Lambda packaging
  is simpler. But it is AWS-only, and plan-in-PR is harder to show than `terraform plan`.
- *Clicking in the console (ClickOps)*: no history, impossible to replicate between the
  sandbox and our account, and nobody knows what exists.

**Consequences.** We manage a state file (S3, versioned, encrypted, native lock file). The
same module deploys two different environments by changing variables. We can unit test the
module with a mocked provider (`terraform test`).
