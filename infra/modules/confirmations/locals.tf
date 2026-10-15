locals {
  confirmation_enabled      = var.confirmation_worker != null
  confirmation_name         = "${var.name_prefix}-confirmations"
  confirmation_function_arn = "arn:aws:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.confirmation_name}"
}
