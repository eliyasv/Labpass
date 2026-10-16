# Public hostname resolves to CloudFront; the separate origin hostname resolves
# to the ALB and must match its certificate. The hosted zone already exists.
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

  validation {
    condition = var.frontend == null ? (var.application == null ? true : var.application.origin_certificate_arn != null) : (
      var.application == null ? false : (
        var.application.public_origin == "https://${var.frontend.domain_name}" && var.application.origin_certificate_arn == null
      )
    )
    error_message = "Standalone hosting needs an origin certificate ARN. Frontend integration requires hosting with a matching HTTPS public_origin and no supplied origin certificate; it provisions both certificates."
  }
}
