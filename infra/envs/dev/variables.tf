variable "region" {
  type    = string
  default = "us-east-1"
}

variable "spotify_client_id" {
  description = "Client ID of the Spotify app"
  type        = string
}

variable "alarm_email" {
  description = "Receives the collection alarms (empty = none)"
  type        = string
  default     = ""
}

variable "collect_schedule" {
  description = "Use rate(5 minutes) for the demo"
  type        = string
  default     = "rate(1 hour)"
}
