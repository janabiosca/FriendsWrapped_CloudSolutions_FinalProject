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

data "archive_file" "dashboard" {
  type        = "zip"
  output_path = "${path.module}/.build/dashboard.zip"
  dynamic "source" {
    for_each = fileset("${path.module}/../../src", "*.py")
    content {
      filename = source.value
      content  = file("${path.module}/../../src/${source.value}")
    }
  }
  source {
    filename = "index.html"
    content  = file("${path.module}/../../web/index.html")
  }
}

resource "aws_cloudwatch_log_group" "dashboard" {
  for_each          = toset(["dashboard", "signup"])
  name              = "/aws/lambda/sfw-dev-${each.key}"
  retention_in_days = 7
}

resource "aws_lambda_function" "signup" {
  function_name    = "sfw-dev-signup"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.13"
  handler          = "dashboard.signup"
  filename         = data.archive_file.dashboard.output_path
  source_code_hash = data.archive_file.dashboard.output_base64sha256
  timeout          = 5
  memory_size      = 256
  environment {
    variables = {
      OAUTH_TABLE_NAME = "sfw-dev-connect"
    }
  }
  depends_on = [aws_cloudwatch_log_group.dashboard]
}

resource "aws_cognito_user_pool" "group" {
  name                     = "sfw-dev-friends"
  user_pool_tier           = "LITE"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  username_configuration {
    case_sensitive = false
  }
  schema {
    name                     = "email"
    attribute_data_type      = "String"
    required                 = true
    mutable                  = false
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 2048
    }
  }
  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = true
  }
  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
  lambda_config {
    pre_sign_up = aws_lambda_function.signup.arn
  }
}

resource "aws_lambda_permission" "signup" {
  statement_id  = "AllowCognitoSignup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.signup.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.group.arn
}

resource "aws_apigatewayv2_api" "dashboard" {
  name          = "sfw-dev-dashboard"
  protocol_type = "HTTP"
}

resource "aws_cognito_user_pool_client" "web" {
  name                                 = "friends-wrapped-web"
  user_pool_id                         = aws_cognito_user_pool.group.id
  generate_secret                      = false
  supported_identity_providers         = ["COGNITO"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email"]
  callback_urls                        = ["${aws_apigatewayv2_api.dashboard.api_endpoint}/"]
  logout_urls                          = ["${aws_apigatewayv2_api.dashboard.api_endpoint}/"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 1
  id_token_validity                    = 1
  refresh_token_validity               = 1
  read_attributes                      = ["email", "email_verified"]
  write_attributes                     = ["email"]
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
}

resource "aws_cognito_user_pool_domain" "web" {
  domain                = "sfw-${aws_apigatewayv2_api.dashboard.id}"
  user_pool_id          = aws_cognito_user_pool.group.id
  managed_login_version = 1
}

resource "aws_lambda_function" "dashboard" {
  function_name    = "sfw-dev-dashboard"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.13"
  handler          = "dashboard.handler"
  filename         = data.archive_file.dashboard.output_path
  source_code_hash = data.archive_file.dashboard.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      RAW_BUCKET        = "sfw-dev-raw-6e5880d28f5d8e514bf6ee4650"
      TABLE_NAME        = "sfw-dev"
      OAUTH_TABLE_NAME  = "sfw-dev-connect"
      GROUP_ID          = "friends"
      COGNITO_DOMAIN    = "https://${aws_cognito_user_pool_domain.web.domain}.auth.us-east-1.amazoncognito.com"
      COGNITO_CLIENT_ID = aws_cognito_user_pool_client.web.id
      DASHBOARD_URL     = "${aws_apigatewayv2_api.dashboard.api_endpoint}/"
    }
  }
  depends_on = [aws_cloudwatch_log_group.dashboard]
}

resource "aws_apigatewayv2_integration" "dashboard" {
  api_id                 = aws_apigatewayv2_api.dashboard.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.dashboard.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_authorizer" "members" {
  api_id           = aws_apigatewayv2_api.dashboard.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "group-members"
  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.us-east-1.amazonaws.com/${aws_cognito_user_pool.group.id}"
  }
}

resource "aws_apigatewayv2_route" "page" {
  api_id    = aws_apigatewayv2_api.dashboard.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.dashboard.id}"
}

resource "aws_apigatewayv2_route" "statistics" {
  for_each             = toset(["/api/stats", "/api/group-weekly", "/api/wrapped"])
  api_id               = aws_apigatewayv2_api.dashboard.id
  route_key            = "GET ${each.value}"
  target               = "integrations/${aws_apigatewayv2_integration.dashboard.id}"
  authorization_type   = "JWT"
  authorizer_id        = aws_apigatewayv2_authorizer.members.id
  authorization_scopes = ["openid"]
}

resource "aws_apigatewayv2_stage" "dashboard" {
  api_id      = aws_apigatewayv2_api.dashboard.id
  name        = "$default"
  auto_deploy = true
  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }
}

resource "aws_lambda_permission" "dashboard" {
  statement_id  = "AllowDashboardApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dashboard.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.dashboard.execution_arn}/*/GET/*"
}

output "dashboard_url" {
  value = "${aws_apigatewayv2_api.dashboard.api_endpoint}/"
}

output "user_pool_id" {
  value = aws_cognito_user_pool.group.id
}
