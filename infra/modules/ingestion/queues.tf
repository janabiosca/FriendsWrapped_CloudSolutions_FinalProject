# FIFO with one message group per user: users are collected in parallel, but the same user is
# never processed twice at once (Spotify refresh tokens can rotate on use, and two concurrent
# refreshes would invalidate each other).
resource "aws_sqs_queue" "collect" {
  name                       = "${var.name}-collect.fifo"
  fifo_queue                 = true
  visibility_timeout_seconds = 6 * local.function_timeout # AWS recommendation for Lambda triggers
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.collect_dlq.arn
    maxReceiveCount     = 3
  })
}

# After 3 failed attempts the task lands here and the alarm fires. 14 days to fix it and redrive.
resource "aws_sqs_queue" "collect_dlq" {
  name                      = "${var.name}-collect-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 14 * 24 * 3600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue_redrive_allow_policy" "collect_dlq" {
  queue_url = aws_sqs_queue.collect_dlq.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.collect.arn]
  })
}
