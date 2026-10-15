output "network" {
  description = "Network IDs for later workloads; database subnets are isolated."
  value = {
    vpc_id                 = aws_vpc.main.id
    availability_zones     = local.availability_zones
    public_subnet_ids      = [for subnet in aws_subnet.public : subnet.id]
    application_subnet_ids = [for subnet in aws_subnet.application : subnet.id]
    database_subnet_ids    = [for subnet in aws_subnet.database : subnet.id]
  }
}

output "image_repositories" {
  description = "Repository URLs; later releases publish and deploy image digests."
  value       = { for name, repository in aws_ecr_repository.application : name => repository.repository_url }
}

output "confirmation_queue" {
  description = "Queue identity for the relay and Lambda event-source mapping."
  value = {
    arn     = aws_sqs_queue.confirmations.arn
    url     = aws_sqs_queue.confirmations.id
    dlq_arn = aws_sqs_queue.dead_letter.arn
  }
}

output "database" {
  description = "Database endpoint and credential ARNs; secret values are populated outside Terraform."
  value = {
    host              = aws_db_instance.main.address
    port              = aws_db_instance.main.port
    name              = aws_db_instance.main.db_name
    master_secret_arn = aws_db_instance.main.master_user_secret[0].secret_arn
    secret_arns       = { for name, secret in aws_secretsmanager_secret.database : name => secret.arn }
    security_group_id = aws_security_group.database.id
  }
}

output "runtime_access" {
  description = "Workload security groups, role ARNs and EC2 profiles for compute integration."
  value = {
    security_group_ids = { for name, group in aws_security_group.database_client : name => group.id }
    role_arns          = { for name, role in aws_iam_role.runtime : name => role.arn }
    instance_profiles  = { for name, profile in aws_iam_instance_profile.runtime : name => profile.name }
  }
}

output "application_hosting" {
  description = "ALB, groups and launch templates; operator templates do not launch hosts automatically."
  value = local.hosting_enabled ? {
    alb_dns_name     = aws_lb.api[0].dns_name
    alb_zone_id      = aws_lb.api[0].zone_id
    api_target_group = aws_lb_target_group.api[0].arn
    api_asg_name     = aws_autoscaling_group.api[0].name
    relay_asg_name   = aws_autoscaling_group.relay[0].name
    launch_templates = { for name, template in aws_launch_template.runtime : name => {
      id      = template.id
      version = template.latest_version
    } }
    log_groups = { for name, group in aws_cloudwatch_log_group.runtime : name => group.name }
  } : null
}

output "frontend_delivery" {
  description = "Frontend URL, publication bucket, distribution and origin DNS; null when disabled."
  value = local.frontend_enabled ? {
    url                    = "https://${var.frontend.domain_name}"
    bucket_name            = aws_s3_bucket.frontend[0].id
    distribution_id        = aws_cloudfront_distribution.site[0].id
    distribution_domain    = aws_cloudfront_distribution.site[0].domain_name
    origin_domain          = aws_route53_record.origin[0].fqdn
    viewer_certificate_arn = aws_acm_certificate_validation.site["viewer"].certificate_arn
    origin_certificate_arn = aws_acm_certificate_validation.site["origin"].certificate_arn
  } : null
}

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
