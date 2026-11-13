# In a normal account each function gets its own role with only what it uses (least privilege).
# In AWS Academy roles cannot be created, so every function runs as the existing LabRole.
locals {
  create_roles = var.lab_role_name == ""

  # Exactly the calls each function makes (see src/store.py and src/dispatcher.py).
  permissions = {
    dispatcher = [
      {
        sid       = "ReadGroupMembers"
        actions   = ["dynamodb:Query"]
        resources = [aws_dynamodb_table.main.arn]
      },
      {
        sid       = "QueueCollections"
        actions   = ["sqs:SendMessage"]
        resources = [aws_sqs_queue.collect.arn]
      },
    ]
    collector = [
      {
        sid       = "ReadQueue"
        actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
        resources = [aws_sqs_queue.collect.arn]
      },
      {
        sid       = "StorePlaysAndProfiles"
        actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"]
        resources = [aws_dynamodb_table.main.arn]
      },
      {
        # Only this stack's Spotify tokens. Secrets Manager adds a random suffix to every ARN.
        sid       = "ReadAndRotateSpotifyTokens"
        actions   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        resources = ["arn:${local.partition}:secretsmanager:${local.region}:${local.account_id}:secret:${local.secret_prefix}*"]
      },
      {
        sid       = "ArchiveRawResponses"
        actions   = ["s3:PutObject"]
        resources = ["${local.raw_bucket_arn}/raw/*"]
      },
    ]
  }

  # Writing to the SSE-KMS bucket needs a data key from our KMS key.
  kms_permissions = var.customer_managed_key ? [
    {
      sid       = "EncryptRawResponses"
      actions   = ["kms:GenerateDataKey"]
      resources = [aws_kms_key.data[0].arn]
    },
  ] : []

  # Taken from a resource ARN to avoid data sources whose attributes changed between provider versions.
  arn_parts  = split(":", aws_sqs_queue.collect.arn)
  partition  = local.arn_parts[1]
  region     = local.arn_parts[3]
  account_id = local.arn_parts[4]
}

data "aws_iam_role" "shared" {
  count = local.create_roles ? 0 : 1
  name  = var.lab_role_name
}

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.create_roles ? local.functions : {}
  name               = "${var.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

data "aws_iam_policy_document" "fn" {
  for_each = local.create_roles ? local.functions : {}

  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  statement {
    sid     = "SendTraces"
    actions = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    # X-Ray has no resource-level permissions: "*" is the only possible value.
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = concat(local.permissions[each.key], each.key == "collector" ? local.kms_permissions : [])
    content {
      sid       = statement.value.sid
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.create_roles ? local.functions : {}
  name     = "least-privilege"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}
