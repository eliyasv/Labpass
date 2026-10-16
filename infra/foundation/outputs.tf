# Expose module integration metadata for operators and release tooling, not passwords.
output "network" {
  description = "Network IDs for later workloads; database subnets are isolated."
  value       = module.network.network
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
  value       = module.database.database
}

output "runtime_access" {
  description = "Workload security groups, role ARNs and EC2 profiles."
  value = {
    security_group_ids = module.database.client_security_group_ids
    role_arns          = { for name, role in module.database.runtime_roles : name => role.arn }
    instance_profiles  = module.database.instance_profiles
  }
}

output "application_hosting" {
  description = "ALB, groups and launch templates; operator templates do not launch hosts automatically."
  value       = module.application.application_hosting
}

output "frontend_delivery" {
  description = "Frontend URL, publication bucket, distribution and origin DNS; null when disabled."
  value       = module.frontend.frontend_delivery
}

output "confirmation_worker" {
  description = "Lambda alias/version, SQS mapping and SES identity metadata; null when disabled."
  value       = module.confirmations.confirmation_worker
}
