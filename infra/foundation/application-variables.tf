variable "application" {
  description = "EC2/ALB hosting configuration. Null leaves hosting disabled."
  type = object({
    ami_id                 = string
    image_digest           = string
    public_origin          = string
    origin_certificate_arn = string
    api_desired_capacity   = optional(number, 0)
    relay_desired_capacity = optional(number, 0)
  })
  default = null

  validation {
    condition = var.application == null ? true : alltrue([
      can(regex("^ami-[0-9a-f]{17}$", var.application.ami_id)),
      can(regex("^sha256:[0-9a-f]{64}$", var.application.image_digest)),
      can(regex("^https://([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.application.public_origin)),
      can(regex("^arn:aws:acm:${var.aws_region}:${var.aws_account_id}:certificate/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.application.origin_certificate_arn)),
      contains([0, 2, 3, 4], var.application.api_desired_capacity),
      contains([0, 1, 2], var.application.relay_desired_capacity),
    ])
    error_message = "Hosting requires an AMI ID, immutable SHA-256 image digest, HTTPS origin and same-account regional ACM ARN. API capacity is 0 or 2–4; relay capacity is 0–2."
  }
}
