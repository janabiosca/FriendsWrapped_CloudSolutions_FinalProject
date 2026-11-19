# Spotify Friends Wrapped

Listening statistics and a weekly Wrapped for a group of 4 friends, built serverless on AWS.

Spotify returns at most **50 plays per request** and does not guarantee unlimited historical access. The first
version (v0.2, *ingestion*) collects every friend's plays every hour, even when nobody has the
app open, with conditional writes to avoid duplicates and warnings about possible gaps. Everything else (stats, web app, Wrapped, concerts)
is built on top of this history.

## Architecture (v0.2)

```
EventBridge (hourly) ─► dispatcher λ ─► SQS FIFO (1 message group per user) ─► collector λ ─► DynamoDB (plays, profiles)
                                              │ 3 failures                         │   ├─► S3 raw zone (Hive partitions)
                                              ▼                                    │   └─► Secrets Manager (refresh tokens)
                                        Dead-letter queue ─► CloudWatch alarm ─► SNS ─► email
                                                                  ▲
                         log metric filters (reauth required, possible gap, heartbeat)
```

| Service | Role | Why this one |
|---|---|---|
| EventBridge | Hourly schedule | Serverless cron, nothing to keep running |
| Lambda (dispatcher, collector) | Fan-out and collection | Runs a few seconds per hour: pay per use |
| SQS FIFO + DLQ | One task per user, retries, isolation | A failure only retries that user; FIFO groups stop two concurrent refreshes of the same token |
| DynamoDB (on-demand, PITR) | Plays, profiles, group membership | Key-value access by user and time; conditional writes make collection idempotent |
| S3 (raw zone) | Raw Spotify responses | Cheap durable data lake for Glue/Athena later; rebuild stats if the schema changes |
| Secrets Manager | Spotify refresh tokens | Encrypted, audited, rotated tokens stay out of code and out of Terraform state |
| KMS (prod) | Customer managed key for S3 and SNS | Key policy decides who decrypts; yearly rotation; CloudTrail audit |
| CloudWatch + SNS | Alarms by email | We learn about failures before plays are lost |
| X-Ray | Tracing | One collection end to end: Spotify, Secrets Manager, DynamoDB, S3 |

Design decisions with their alternatives are in [docs/decisions](docs/decisions).

## Repository layout

```
infra/
  modules/ingestion/      reusable module (+ tests/ with a mocked AWS provider)
  envs/dev/               AWS Academy sandbox (LabRole, destroyable)
  envs/prod/              our own account (least-privilege roles, protected data, KMS)
  bootstrap/github-oidc/  one-off: lets GitHub Actions log in to AWS without stored keys
src/                      Lambda code (standard library + boto3 only)
tests/                    pytest + moto (in-memory AWS), Spotify faked
scripts/                  bootstrap_state.sh, connect_spotify.py
.github/workflows/        ci.yml (every push/PR), release.yml (deploy on release)
```

## Environments

| | `dev` | `prod` |
|---|---|---|
| Account | AWS Academy sandbox | our own AWS account |
| IAM | every function runs as `LabRole` (roles cannot be created) | one least-privilege role per function |
| Data | destroyable (`protect_data = false`) | DynamoDB deletion protection, S3 kept |
| Encryption | AWS managed keys | customer managed KMS key |
| Always on | not guaranteed: lab sessions expire and the sandbox can be reset | yes: the real listening history lives here |

## Deploy

Requirements: Terraform >= 1.10, AWS CLI, Python 3.12+, credentials of the target account.

1. **Spotify app** (once): create it at developer.spotify.com/dashboard, add
   `http://127.0.0.1:8888/callback` as redirect URI and the 4 friends as users.
2. **State bucket** (once per account; the only resource outside Terraform):
   ```bash
   scripts/bootstrap_state.sh prod      # writes infra/envs/prod/backend.conf
   ```
3. **Settings**: `cp infra/envs/prod/terraform.tfvars.example infra/envs/prod/terraform.tfvars` and fill it.
4. **Apply**:
   ```bash
   terraform -chdir=infra/envs/prod init -backend-config=backend.conf
   terraform -chdir=infra/envs/prod plan
   terraform -chdir=infra/envs/prod apply
   ```
   Confirm the SNS subscription email AWS sends to `alarm_email`.
5. **Connect each friend** (each one logs in with her own Spotify account):
   ```bash
   python scripts/connect_spotify.py --env prod --client-id <id> --user-id jana --name Jana --email jana@example.com
   ```

Use `dev` the same way in the AWS Academy sandbox (`scripts/bootstrap_state.sh dev`, `infra/envs/dev`).
`terraform destroy` removes a `dev` environment completely; in `prod` it is blocked by deletion protection on purpose.

