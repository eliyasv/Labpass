variable "aws_account_id" {
  description = "Target AWS account ID."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the actual 12-digit AWS account ID; there is no default account."
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

variable "frontend" {
  description = "CloudFront/S3 delivery and DNS in an existing authoritative public Route 53 zone. Null leaves delivery disabled."
  type = object({
    hosted_zone_id     = string
    domain_name        = string
    origin_domain_name = string
  })
  default = null

  validation {
    condition = var.frontend == null ? true : alltrue([
      can(regex("^Z[A-Z0-9]{1,31}$", var.frontend.hosted_zone_id)),
      length(var.frontend.domain_name) <= 253,
      length(var.frontend.origin_domain_name) <= 253,
      can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.frontend.domain_name)),
      can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.frontend.origin_domain_name)),
      var.frontend.domain_name != var.frontend.origin_domain_name,
    ])
    error_message = "Frontend delivery requires a Route 53 zone ID and distinct lowercase DNS names without wildcards or trailing dots."
  }
}

variable "origin_verify_token" {
  description = "Origin-verification token forwarded by CloudFront to the ALB; stored in Terraform state."
  type        = string
  sensitive   = true
  default     = null

  validation {
    condition     = var.frontend == null ? true : can(regex("^[0-9a-f]{64}$", var.origin_verify_token))
    error_message = "Enabled delivery requires a 64-character lowercase hex origin token."
  }
}

variable "alb_origin" {
  description = "ALB DNS name and canonical hosted zone ID for origin DNS; required when frontend delivery is enabled."
  type = object({
    dns_name = string
    zone_id  = string
  })
  default = null
}
