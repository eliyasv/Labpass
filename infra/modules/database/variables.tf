variable "name_prefix" {
  description = "Resource name prefix."
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

variable "vpc_id" {
  description = "VPC containing the database and workload client security groups."
  type        = string
}

variable "database_subnet_ids" {
  description = "Isolated subnets used by the RDS subnet group."
  type        = list(string)
}

variable "queue_arn" {
  description = "Confirmation queue ARN for the relay publish and consumer receive policies."
  type        = string
}
