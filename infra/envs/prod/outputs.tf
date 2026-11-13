# Read by scripts/connect_spotify.py through `terraform output -json`.
output "table_name" {
  value = module.ingestion.table_name
}

output "raw_bucket" {
  value = module.ingestion.raw_bucket
}

output "secret_prefix" {
  value = module.ingestion.secret_prefix
}

output "group_id" {
  value = module.ingestion.group_id
}

output "dispatcher_function" {
  value = module.ingestion.dispatcher_function
}

output "collect_dlq_url" {
  value = module.ingestion.collect_dlq_url
}
