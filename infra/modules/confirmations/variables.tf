variable "aws_account_id" {
  description = "Target AWS account ID."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the actual 12-digit AWS account ID; there is no default account."
  }
}

variable "aws_region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
  nullable    = false

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "This configuration requires us-east-1."
  }
}

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

variable "confirmation_worker" {
  description = "Lambda/SQS/SES confirmation delivery. Null leaves the worker disabled; an existing authoritative public Route 53 zone is required."
  type = object({
    image_digest              = string
    email_domain              = string
    sender_email              = string
    hosted_zone_id            = string
    max_concurrency           = optional(number, 2)
    reserve_concurrency       = optional(bool, true)
    verified_recipient_emails = optional(set(string), [])
    mapping_enabled           = optional(bool, false)
  })
  default = null

  validation {
    condition = var.confirmation_worker == null ? true : alltrue([
      for email in var.confirmation_worker.verified_recipient_emails :
      length(email) <= 254 && length(split("@", email)[0]) <= 64 &&
      can(regex("^[a-z0-9]+([._+-][a-z0-9]+)*@([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", email))
    ])
    error_message = "Verified recipients must be normalized lowercase email addresses without wildcards, with at most 64 local-part and 254 total characters."
  }

  validation {
    condition = var.confirmation_worker == null ? true : alltrue([
      can(regex("^sha256:[0-9a-f]{64}$", var.confirmation_worker.image_digest)),
      can(regex("^Z[A-Z0-9]{1,31}$", var.confirmation_worker.hosted_zone_id)),
      length(var.confirmation_worker.email_domain) <= 253,
      can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.confirmation_worker.email_domain)),
      length(var.confirmation_worker.sender_email) <= 254,
      can(regex("^[a-z0-9]+([._+-][a-z0-9]+)*@([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.confirmation_worker.sender_email)),
      length(split("@", var.confirmation_worker.sender_email)[0]) <= 64,
      endswith(var.confirmation_worker.sender_email, "@${var.confirmation_worker.email_domain}"),
      contains(range(2, 11), var.confirmation_worker.max_concurrency),
    ])
    error_message = "Confirmation delivery requires a SHA-256 image digest, public zone ID, lowercase DNS domain and normalized sender in that domain. Sender local parts use alphanumeric groups separated by . _ + or -. Concurrency must be an integer from 2 to 10."
  }
}

variable "database" {
  description = "Database connection metadata and the consumer's credential secret ARN."
  type = object({
    host       = string
    name       = string
    port       = number
    secret_arn = string
  })
}

variable "application_subnet_ids" {
  description = "Private subnets for Lambda database access and outbound AWS API traffic."
  type        = list(string)
}

variable "consumer_security_group_id" {
  description = "Consumer security group with PostgreSQL access to the database."
  type        = string
}

variable "consumer_role" {
  description = "Consumer IAM role ID for policy attachment and ARN for Lambda execution."
  type = object({
    id  = string
    arn = string
  })
}

variable "lambda_repository" {
  description = "ECR repository name and ARN for its retrieval policy, and URL for the worker image reference."
  type = object({
    name           = string
    arn            = string
    repository_url = string
  })
}

variable "queue_arn" {
  description = "Confirmation queue ARN consumed by the Lambda event-source mapping."
  type        = string
}

variable "queue_visibility_timeout_seconds" {
  description = "Source queue visibility timeout, checked against the worker execution timeout."
  type        = number
}
