output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "raw_bucket" {
  value = local.raw_bucket_name
}

output "secret_prefix" {
  description = "Spotify refresh tokens are stored as <prefix><user_id> by scripts/connect_spotify.py"
  value       = local.secret_prefix
}

output "group_id" {
  value = var.group_id
}

output "dispatcher_function" {
  description = "Invoke it by hand to trigger a collection during the demo"
  value       = aws_lambda_function.fn["dispatcher"].function_name
}

output "collector_function" {
  value = aws_lambda_function.fn["collector"].function_name
}

output "collect_queue_url" {
  value = aws_sqs_queue.collect.url
}

output "collect_dlq_url" {
  value = aws_sqs_queue.collect_dlq.url
}

output "alarm_topic_arn" {
  value = aws_sns_topic.alarms.arn
}
