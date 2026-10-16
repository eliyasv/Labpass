# Use two standard AZs available to the account for public, application and DB tiers.
data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "zone-type"
    values = ["availability-zone"]
  }
}

locals {
  # Discover AZ names in the actual account; do not assume a particular letter is available.
  availability_zones = slice(sort(data.aws_availability_zones.available.names), 0, min(2, length(data.aws_availability_zones.available.names)))
  zones              = { for index, name in local.availability_zones : tostring(index) => name }
  vpc_cidr           = "10.42.0.0/16"
}

resource "aws_vpc" "main" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.name_prefix }

  lifecycle {
    precondition {
      condition     = length(local.availability_zones) == 2
      error_message = "The demo requires two available standard AZs in the selected account/region."
    }
  }
}

resource "aws_default_security_group" "main" {
  vpc_id  = aws_vpc.main.id
  ingress = []
  egress  = []
  # No ingress/egress rules. Workload-specific security groups are added with the workloads.
  tags = { Name = "${var.name_prefix}-unused-default" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = var.name_prefix }
}

# Public routes serve the ALB and NAT; instances do not receive public IPs by default.
resource "aws_subnet" "public" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, tonumber(each.key))
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name_prefix}-public-${each.key}" }
}

# API, relay, Lambda and operator hosts use private subnets with outbound NAT access.
resource "aws_subnet" "application" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, 10 + tonumber(each.key))
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name_prefix}-application-${each.key}" }
}

# Database subnets have no internet route; two subnets do not make RDS Multi-AZ.
resource "aws_subnet" "database" {
  for_each = local.zones

  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.value
  cidr_block              = cidrsubnet(local.vpc_cidr, 8, 20 + tonumber(each.key))
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name_prefix}-database-${each.key}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.name_prefix}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  for_each       = local.zones
  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${var.name_prefix}-nat" }
}

# Both application AZs share this zonal gateway, so egress depends on one AZ.
resource "aws_nat_gateway" "main" {
  availability_mode = "zonal"
  connectivity_type = "public"
  allocation_id     = aws_eip.nat.id
  subnet_id         = aws_subnet.public["0"].id
  tags              = { Name = "${var.name_prefix}-nat" }
  depends_on        = [aws_internet_gateway.main, aws_route.public_internet]
}

resource "aws_route_table" "application" {
  for_each = local.zones
  vpc_id   = aws_vpc.main.id
  tags     = { Name = "${var.name_prefix}-application-${each.key}" }
}

resource "aws_route" "application_egress" {
  for_each = local.zones

  route_table_id         = aws_route_table.application[each.key].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}

resource "aws_route_table_association" "application" {
  for_each       = local.zones
  subnet_id      = aws_subnet.application[each.key].id
  route_table_id = aws_route_table.application[each.key].id
}

resource "aws_route_table" "database" {
  vpc_id = aws_vpc.main.id
  route  = []
  tags   = { Name = "${var.name_prefix}-database-isolated" }
  # Local VPC route only: RDS has no internet/NAT route.
}

resource "aws_route_table_association" "database" {
  for_each       = local.zones
  subnet_id      = aws_subnet.database[each.key].id
  route_table_id = aws_route_table.database.id
}

# Route same-region S3 traffic, including ECR image layers, outside the NAT path.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for table in aws_route_table.application : table.id]
  tags              = { Name = "${var.name_prefix}-s3" }
}
