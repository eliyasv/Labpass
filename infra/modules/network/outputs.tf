output "network" {
  description = "Network IDs for later workloads; database subnets are isolated."
  value = {
    vpc_id                 = aws_vpc.main.id
    availability_zones     = local.availability_zones
    public_subnet_ids      = [for subnet in aws_subnet.public : subnet.id]
    application_subnet_ids = [for subnet in aws_subnet.application : subnet.id]
    database_subnet_ids    = [for subnet in aws_subnet.database : subnet.id]
  }

  # Consumers need usable routes and associations, not just allocated subnet IDs.
  depends_on = [
    aws_route.public_internet,
    aws_route.application_egress,
    aws_route_table_association.public,
    aws_route_table_association.application,
    aws_route_table_association.database,
    aws_vpc_endpoint.s3,
  ]
}
