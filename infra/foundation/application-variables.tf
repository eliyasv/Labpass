# Null omits hosting; zero desired capacities create the fleet definitions before
# database bootstrap. A running API requires at least two instances across AZs.
variable "application" {
  description = "EC2/ALB hosting configuration. Null leaves hosting disabled."
  type = object({
    ami_id                 = string
    image_digest           = string
    public_origin          = string
    origin_certificate_arn = optional(string)
    api_desired_capacity   = optional(number, 0)
    relay_desired_capacity = optional(number, 0)
  })
  default = null

  validation {
    condition = var.application == null ? true : alltrue([
      can(regex("^ami-[0-9a-f]{17}$", var.application.ami_id)),
      can(regex("^sha256:[0-9a-f]{64}$", var.application.image_digest)),
      can(regex("^https://([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.application.public_origin)),
      var.application.origin_certificate_arn == null ? true : can(regex("^arn:aws:acm:${var.aws_region}:${var.aws_account_id}:certificate/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.application.origin_certificate_arn)),
      contains([0, 2, 3, 4], var.application.api_desired_capacity),
      contains([0, 1, 2], var.application.relay_desired_capacity),
    ])
    error_message = "Hosting requires an AMI ID, immutable SHA-256 image digest and HTTPS origin; any supplied ACM ARN must match the account/region. API capacity is 0 or 2–4; relay capacity is 0–2."
  }
}

# CloudFront supplies this header to the ALB; sensitive inputs still enter state.
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

# Temporarily accept both tokens while CloudFront rolls out the replacement.
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
