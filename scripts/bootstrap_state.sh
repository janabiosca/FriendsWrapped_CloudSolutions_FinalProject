#!/usr/bin/env bash
# Creates the S3 bucket that stores the Terraform state. Run it once per AWS account
# (once in the AWS Academy sandbox for dev, once in our own account for prod):
#
#   scripts/bootstrap_state.sh dev
#   scripts/bootstrap_state.sh prod
#
# It is the only resource created outside Terraform: Terraform needs it before it can run
# (chicken and egg). State locking uses the native S3 lock file (Terraform >= 1.10), so no
# DynamoDB lock table is needed.
set -euo pipefail

ENV=${1:?usage: scripts/bootstrap_state.sh <dev|prod>}
REGION=${AWS_DEFAULT_REGION:-us-east-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET="tf-state-sfw-$ACCOUNT"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  echo "State bucket $BUCKET already exists"
elif [ "$REGION" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
fi

# The state lists every resource and may contain sensitive values: private, encrypted, versioned.
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled

CONF="$(dirname "$0")/../infra/envs/$ENV/backend.conf"
cat > "$CONF" <<CONF
bucket       = "$BUCKET"
key          = "$ENV/terraform.tfstate"
region       = "$REGION"
use_lockfile = true
encrypt      = true
CONF
echo "State bucket: $BUCKET"
echo "Wrote $CONF. Next: terraform -chdir=infra/envs/$ENV init -backend-config=backend.conf"
