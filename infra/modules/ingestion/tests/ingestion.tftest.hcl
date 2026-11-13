# Unit tests of the module with a mocked AWS provider: no account, no cost, run in CI on every PR.
#   cd infra/modules/ingestion && terraform init && terraform test

# The provider validates ARN formats, so mocked resources need realistic ARNs.
mock_provider "aws" {
  mock_resource "aws_sqs_queue" {
    defaults = { arn = "arn:aws:sqs:us-east-1:123456789012:mocked" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:us-east-1:123456789012:mocked" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:mocked" }
  }
  mock_resource "aws_cloudwatch_event_rule" {
    defaults = { arn = "arn:aws:events:us-east-1:123456789012:rule/mocked" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:mocked" }
  }
  mock_resource "aws_dynamodb_table" {
    defaults = { arn = "arn:aws:dynamodb:us-east-1:123456789012:table/mocked" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::mocked" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mocked" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:123456789012:key/mocked" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/LabRole" }
  }
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
}

variables {
  name              = "sfw-test"
  spotify_client_id = "client"
  source_dir        = "../../../src"
  build_dir         = ".build-test"
}

run "academy_runs_every_function_as_the_lab_role" {
  command = apply

  variables {
    lab_role_name        = "LabRole"
    protect_data         = false
    customer_managed_key = false
  }

  assert {
    condition     = length(aws_kms_key.data) == 0 && aws_sns_topic.alarms.kms_master_key_id == null
    error_message = "No customer managed key in AWS Academy"
  }

  assert {
    condition     = length(aws_iam_role.fn) == 0
    error_message = "AWS Academy does not allow creating IAM roles"
  }

  assert {
    condition     = alltrue([for f in aws_lambda_function.fn : f.role == "arn:aws:iam::123456789012:role/LabRole"])
    error_message = "Every function must run as LabRole in AWS Academy"
  }

  assert {
    condition     = aws_s3_bucket.raw[0].force_destroy && !aws_dynamodb_table.main.deletion_protection_enabled
    error_message = "A sandbox must be destroyable"
  }
}

run "own_account_gets_one_least_privilege_role_per_function" {
  command = apply

  assert {
    condition     = length(aws_iam_role.fn) == 2
    error_message = "Expected one role for the dispatcher and one for the collector"
  }

  assert {
    condition = contains(
      flatten([for s in data.aws_iam_policy_document.fn["collector"].statement : tolist(s.resources)]),
      "arn:aws:secretsmanager:us-east-1:123456789012:secret:sfw-test/spotify/*"
    )
    error_message = "The collector may only read this stack's Spotify tokens"
  }

  assert {
    condition = length(setintersection(
      toset(flatten([for s in data.aws_iam_policy_document.fn["dispatcher"].statement : tolist(s.actions)])),
      ["secretsmanager:GetSecretValue", "s3:PutObject", "dynamodb:PutItem"]
    )) == 0
    error_message = "The dispatcher must not touch tokens, S3 or play writes"
  }

  assert {
    condition     = aws_dynamodb_table.main.deletion_protection_enabled && !aws_s3_bucket.raw[0].force_destroy
    error_message = "Listening history must be protected by default"
  }

  assert {
    condition     = aws_sqs_queue.collect.fifo_queue && aws_sqs_queue.collect.visibility_timeout_seconds == 90
    error_message = "Collect queue must be FIFO with 6x the function timeout as visibility"
  }

  assert {
    condition = (
      aws_kms_key.data[0].enable_key_rotation
      && aws_sns_topic.alarms.kms_master_key_id == aws_kms_key.data[0].arn
      && contains(
        flatten([for s in data.aws_iam_policy_document.fn["collector"].statement : tolist(s.actions)]),
        "kms:GenerateDataKey"
      )
    )
    error_message = "Prod must encrypt with a rotating customer managed key the collector can use"
  }

  assert {
    condition     = aws_lambda_event_source_mapping.collect.batch_size == 1
    error_message = "One user per invocation, so a failure only retries that user"
  }
}

run "rejects_invalid_names" {
  command = plan

  variables {
    name = "Bad_Name"
  }

  expect_failures = [var.name]
}
