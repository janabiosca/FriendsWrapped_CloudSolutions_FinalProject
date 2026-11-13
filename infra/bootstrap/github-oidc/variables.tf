variable "region" {
  type    = string
  default = "us-east-1"
}

variable "github_repository" {
  description = "owner/name of the GitHub repository allowed to deploy, e.g. jana-biosca/spotify-friends-wrapped"
  type        = string
}

variable "state_bucket" {
  description = "Terraform state bucket created by scripts/bootstrap_state.sh"
  type        = string
}

variable "resource_prefix" {
  description = "Name prefix of the environment the apply role may manage (IAM roles are restricted to it)"
  type        = string
  default     = "sfw-prod"
}
