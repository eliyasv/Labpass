variable "aws_account_id" {
  description = "Actual AWS account approved for this demo; prevents applying to another account."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the actual 12-digit AWS account ID; there is no default account."
  }
}

variable "aws_region" {
  description = "Region selected for the temporary demo."
  type        = string
  default     = "us-east-1"
  nullable    = false

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This demo's architecture and cost review target us-east-1."
  }
}

variable "name_prefix" {
  description = "Unique prefix for a dedicated LabPass demo stack."
  type        = string
  default     = "labpass-demo"
  nullable    = false

  validation {
    condition     = can(regex("^labpass-[a-z0-9][a-z0-9-]{0,29}$", var.name_prefix))
    error_message = "Use labpass- followed by 1–30 lowercase letters, digits or hyphens."
  }
}

variable "database_engine_version" {
  description = "PostgreSQL 18 minor version; orderability is checked in the target region."
  type        = string
  default     = "18.6"
  nullable    = false

  validation {
    condition     = can(regex("^18\\.[0-9]+$", var.database_engine_version))
    error_message = "Select an exact PostgreSQL 18 minor version."
  }
}

variable "database_deletion_protection" {
  description = "RDS deletion protection."
  type        = bool
  default     = true
  nullable    = false
}
