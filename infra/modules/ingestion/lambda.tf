locals {
  function_timeout = 120
  secret_prefix    = "${var.name}/spotify/"

  functions = {
    dispatcher = {
      handler     = "dispatcher.handler"
      description = "Leaves one collection task per group member in the queue"
    }
    collector = {
      handler     = "collector.handler"
      description = "Collects the new plays of one user"
    }
  }

  environment = {
    TABLE_NAME        = aws_dynamodb_table.main.name
    RAW_BUCKET        = local.raw_bucket_name
    QUEUE_URL         = aws_sqs_queue.collect.url
    GROUP_ID          = var.group_id
    SPOTIFY_CLIENT_ID = var.spotify_client_id
    SECRET_PREFIX     = local.secret_prefix
  }
}

# Both functions share one package: the code is standard library + boto3 (already in the runtime).
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${var.build_dir}/${var.name}-lambda.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

# Created explicitly (instead of letting Lambda create it) so the retention is managed here.
resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${var.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fn" {
  for_each = local.functions

  function_name    = "${var.name}-${each.key}"
  description      = each.value.description
  role             = local.create_roles ? aws_iam_role.fn[each.key].arn : data.aws_iam_role.shared[0].arn
  handler          = each.value.handler
  runtime          = "python3.13"
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = local.function_timeout
  memory_size      = 256

  environment {
    variables = local.environment
  }

  tracing_config {
    mode = "Active" # X-Ray: see each collection end to end (Spotify, Secrets Manager, DynamoDB, S3)
  }

  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn]
}

resource "aws_lambda_event_source_mapping" "collect" {
  event_source_arn = aws_sqs_queue.collect.arn
  function_name    = aws_lambda_function.fn["collector"].arn
  batch_size       = 1 # one user per invocation: a failure only retries that user
}

resource "aws_cloudwatch_event_rule" "collect" {
  name                = "${var.name}-collect"
  description         = "Starts a collection of every group member"
  schedule_expression = var.collect_schedule
}

resource "aws_cloudwatch_event_target" "collect" {
  rule = aws_cloudwatch_event_rule.collect.name
  arn  = aws_lambda_function.fn["dispatcher"].arn
}

resource "aws_lambda_permission" "events" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["dispatcher"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.collect.arn
}
