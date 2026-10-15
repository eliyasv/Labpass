mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1b", "us-east-1a"] }
  }
  mock_data "aws_rds_orderable_db_instance" {
    defaults = { instance_class = "db.t4g.micro" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-master-AbCd12"
        kms_key_id    = "mock-key"
        secret_status = "active"
      }]
    }
  }
}

variables {
  aws_account_id = "123456789012"

  vpc_id              = "vpc-00000000000000001"
  database_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  queue_arn           = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations"
}



run "private_database_and_access" {
  module { source = "../modules/database" }
  command = apply

  assert {
    condition = (
      !aws_db_instance.main.publicly_accessible &&
      aws_db_instance.main.storage_encrypted &&
      aws_db_instance.main.manage_master_user_password &&
      aws_db_instance.main.password == null &&
      aws_db_instance.main.deletion_protection &&
      !aws_db_instance.main.skip_final_snapshot &&
      length(aws_security_group.database.egress) == 0 &&
      aws_db_instance.main.backup_retention_period == 7 &&
      aws_db_instance.main.port == 5432 &&
      toset(aws_db_subnet_group.main.subnet_ids) == toset(var.database_subnet_ids) &&
      toset(aws_db_instance.main.vpc_security_group_ids) == toset([aws_security_group.database.id])
    )
    error_message = "RDS must be private, encrypted, backed up and use managed credentials."
  }

  assert {
    condition = (
      length(aws_vpc_security_group_ingress_rule.postgres) == 5 &&
      alltrue([for name, rule in aws_vpc_security_group_ingress_rule.postgres :
        rule.referenced_security_group_id == aws_security_group.database_client[name].id &&
        rule.security_group_id == aws_security_group.database.id &&
        rule.cidr_ipv4 == null && rule.ip_protocol == "tcp" &&
        rule.from_port == 5432 && rule.to_port == 5432
      ]) &&
      alltrue([for rule in aws_vpc_security_group_egress_rule.postgres :
        rule.referenced_security_group_id == aws_security_group.database.id &&
        rule.from_port == 5432 && rule.to_port == 5432
      ])
    )
    error_message = "PostgreSQL access must use workload group references, without public CIDRs."
  }

  assert {
    condition = alltrue([for name, policy in aws_iam_role_policy.database_secret :
      jsondecode(policy.policy).Statement[0].Resource == aws_secretsmanager_secret.database[name].arn &&
      jsondecode(policy.policy).Statement[0].Action == ["secretsmanager:GetSecretValue"]
    ])
    error_message = "Each runtime may read only its own database secret."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.bootstrap_secrets.policy).Statement[0].Resource == aws_db_instance.main.master_user_secret[0].secret_arn &&
      toset(jsondecode(aws_iam_role_policy.bootstrap_secrets.policy).Statement[1].Resource) == toset([for secret in aws_secretsmanager_secret.database : secret.arn]) &&
      jsondecode(aws_iam_role_policy.queue["relay"].policy).Statement[0].Action == ["sqs:SendMessage"] &&
      jsondecode(aws_iam_role_policy.queue["consumer"].policy).Statement[0].Resource == var.queue_arn &&
      jsondecode(aws_iam_role.runtime["consumer"].assume_role_policy).Statement[0].Principal.Service == "lambda.amazonaws.com"
    )
    error_message = "Bootstrap and queue permissions must remain separate from runtime secret access."
  }

  assert {
    condition = (
      { for parameter in aws_db_parameter_group.postgres.parameter : parameter.name => parameter.value }["rds.force_ssl"] == "1" &&
      { for parameter in aws_db_parameter_group.postgres.parameter : parameter.name => parameter.value }["password_encryption"] == "scram-sha-256"
    )
    error_message = "PostgreSQL must enforce TLS and SCRAM password storage."
  }
}


run "reject_other_database_major" {
  module { source = "../modules/database" }
  command = plan
  variables {
    database_engine_version = "17.11"
  }
  expect_failures = [var.database_engine_version]
}


run "reject_unavailable_instance_class" {
  module { source = "../modules/database" }
  command = plan
  override_data {
    target = data.aws_rds_orderable_db_instance.postgres
    values = { instance_class = "db.r5.large" }
  }
  expect_failures = [aws_db_instance.main]
}
