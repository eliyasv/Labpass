variable "aws_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Supply the actual target AWS account ID."
  }
}

variable "github_repository" {
  type = string
  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "Supply the exact GitHub owner/repository name."
  }
}

variable "github_owner_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_owner_id))
    error_message = "Supply the immutable numeric GitHub owner ID."
  }
}

variable "github_repository_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "Supply the immutable numeric GitHub repository ID."
  }
}

variable "oidc_subject_format" {
  type    = string
  default = "immutable"
  validation {
    condition     = contains(["immutable", "legacy"], var.oidc_subject_format)
    error_message = "Use the repository's actual OIDC subject format: immutable or legacy."
  }
}

variable "existing_oidc_provider_arn" {
  type    = string
  default = null
  validation {
    condition     = var.existing_oidc_provider_arn == null ? true : var.existing_oidc_provider_arn == "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com"
    error_message = "Reuse only this account's GitHub Actions OIDC provider."
  }
}

variable "workload_name_prefix" {
  type    = string
  default = "labpass-demo"
  validation {
    condition     = can(regex("^labpass-[a-z0-9][a-z0-9-]{0,29}$", var.workload_name_prefix))
    error_message = "Match the foundation name_prefix."
  }
}

variable "runtime_launch_template_ids" {
  type    = map(string)
  default = {}
  validation {
    condition = length(var.runtime_launch_template_ids) == 0 ? true : (
      toset(keys(var.runtime_launch_template_ids)) == toset(["api", "relay", "bootstrap", "migration"]) &&
      alltrue([for id in var.runtime_launch_template_ids : can(regex("^lt-[0-9a-f]{17}$", id))])
    )
    error_message = "Supply all four actual foundation launch-template IDs, or leave them empty until foundation deployment."
  }
}

variable "migration_instance_id" {
  type    = string
  default = null
  validation {
    condition     = var.migration_instance_id == null ? true : can(regex("^i-[0-9a-f]{17}$", var.migration_instance_id))
    error_message = "Supply the dedicated running migration operator instance ID."
  }
}
