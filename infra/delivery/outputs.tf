output "delivery" {
  value = {
    role_arns          = { for name, role in aws_iam_role.delivery : name => role.arn }
    oidc_subjects      = { for name, environment in local.environments : name => "${local.subject_prefix}:environment:${environment}" }
    state_bucket       = aws_s3_bucket.state.id
    state_key          = local.state_key
    migration_document = aws_ssm_document.migrate.name
  }
}

output "public_dns" {
  description = "Hosted zone ID for foundation inputs and authoritative nameservers for registrar delegation."
  value = var.public_domain_name == null ? null : {
    domain_name    = var.public_domain_name
    hosted_zone_id = aws_route53_zone.public[0].zone_id
    name_servers   = sort(aws_route53_zone.public[0].name_servers)
  }
}
