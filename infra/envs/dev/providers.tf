terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Remote state in S3 with native locking. The bucket is created once by
  # scripts/bootstrap_state.sh and passed with: terraform init -backend-config=backend.conf
  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "spotify-friends-wrapped"
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}
