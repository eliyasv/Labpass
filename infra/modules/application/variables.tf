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

variable "application" {
  description = "EC2/ALB hosting configuration. Null leaves hosting disabled."
  type = object({
    ami_id                 = string
    image_digest           = string
    public_origin          = string
    api_desired_capacity   = optional(number, 0)
    relay_desired_capacity = optional(number, 0)
  })
  default = null

  validation {
    condition = var.application == null ? true : alltrue([
      can(regex("^ami-[0-9a-f]{17}$", var.application.ami_id)),
      can(regex("^sha256:[0-9a-f]{64}$", var.application.image_digest)),
      can(regex("^https://([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.application.public_origin)),
      contains([0, 2, 3, 4], var.application.api_desired_capacity),
      contains([0, 1, 2], var.application.relay_desired_capacity),
    ])
    error_message = "Hosting requires an AMI ID, immutable SHA-256 image digest and HTTPS origin. API capacity is 0 or 2–4; relay capacity is 0–2."
  }
}

variable "origin_verify_token" {
  description = "Random 32-byte hex token shared by CloudFront and the ALB. Stored in Terraform state; restrict state and configuration access."
  type        = string
  default     = null
  sensitive   = true

  validation {
    condition     = var.application == null ? true : can(regex("^[0-9a-f]{64}$", var.origin_verify_token))
    error_message = "Enabled application hosting requires a cryptographically random 64-character lowercase hex origin token."
  }
}

variable "origin_verify_previous_token" {
  description = "Previous origin token accepted during a two-step rotation; remove after CloudFront deployment completes."
  type        = string
  default     = null
  sensitive   = true

  validation {
    condition     = var.origin_verify_previous_token == null ? true : can(regex("^[0-9a-f]{64}$", var.origin_verify_previous_token))
    error_message = "The previous origin token must be a 64-character lowercase hex value."
  }
}

variable "database" {
  description = "Database connection metadata, runtime secret ARNs and the master secret ARN used by the bootstrap host."
  type = object({
    host              = string
    name              = string
    port              = number
    master_secret_arn = string
    secret_arns       = map(string)
  })
}

variable "vpc_id" {
  description = "VPC containing the ALB and application hosts."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the internet-facing ALB."
  type        = list(string)
}

variable "application_subnet_ids" {
  description = "Private subnets for the API and relay fleets."
  type        = list(string)
}

variable "queue_arn" {
  description = "Confirmation queue ARN used by the outbox relay."
  type        = string
}

variable "api_repository" {
  description = "ECR repository ARN for image-pull policies and URL for immutable runtime image references."
  type = object({
    arn            = string
    repository_url = string
  })
}

variable "client_security_group_ids" {
  description = "Database client security-group IDs keyed by api, relay, bootstrap and migration."
  type        = map(string)
}

variable "instance_profiles" {
  description = "EC2 instance-profile names keyed by api, relay, bootstrap and migration."
  type        = map(string)
}

variable "runtime_roles" {
  description = "IAM role IDs and names for attaching host policies, keyed by api, relay, bootstrap and migration."
  type = map(object({
    id   = string
    name = string
  }))
}

variable "listener_certificate_arn" {
  description = "ACM certificate selected by the root for the ALB HTTPS listener; required when hosting is enabled."
  type        = string
  default     = null
}

variable "aws_account_id" {
  description = "Target AWS account ID."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the actual 12-digit AWS account ID; there is no default account."
  }
}
