output "confirmation_worker" {
  description = "Lambda alias/version, SQS mapping and SES identity metadata; null when disabled."
  value = local.confirmation_enabled ? {
    function_name     = aws_lambda_function.confirmations[0].function_name
    function_version  = aws_lambda_function.confirmations[0].version
    alias_arn         = aws_lambda_alias.confirmations[0].arn
    mapping_uuid      = aws_lambda_event_source_mapping.confirmations[0].uuid
    mapping_enabled   = aws_lambda_event_source_mapping.confirmations[0].enabled
    max_concurrency   = var.confirmation_worker.max_concurrency
    log_group         = aws_cloudwatch_log_group.confirmations[0].name
    ses_identity_arn  = aws_sesv2_email_identity.confirmations[0].arn
    ses_verified      = aws_sesv2_email_identity.confirmations[0].verified_for_sending_status
    configuration_set = aws_sesv2_configuration_set.confirmations[0].configuration_set_name
    dkim_record_names = [for record in aws_route53_record.email_dkim : record.name]
  } : null
}
