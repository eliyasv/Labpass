# Fail planning if this PostgreSQL version/class/storage combination is unavailable.
data "aws_rds_orderable_db_instance" "postgres" {
  engine                     = "postgres"
  engine_version             = var.database_engine_version
  storage_type               = "gp3"
  preferred_instance_classes = ["db.t4g.micro"]
}

resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-database"
  subnet_ids = var.database_subnet_ids
}

# Require encrypted client connections and SCRAM password authentication.
resource "aws_db_parameter_group" "postgres" {
  name   = "${var.name_prefix}-postgres18"
  family = "postgres18"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
    # Match RDS's reported apply method to avoid drift on the unchanged TLS value.
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "password_encryption"
    value = "scram-sha-256"
  }
}

resource "aws_security_group" "database" {
  name        = "${var.name_prefix}-database"
  description = "PostgreSQL access from explicit workload groups"
  vpc_id      = var.vpc_id
  egress      = []
}

locals {
  database_clients = toset(["api", "relay", "consumer", "migration", "bootstrap"])
}

# Separate client groups let RDS admit each workload without opening a VPC-wide CIDR.
resource "aws_security_group" "database_client" {
  for_each    = local.database_clients
  name        = "${var.name_prefix}-${each.key}"
  description = "${each.key} private runtime access"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  for_each                     = local.database_clients
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.database_client[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "postgres" {
  for_each                     = local.database_clients
  security_group_id            = aws_security_group.database_client[each.key].id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# AWS APIs and image/package retrieval use HTTPS through the application NAT path.
resource "aws_vpc_security_group_egress_rule" "https" {
  for_each          = local.database_clients
  security_group_id = aws_security_group.database_client[each.key].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# Single-AZ database in isolated subnets; the subnet group does not create a standby.
# RDS manages the master password in Secrets Manager, outside Terraform values.
resource "aws_db_instance" "main" {
  identifier                  = "${var.name_prefix}-postgres"
  engine                      = "postgres"
  engine_version              = var.database_engine_version
  instance_class              = data.aws_rds_orderable_db_instance.postgres.instance_class
  db_name                     = "labpass"
  port                        = 5432
  username                    = "labpass_admin"
  manage_master_user_password = true
  allocated_storage           = 20
  storage_type                = "gp3"
  storage_encrypted           = true
  publicly_accessible         = false
  multi_az                    = false
  db_subnet_group_name        = aws_db_subnet_group.main.name
  parameter_group_name        = aws_db_parameter_group.postgres.name
  vpc_security_group_ids      = [aws_security_group.database.id]
  backup_retention_period     = 7
  copy_tags_to_snapshot       = true
  deletion_protection         = var.database_deletion_protection
  # Destruction preserves a final snapshot; repeated use of this name can collide.
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.name_prefix}-postgres-final"
  auto_minor_version_upgrade  = true
  allow_major_version_upgrade = false
  engine_lifecycle_support    = "open-source-rds-extended-support-disabled"

  lifecycle {
    precondition {
      condition     = data.aws_rds_orderable_db_instance.postgres.instance_class == "db.t4g.micro"
      error_message = "The selected PostgreSQL version must support db.t4g.micro with gp3 in the target region."
    }
  }
}

# Create containers only; the bootstrap job writes passwords and PostgreSQL roles.
resource "aws_secretsmanager_secret" "database" {
  for_each                = toset(["api", "relay", "consumer", "migration"])
  name                    = "${var.name_prefix}/database/${each.key}"
  description             = "Restricted ${each.key} PostgreSQL credentials"
  recovery_window_in_days = 7
}