## CI/CD (GitOps)

The repository is the single source of truth: infrastructure changes only through pull requests.

- **ci.yml**, on every push and pull request: Python tests, `terraform fmt -check`,
  `terraform test` (module tests with mocked AWS), `terraform validate` of each environment,
  Trivy (blocks on HIGH/CRITICAL misconfigurations and on committed secrets) and, on pull
  requests, a `terraform plan` posted as a PR comment.
- **release.yml**, when a GitHub release is published (`v0.2.0`, `v0.3.0`…): tests, then `terraform apply`.
  Give the GitHub environment `prod` required reviewers so production deploys need an approval.

Repository configuration (Settings → Secrets and variables → Actions):

| Name | Type | Value |
|---|---|---|
| `TF_ENV` | variable | `dev` or `prod` |
| `TF_STATE_BUCKET` | variable | bucket printed by `bootstrap_state.sh` (the plan job is skipped until it is set) |
| `AWS_REGION` | variable | `us-east-1` |
| `SPOTIFY_CLIENT_ID` | variable | Spotify app client ID |
| `ALARM_EMAIL` | variable | team email |
| `AWS_PLAN_ROLE_ARN`, `AWS_APPLY_ROLE_ARN` | variables | own account: outputs of `infra/bootstrap/github-oidc` (short-lived OIDC credentials) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | secrets | AWS Academy only (used when the role variables are empty); they expire with the lab session |

To create the OIDC roles in the own account (once, with admin credentials):

```bash
terraform -chdir=infra/bootstrap/github-oidc init -backend-config=../../envs/prod/backend.conf -backend-config="key=bootstrap/github-oidc.tfstate"
terraform -chdir=infra/bootstrap/github-oidc apply -var github_repository=<owner>/<repo> -var state_bucket=<bucket>
```

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                                 # Lambda logic against in-memory AWS
cd infra/modules/ingestion && terraform init && terraform test  # module logic, mocked AWS
```

The tests reproduce the difficulties in the project draft: collecting twice never duplicates,
a crash before the cursor moves never double counts, the same song played twice counts twice,
one friend failing does not affect the others, rotated refresh tokens are saved, rate limits
delay the retry, and a full page of 50 new plays is flagged as a possible gap.

## Demo

- Collect now instead of waiting for the hour:
  `aws lambda invoke --function-name $(terraform -chdir=infra/envs/prod output -raw dispatcher_function) /dev/stdout`
- Or deploy with `collect_schedule = "rate(5 minutes)"` for the day.
- Failure and recovery: a broken token sends that friend's task to the dead-letter queue and
  the alarm emails us; after reconnecting, *SQS → dead-letter queue → Start DLQ redrive*.

## Manual steps (not in Terraform, and why)

| Step | Why it is manual |
|---|---|
| State bucket (`bootstrap_state.sh`) | Terraform needs it before it can run |
| Spotify app and redirect URI | Outside AWS |
| Spotify tokens (`connect_spotify.py`) | Secrets must never go through Terraform state (stored in plain text) |
| Confirm the SNS email | AWS requires the recipient to opt in |
| `infra/bootstrap/github-oidc` | Needs admin rights once; afterwards CI deploys without keys |

## Cost (prod, 4 users, hourly)

About 3 USD/month: Secrets Manager 4 × 0.40, KMS key 1.00, CloudWatch alarms ~0.50.
Lambda, DynamoDB on-demand, SQS, S3 and X-Ray stay within the free tier at this volume.

## Known limitations

- Minutes are estimated from track durations: a skipped song may count as complete.
- History starts when a friend connects. `scripts/import_spotify_history.py` supports importing Spotify history exports when available.
- After the initial seed, collection follows available pages (up to 20 per run), including
  an older-time request when a full page has no next link. The checkpoint only advances
  after all fetched pages are stored. Spotify may still withhold older history; a full
  page after a checkpoint is flagged conservatively as a possible gap.
- A pagination loop, failed request or the 20-page safety limit fails the collection
  without advancing its checkpoint. It is not silently marked complete.
- `dev` is a sandbox: check whether scheduled collections keep running after the AWS Academy
  session ends before relying on it; the real history is collected in `prod`.

## Local dashboard preview

Run `.venv/bin/python scripts/preview_dashboard.py`, then open http://127.0.0.1:8765.
The preview is read-only, bound to loopback on this Mac, and uses the current local
AWS credentials to query Jana's recorded plays. It never reads Spotify tokens.
Filters: all recorded history, the last seven calendar days, or today (Europe/Madrid).
Refresh reloads stored statistics; collection is independently scheduled in AWS.
This is not yet the hosted group application: authentication, group authorization,
and an AWS-hosted API/frontend remain to be implemented.


## Remote Spotify connection (AWS Academy)

`src/spotify_connect.py` handles invitation-only PKCE authorization over HTTPS.
`infra/connect` is an independent Terraform stack using the existing Academy LabRole,
ingestion table and secret prefix. Its state uses the existing backend bucket with
key `dev/spotify-connect.tfstate`.

```bash
terraform -chdir=infra/connect init -backend-config=../envs/dev/backend.conf -backend-config="key=dev/spotify-connect.tfstate"
terraform -chdir=infra/connect plan -var="spotify_client_id=<app client id>"
terraform -chdir=infra/connect apply -var="spotify_client_id=<app client id>"
terraform -chdir=infra/connect output -raw spotify_redirect_uri
```

Add that exact redirect URI in the Spotify application settings. The owner must
also add each friend in Spotify User Management. Issue invitations locally:

```bash
.venv/bin/python scripts/invite_spotify.py --user-id anna --name Anna --base-url <connect_base_url>
.venv/bin/python scripts/invite_spotify.py --user-id helena --name Helena --base-url <connect_base_url>
```

Send each URL privately to its named recipient. Invitations expire after seven days
and are claimed once. Browser-bound sessions expire after ten minutes. Tokens go
directly to Secrets Manager. An interrupted save may need a replacement invitation;
account binding prevents replacing the member with another Spotify account.
This stack provides onboarding only. It does not expose listening data or provide
the dashboard's sign-in. Its availability depends on the Academy environment.


## Hosted group dashboard (AWS Academy)

`infra/dashboard` deploys the web page, API Gateway JWT authorization, and a Cognito
user pool. The existing `sfw-dev-connect` table stores approved email hashes mapped
to internal member IDs. Public registration is rejected unless the email is approved.
Email verification and active group membership are checked before any statistics are
returned. Profile statistics are restricted to Spotify members of the authenticated user's group.

```bash
terraform -chdir=infra/dashboard init -backend-config=../envs/dev/backend.conf -backend-config="key=dev/dashboard.tfstate"
terraform -chdir=infra/dashboard plan
terraform -chdir=infra/dashboard apply
terraform -chdir=infra/dashboard output -raw dashboard_url
.venv/bin/python scripts/allow_dashboard_member.py --user-id anna --email <approved-email>
```

The user creates her own dashboard password in Cognito and verifies her email.
Spotify authorization remains a separate, invitation-based step. The browser uses
PKCE, keeps the access token in session storage, and requests a fresh login after
expiry. API Gateway checks signature, issuer, audience, expiry and the `openid`
scope; Lambda checks verified email, the approved mapping, and current membership.
The Academy deployment uses LabRole and depends on the laboratory's availability.


Group observers can register and browse the same group profiles without connecting
Spotify. Register an observer with `scripts/allow_dashboard_member.py --user-id pati
--email <approved-email> --viewer --name Pati`. Observers use `VIEWER#` membership
records and are excluded from Spotify collection and listening rankings. The profile
selector allows every group member to view the group's individual listening summaries.


