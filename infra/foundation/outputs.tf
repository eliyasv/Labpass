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
