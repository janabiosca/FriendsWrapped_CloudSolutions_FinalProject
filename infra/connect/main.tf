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

variable "spotify_client_id" {
  type = string
}

data "aws_iam_role" "lab" {
  name = "LabRole"
}

resource "aws_dynamodb_table" "oauth" {
  name         = "sfw-dev-connect"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"
  attribute {
    name = "id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
  server_side_encryption {
    enabled = true
  }
}

resource "aws_apigatewayv2_api" "connect" {
  name          = "sfw-dev-connect"
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "connect" {
  name              = "/aws/lambda/sfw-dev-connect"
  retention_in_days = 7
}

data "archive_file" "connect" {
  type        = "zip"
  source_dir  = "${path.module}/../../src"
  output_path = "${path.module}/.build/connect.zip"
  excludes    = ["__pycache__", "**/__pycache__/**", "**/*.pyc"]
}

resource "aws_lambda_function" "connect" {
  function_name    = "sfw-dev-connect"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.13"
  handler          = "spotify_connect.handler"
  filename         = data.archive_file.connect.output_path
  source_code_hash = data.archive_file.connect.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      TABLE_NAME        = "sfw-dev"
      OAUTH_TABLE_NAME  = aws_dynamodb_table.oauth.name
      SECRET_PREFIX     = "sfw-dev/spotify/"
      GROUP_ID          = "friends"
      SPOTIFY_CLIENT_ID = var.spotify_client_id
      CONNECT_BASE_URL  = aws_apigatewayv2_api.connect.api_endpoint
    }
  }
  depends_on = [aws_cloudwatch_log_group.connect]
}

resource "aws_apigatewayv2_integration" "connect" {
  api_id                 = aws_apigatewayv2_api.connect.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.connect.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "connect" {
  for_each  = toset(["/connect", "/start", "/callback", "/health"])
  api_id    = aws_apigatewayv2_api.connect.id
  route_key = "GET ${each.value}"
  target    = "integrations/${aws_apigatewayv2_integration.connect.id}"
}

resource "aws_apigatewayv2_stage" "connect" {
  api_id      = aws_apigatewayv2_api.connect.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 5
    throttling_rate_limit  = 2
  }
}

resource "aws_lambda_permission" "connect" {
  statement_id  = "AllowConnectApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.connect.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.connect.execution_arn}/*/GET/*"
}

output "connect_base_url" {
  value = aws_apigatewayv2_api.connect.api_endpoint
}

output "spotify_redirect_uri" {
  value = "${aws_apigatewayv2_api.connect.api_endpoint}/callback"
}
