terraform {
  required_version = "~> 1.15.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.68.0"
    }
  }
}

# Reject credentials for another account; child modules inherit this provider.
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.aws_account_id]

  default_tags {
    tags = {
      Project     = "LabPass"
      Environment = "demo"
      ManagedBy   = "Terraform"
    }
  }
}
