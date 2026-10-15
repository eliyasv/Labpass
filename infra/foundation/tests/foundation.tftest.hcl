# All resource identifiers below are fictional and generated only by the mock provider.
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

override_resource {
  target = aws_sqs_queue.confirmations
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/mock-confirmations"
  }
}

override_resource {
  target = aws_sqs_queue.dead_letter
  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:mock-dlq"
    id  = "https://sqs.us-east-1.amazonaws.com/123456789012/mock-dlq"
  }
}

variables {
  aws_account_id = "123456789012"
}

run "demo_foundation" {
  # Apply only to the mock provider's in-memory state, never to AWS.
  command = apply

  assert {
    condition = (
      length(aws_subnet.public) == 2 &&
      length(aws_subnet.application) == 2 &&
      length(aws_subnet.database) == 2 &&
      length(toset(local.availability_zones)) == 2
    )
    error_message = "Separate public, application and database subnets must span two AZs."
  }

  assert {
    condition = alltrue([
      for subnet in concat(values(aws_subnet.public), values(aws_subnet.application), values(aws_subnet.database)) :
      !subnet.map_public_ip_on_launch
    ])
    error_message = "Instances must not receive automatic public IPs."
  }

  assert {
    condition = length(toset(concat(
      [for subnet in aws_subnet.public : subnet.cidr_block],
      [for subnet in aws_subnet.application : subnet.cidr_block],
      [for subnet in aws_subnet.database : subnet.cidr_block],
    ))) == 6
    error_message = "The six equal-size subnets must have distinct CIDRs."
  }

  assert {
    condition = (
      aws_route.public_internet.gateway_id == aws_internet_gateway.main.id &&
      alltrue([for route in aws_route.application_egress : route.nat_gateway_id == aws_nat_gateway.main.id]) &&
      length(aws_route_table.database.route) == 0 &&
      alltrue([for association in aws_route_table_association.database : association.route_table_id == aws_route_table.database.id])
    )
    error_message = "Public/application egress and isolated database associations must remain separate."
  }

  assert {
    condition = (
      aws_nat_gateway.main.subnet_id == aws_subnet.public["0"].id &&
      aws_vpc_endpoint.s3.vpc_endpoint_type == "Gateway" &&
      toset(aws_vpc_endpoint.s3.route_table_ids) == toset([for table in aws_route_table.application : table.id])
    )
    error_message = "The demo uses one public NAT and an S3 gateway path for application subnets."
  }

  assert {
    condition = (
      length(aws_default_security_group.main.ingress) == 0 &&
      length(aws_default_security_group.main.egress) == 0
    )
    error_message = "The default security group must have no traffic rules."
  }

  assert {
    condition = alltrue([
      for repository in aws_ecr_repository.application :
      repository.image_tag_mutability == "IMMUTABLE" && repository.force_delete
    ])
    error_message = "Demo images must use immutable tags and be removable during authorized teardown."
  }

  assert {
    condition = (
      aws_sqs_queue.confirmations.visibility_timeout_seconds >= 6 * 60 &&
      aws_sqs_queue.dead_letter.message_retention_seconds > aws_sqs_queue.confirmations.message_retention_seconds &&
      jsondecode(aws_sqs_queue.confirmations.redrive_policy).maxReceiveCount == 5 &&
      jsondecode(aws_sqs_queue.confirmations.redrive_policy).deadLetterTargetArn == aws_sqs_queue.dead_letter.arn &&
      aws_sqs_queue.confirmations.arn != aws_sqs_queue.dead_letter.arn &&
      aws_sqs_queue.confirmations.sqs_managed_sse_enabled &&
      aws_sqs_queue.dead_letter.sqs_managed_sse_enabled
    )
    error_message = "Queues must preserve the Lambda retry, visibility, retention and encryption contract."
  }

  assert {
    condition = (
      jsondecode(aws_sqs_queue_redrive_allow_policy.dead_letter.redrive_allow_policy).redrivePermission == "byQueue" &&
      jsondecode(aws_sqs_queue_redrive_allow_policy.dead_letter.redrive_allow_policy).sourceQueueArns == [aws_sqs_queue.confirmations.arn]
    )
    error_message = "The DLQ must allow redrive only from this source queue."
  }
}

run "reject_other_region" {
  command = plan
  variables {
    aws_region = "eu-west-1"
  }
  expect_failures = [var.aws_region]
}

run "reject_missing_account" {
  command = plan
  variables {
    aws_account_id = ""
  }
  expect_failures = [var.aws_account_id]
}

run "reject_single_available_zone" {
  command = plan
  override_data {
    target = data.aws_availability_zones.available
    values = { names = ["us-east-1a"] }
  }
  expect_failures = [aws_vpc.main]
}
