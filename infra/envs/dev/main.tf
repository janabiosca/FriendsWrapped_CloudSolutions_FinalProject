# AWS Academy sandbox: for experimenting. Roles cannot be created, credentials expire with the
# lab session and the sandbox is not guaranteed to stay up, so the real history lives in prod.
module "ingestion" {
  source = "../../modules/ingestion"

  existing_raw_bucket  = "sfw-dev-raw-6e5880d28f5d8e514bf6ee4650"
  name                 = "sfw-dev"
  spotify_client_id    = var.spotify_client_id
  alarm_email          = var.alarm_email
  collect_schedule     = var.collect_schedule
  lab_role_name        = "LabRole"
  protect_data         = false # throwaway: terraform destroy must be able to delete everything
  customer_managed_key = false # AWS managed encryption: LabRole may not be allowed to use our own keys
  log_retention_days   = 7

  source_dir = "${path.root}/../../../src"
  build_dir  = "${path.root}/.build"
}
