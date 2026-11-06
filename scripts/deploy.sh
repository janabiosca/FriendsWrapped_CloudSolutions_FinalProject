#!/usr/bin/env bash
# Deploys the stack with the plain AWS CLI (no SAM CLI needed).
#
#   scripts/deploy.sh <spotify-client-id> [schedule] [alarm-email]
#   scripts/deploy.sh abc123                                  # hourly collection
#   scripts/deploy.sh abc123 "rate(5 minutes)" me@example.com # demo configuration
#
# Needs the AWS Academy credentials in the environment or in ~/.aws/credentials.
set -euo pipefail
cd "$(dirname "$0")/.."

CLIENT_ID=${1:?usage: scripts/deploy.sh <spotify-client-id> [schedule] [alarm-email]}
SCHEDULE=${2:-rate(1 hour)}
ALARM_EMAIL=${3:-}
STACK=${STACK:-sfw}
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}

ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
ARTIFACTS="sfw-artifacts-$ACCOUNT-$AWS_DEFAULT_REGION"
aws s3api head-bucket --bucket "$ARTIFACTS" 2>/dev/null || aws s3 mb "s3://$ARTIFACTS"

aws cloudformation package --template-file template.yaml --s3-bucket "$ARTIFACTS" \
  --output-template-file packaged.yaml
aws cloudformation deploy --template-file packaged.yaml --stack-name "$STACK" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND --no-fail-on-empty-changeset \
  --parameter-overrides "SpotifyClientId=$CLIENT_ID" "CollectSchedule=$SCHEDULE" "AlarmEmail=$ALARM_EMAIL"
aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Outputs' --output table
