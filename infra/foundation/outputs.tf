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
