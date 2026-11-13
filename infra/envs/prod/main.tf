# Our own AWS account: always on, so no play is lost. One least-privilege role per function.
module "ingestion" {
  source = "../../modules/ingestion"

  name                 = "sfw-prod"
  spotify_client_id    = var.spotify_client_id
  alarm_email          = var.alarm_email
  collect_schedule     = var.collect_schedule
  lab_role_name        = "" # create one role per function
  protect_data         = true
  customer_managed_key = true
  log_retention_days   = 30

  source_dir = "${path.root}/../../../src"
  build_dir  = "${path.root}/.build"
}
