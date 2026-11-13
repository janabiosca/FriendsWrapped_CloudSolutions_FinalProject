# Customer managed key for the raw data lake bucket and the alarm topic. Compared with the
# AWS managed defaults it lets us decide who may decrypt (key policy), rotates every year and
# every use is logged in CloudTrail. Costs ~1 USD/month; S3 bucket keys keep requests cheap.
data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "kms" {
  count = var.customer_managed_key ? 1 : 0

  # Standard delegation: IAM policies of this account decide who can use the key.
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"] # in a key policy "*" means "this key"

    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  # CloudWatch alarms must encrypt the messages they publish to the encrypted SNS topic.
  statement {
    sid       = "CloudWatchAlarmsPublishToEncryptedTopic"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_kms_key" "data" {
  count                   = var.customer_managed_key ? 1 : 0
  description             = "${var.name}: raw listening data and alarm notifications"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.kms[0].json
}

resource "aws_kms_alias" "data" {
  count         = var.customer_managed_key ? 1 : 0
  name          = "alias/${var.name}-data"
  target_key_id = aws_kms_key.data[0].key_id
}

locals {
  kms_key_arn = var.customer_managed_key ? aws_kms_key.data[0].arn : null
}
