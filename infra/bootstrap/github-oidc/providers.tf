# One-off root, applied by hand once in our own AWS account (not in AWS Academy, where IAM
# roles cannot be created). It lets GitHub Actions log in to AWS with short-lived OIDC tokens,
# so no AWS access keys are ever stored in GitHub.
terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {} # same state bucket, key = "bootstrap/github-oidc.tfstate"
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "spotify-friends-wrapped"
      ManagedBy = "terraform"
    }
  }
}
