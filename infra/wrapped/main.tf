terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
  backend "s3" {}
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      Project   = "spotify-friends-wrapped"
      ManagedBy = "terraform"
    }
  }
}

data "aws_iam_role" "lab" {
  name = "LabRole"
}

data "archive_file" "wrapped" {
  type        = "zip"
  source_dir  = "${path.module}/.build/package"
  output_path = "${path.module}/.build/wrapped.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_cloudwatch_log_group" "wrapped" {
  name              = "/aws/lambda/sfw-dev-wrapped"
  retention_in_days = 7
}

resource "aws_lambda_function" "wrapped" {
  function_name    = "sfw-dev-wrapped"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.13"
  handler          = "wrapped.handler"
  filename         = data.archive_file.wrapped.output_path
  source_code_hash = data.archive_file.wrapped.output_base64sha256
  timeout          = 120
  memory_size      = 256
  environment {
    variables = {
      TABLE_NAME = "sfw-dev"
      RAW_BUCKET = "sfw-dev-raw-6e5880d28f5d8e514bf6ee4650"
      GROUP_ID   = "friends"
    }
  }
  depends_on = [aws_cloudwatch_log_group.wrapped]
}

resource "aws_sfn_state_machine" "wrapped" {
  name     = "sfw-dev-weekly-wrapped"
  role_arn = data.aws_iam_role.lab.arn
  type     = "STANDARD"
  definition = jsonencode({
    StartAt        = "PrepareWeeklySnapshot"
    TimeoutSeconds = 600
    States = {
      PrepareWeeklySnapshot = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.wrapped.arn
          Payload = {
            action             = "prepare"
            "request.$"        = "$"
            "reference_time.$" = "$$.Execution.StartTime"
          }
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        Next = "ArchiveWeeklyWrapped"
      }
      ArchiveWeeklyWrapped = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.wrapped.arn
          Payload = {
            action       = "archive"
            "snapshot.$" = "$"
          }
        }
        OutputPath = "$.Payload"
        Retry = [{
          ErrorEquals     = ["States.TaskFailed"]
          IntervalSeconds = 2
          MaxAttempts     = 3
          BackoffRate     = 2
        }]
        End = true
      }
    }
  })
}

resource "aws_scheduler_schedule" "wrapped" {
  name                         = "sfw-dev-weekly-wrapped"
  schedule_expression          = "cron(0 9 ? * MON *)"
  schedule_expression_timezone = "Europe/Madrid"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_sfn_state_machine.wrapped.arn
    role_arn = data.aws_iam_role.lab.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 3
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "wrapped_failed" {
  alarm_name          = "sfw-dev-weekly-wrapped-failed"
  alarm_description   = "The weekly Wrapped generation failed. Review its Step Functions execution."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.wrapped.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = ["arn:aws:sns:us-east-1:290679806567:sfw-dev-alarms"]
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.wrapped.arn
}