## Weekly Wrapped generation

`infra/wrapped` deploys a Standard Step Functions workflow and an EventBridge
Scheduler schedule for Mondays at 09:00 Europe/Madrid. Each run summarizes the
previous complete Monday–Sunday week, then archives HTML and PDF reports in the private
raw bucket under `wrapped/group=<group>/week=<monday>/`. The workflow passes only
object references between tasks. Conditional writes preserve the original snapshot
and report across retries. The execution start time fixes week selection during retries.

```bash
terraform -chdir=infra/wrapped init -backend-config=../envs/dev/backend.conf -backend-config="key=dev/wrapped.tfstate"
bash scripts/build_wrapped_package.sh
terraform -chdir=infra/wrapped plan
terraform -chdir=infra/wrapped apply
```

An authenticated group member or observer can download the last complete week's
PDF report from the dashboard. Generation and download do not send email. SES account
and identity configuration queries were denied in the current Academy session;
email delivery remains pending. The schedule depends on Academy availability.


The account label always identifies the signed-in member. Selecting a friend's profile
changes the statistics and heading while retaining that account label. Observers use
their own account name and can inspect the group's Spotify profiles. Wrapped PDFs
are generated with ReportLab in a Lambda package built for Python 3.13 on Linux x86_64;
run the package build before planning changes to the Wrapped deployment.


GitHub Actions validates the ingestion module and the connection, dashboard and
Wrapped stacks. Academy PR plans and release deployments use separate state keys
for each stack. PDF dependencies are built before planning or deploying the Wrapped
function. AWS repository variables and expiring Academy credentials must be configured
before cloud plans and deployments can run; local source publication alone runs CI.
