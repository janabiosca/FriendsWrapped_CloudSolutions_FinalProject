# Set these as GitHub repository variables (see README).
output "AWS_PLAN_ROLE_ARN" {
  value = aws_iam_role.github["plan"].arn
}

output "AWS_APPLY_ROLE_ARN" {
  value = aws_iam_role.github["apply"].arn
}
