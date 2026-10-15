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

output "client_security_group_ids" {
  description = "Database client security-group IDs by component, including configured PostgreSQL and HTTPS rules."
  value       = { for name, group in aws_security_group.database_client : name => group.id }
  depends_on = [
    aws_vpc_security_group_ingress_rule.postgres,
    aws_vpc_security_group_egress_rule.postgres,
    aws_vpc_security_group_egress_rule.https,
  ]
}

output "runtime_roles" {
  description = "IAM role IDs, names and ARNs by component, including configured database-secret and queue permissions."
  value = {
    for name, role in aws_iam_role.runtime : name => {
      id   = role.id
      name = role.name
      arn  = role.arn
    }
  }
  depends_on = [
    aws_iam_role_policy.database_secret,
    aws_iam_role_policy.bootstrap_secrets,
    aws_iam_role_policy.queue,
  ]
}

output "instance_profiles" {
  description = "EC2 instance-profile names by component, available after database-secret and queue policies are configured."
  value       = { for name, profile in aws_iam_instance_profile.runtime : name => profile.name }
  depends_on = [
    aws_iam_role_policy.database_secret,
    aws_iam_role_policy.bootstrap_secrets,
    aws_iam_role_policy.queue,
  ]
}
