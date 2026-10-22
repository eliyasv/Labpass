terraform {
  required_version = "~> 1.15.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.69.1"
    }
  }
}

# Bootstrap uses operator credentials and owns resources in a separate local state.
provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = [var.aws_account_id]
  default_tags {
    tags = { Project = "LabPass", ManagedBy = "Terraform", Component = "delivery" }
  }
}
