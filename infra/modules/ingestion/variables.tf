variable "name" {
  description = "Prefix for every resource, e.g. sfw-dev. Must be unique per account and region."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9-]{3,24}$", var.name))
    error_message = "Use 3-24 lowercase letters, digits or dashes."
  }
}

variable "group_id" {
  description = "Id of the friends group whose members are collected."
  type        = string
  default     = "friends"
}

variable "spotify_client_id" {
  description = "Client ID of the Spotify app (developer.spotify.com/dashboard). Not a secret: PKCE apps have no client secret."
  type        = string
}

variable "collect_schedule" {
  description = "How often plays are collected. Spotify keeps only the last 50 plays, so never go above a few hours."
  type        = string
  default     = "rate(1 hour)"
}

variable "alarm_email" {
  description = "Address that receives collection alarms. Empty = no email subscription."
  type        = string
  default     = ""
}

variable "lab_role_name" {
  description = <<-EOT
    Existing IAM role that every function runs as. AWS Academy does not allow creating IAM roles,
    so there it must be "LabRole". Leave empty in a normal account: one least-privilege role is
    created per function.
  EOT
  type        = string
  default     = ""
}

variable "protect_data" {
  description = "Turns on DynamoDB deletion protection and keeps the raw bucket if it has objects. Use false only in throwaway sandboxes."
  type        = bool
  default     = true
}

variable "customer_managed_key" {
  description = "Encrypt the raw bucket and the alarm topic with our own KMS key (~1 USD/month). Off in AWS Academy."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Days the Lambda logs are kept in CloudWatch."
  type        = number
  default     = 30
}

variable "source_dir" {
  description = "Directory with the Lambda source code (src/)."
  type        = string
}

variable "build_dir" {
  description = "Directory where the Lambda zip is written (git-ignored)."
  type        = string
}

variable "existing_raw_bucket" {
  description = "Existing raw bucket bootstrapped outside Terraform in restricted Academy accounts. Empty creates a managed bucket."
  type        = string
  default     = ""
}
