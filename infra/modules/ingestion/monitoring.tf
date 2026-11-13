resource "aws_sns_topic" "alarms" {
  name              = "${var.name}-alarms"
  kms_master_key_id = local.kms_key_arn # alarm texts mention user ids: encrypted at rest
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email" # AWS sends a confirmation email that must be accepted once
  endpoint  = var.alarm_email
}

locals {
  metric_namespace = "SpotifyFriendsWrapped/${var.name}"

  # Metrics extracted from the JSON lines the collector prints (src/collector.py).
  log_metrics = {
    Collections    = "{ $.event = \"collected\" }"
    ReauthRequired = "{ $.event = \"collect_failed\" && $.status = \"reauth_required\" }"
    PossibleGaps   = "{ $.event = \"collected\" && $.possible_gap IS TRUE }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "collector" {
  for_each       = local.log_metrics
  name           = "${var.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.fn["collector"].name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = local.metric_namespace
    value     = "1"
  }
}

# A user's collection failed 3 times and is waiting in the dead-letter queue.
resource "aws_cloudwatch_metric_alarm" "collection_failed" {
  alarm_name          = "${var.name}-collection-failed"
  alarm_description   = "A user's collection failed 3 times. Plays are lost if it is not fixed before that user plays 50 more songs."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.collect_dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# Without this, a broken dispatcher queues nothing and the dead-letter alarm never fires.
resource "aws_cloudwatch_metric_alarm" "dispatcher_errors" {
  alarm_name          = "${var.name}-dispatcher-errors"
  alarm_description   = "The scheduled dispatcher failed: nobody is being collected."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fn["dispatcher"].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "reauth_required" {
  alarm_name          = "${var.name}-reauth-required"
  alarm_description   = "Spotify rejected a refresh token: that friend must run scripts/connect_spotify.py again."
  namespace           = local.metric_namespace
  metric_name         = "ReauthRequired"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  depends_on          = [aws_cloudwatch_log_metric_filter.collector]
}

resource "aws_cloudwatch_metric_alarm" "possible_gap" {
  alarm_name          = "${var.name}-possible-gap"
  alarm_description   = "A collection found 50 new plays at once: some older plays may have been lost. Collect more often."
  namespace           = local.metric_namespace
  metric_name         = "PossibleGaps"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  depends_on          = [aws_cloudwatch_log_metric_filter.collector]
}

# Heartbeat: no successful collection in 3 hours means the schedule stopped silently.
resource "aws_cloudwatch_metric_alarm" "no_collections" {
  alarm_name          = "${var.name}-no-collections"
  alarm_description   = "No successful collection in the last 3 hours. Check the schedule, the dispatcher and the collector."
  namespace           = local.metric_namespace
  metric_name         = "Collections"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching" # no data at all is exactly the failure we look for
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
  depends_on          = [aws_cloudwatch_log_metric_filter.collector]
}
