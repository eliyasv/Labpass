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
