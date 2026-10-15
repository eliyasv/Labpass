output "delivery" {
  value = {
    role_arns          = { for name, role in aws_iam_role.delivery : name => role.arn }
    oidc_subjects      = { for name, environment in local.environments : name => "${local.subject_prefix}:environment:${environment}" }
    state_bucket       = aws_s3_bucket.state.id
    state_key          = local.state_key
    migration_document = aws_ssm_document.migrate.name
  }
}
