mock_provider "aws" { source = "./tests/fixtures/confirmations" }
mock_provider "aws" {
  alias  = "verified"
  source = "./tests/fixtures/confirmations"
  mock_resource "aws_sesv2_email_identity" {
    defaults = {
      arn                         = "arn:aws:ses:us-east-1:123456789012:identity/example.com"
      verified_for_sending_status = true
      dkim_signing_attributes = {
        tokens = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccccccccccccccc"]
        status = "SUCCESS"
      }
    }
  }
}
mock_provider "aws" {
  alias  = "pending_dkim"
  source = "./tests/fixtures/confirmations"
  mock_resource "aws_sesv2_email_identity" {
    defaults = {
      arn                         = "arn:aws:ses:us-east-1:123456789012:identity/example.com"
      verified_for_sending_status = true
      dkim_signing_attributes = {
        tokens = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccccccccccccccc"]
        status = "PENDING"
      }
    }
  }
}

override_data {
  target = data.aws_route53_zone.email[0]
  values = { name = "example.com", private_zone = false }
}

variables {
  aws_account_id = "123456789012"
  confirmation_worker = {
    image_digest   = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    email_domain   = "example.com"
    sender_email   = "notifications@example.com"
    hosted_zone_id = "Z00000000000001"
  }

  application_subnet_ids = ["subnet-00000000000000005", "subnet-00000000000000006"]
  consumer_role = {
    id  = "labpass-demo-consumer"
    arn = "arn:aws:iam::123456789012:role/labpass-demo-consumer"
  }
  consumer_security_group_id = "sg-00000000000000003"
  database = {
    host       = "mock.example.us-east-1.rds.amazonaws.com"
    name       = "labpass"
    port       = 5432
    secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-consumer-AbCd12"
  }
  lambda_repository = {
    repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/lambda"
    arn            = "arn:aws:ecr:us-east-1:123456789012:repository/labpass-demo/lambda"
    name           = "labpass-demo/lambda"
  }
  queue_arn                        = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations"
  queue_visibility_timeout_seconds = 360
}

run "worker_disabled" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = null }
  assert {
    condition = (
      length(aws_lambda_function.confirmations) == 0 &&
      length(aws_lambda_event_source_mapping.confirmations) == 0 &&
      length(aws_lambda_alias.confirmations) == 0 &&
      length(aws_sesv2_email_identity.confirmations) == 0 &&
      length(aws_sesv2_configuration_set.confirmations) == 0 &&
      length(aws_route53_record.email_dkim) == 0 &&
      length(aws_ecr_repository_policy.lambda) == 0 &&
      length(aws_iam_role_policy.confirmation_runtime) == 0 &&
      output.confirmation_worker == null
    )
    error_message = "Null configuration must omit the confirmation workload and its optional permissions."
  }
}

run "private_versioned_worker" {
  module { source = "../modules/confirmations" }
  command = apply

  assert {
    condition = (
      aws_lambda_function.confirmations[0].package_type == "Image" &&
      aws_lambda_function.confirmations[0].image_uri == "${var.lambda_repository.repository_url}@${var.confirmation_worker.image_digest}" &&
      aws_lambda_function.confirmations[0].architectures == tolist(["x86_64"]) &&
      aws_lambda_function.confirmations[0].image_config[0].command == tolist(["labpass.lambda_handler.lambda_handler"]) &&
      aws_lambda_function.confirmations[0].publish &&
      aws_lambda_alias.confirmations[0].function_version == "7" &&
      aws_lambda_event_source_mapping.confirmations[0].function_name == aws_lambda_alias.confirmations[0].arn &&
      aws_lambda_function.confirmations[0].role == var.consumer_role.arn &&
      aws_lambda_function.confirmations[0].vpc_config[0].subnet_ids == toset(var.application_subnet_ids) &&
      aws_lambda_function.confirmations[0].vpc_config[0].security_group_ids == toset([var.consumer_security_group_id]) &&
      aws_cloudwatch_log_group.confirmations[0].retention_in_days == 7 &&
      aws_lambda_function.confirmations[0].logging_config[0].log_group == aws_cloudwatch_log_group.confirmations[0].name
    )
    error_message = "The worker must use a digest, numeric published version, stable alias and its private consumer network/role."
  }

  assert {
    condition = (
      aws_lambda_function.confirmations[0].timeout == 60 &&
      aws_lambda_function.confirmations[0].memory_size == 512 &&
      aws_lambda_event_source_mapping.confirmations[0].batch_size == 1 &&
      aws_lambda_event_source_mapping.confirmations[0].maximum_batching_window_in_seconds == 0 &&
      aws_lambda_event_source_mapping.confirmations[0].function_response_types == toset(["ReportBatchItemFailures"]) &&
      aws_lambda_event_source_mapping.confirmations[0].scaling_config[0].maximum_concurrency == 2 &&
      aws_lambda_function.confirmations[0].reserved_concurrent_executions == 2 &&
      var.queue_visibility_timeout_seconds >= 6 * aws_lambda_function.confirmations[0].timeout &&
      !aws_lambda_event_source_mapping.confirmations[0].enabled &&
      output.confirmation_worker.mapping_enabled == false
    )
    error_message = "Invocation, visibility, concurrency and partial failures must match the handler contract; polling starts disabled."
  }

  assert {
    condition = (
      aws_lambda_function.confirmations[0].environment[0].variables == tomap({
        LABPASS_AWS_ENABLED   = "true"
        LABPASS_QUEUE_ARN     = var.queue_arn
        LABPASS_DB_SECRET_ARN = var.database.secret_arn
        LABPASS_DB_HOST       = var.database.host
        LABPASS_DB_NAME       = var.database.name
        LABPASS_DB_PORT       = "5432"
        LABPASS_DB_CA_FILE    = "/var/task/certs/rds-global-bundle.pem"
        LABPASS_SES_FROM      = var.confirmation_worker.sender_email
      }) &&
      !contains(keys(aws_lambda_function.confirmations[0].environment[0].variables), "AWS_REGION") &&
      !contains(keys(aws_lambda_function.confirmations[0].environment[0].variables), "DATABASE_URL")
    )
    error_message = "Environment must contain only runtime metadata, including the consumer secret ARN and image CA path; AWS supplies reserved credential/region variables."
  }
}

run "scoped_permissions_and_ses" {
  module { source = "../modules/confirmations" }
  command = apply

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[0].Resource == "${aws_cloudwatch_log_group.confirmations[0].arn}:*" &&
      toset(jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[0].Action) == toset(["logs:CreateLogStream", "logs:PutLogEvents"]) &&
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[1].Action == ["ses:SendEmail"] &&
      toset(jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[1].Resource) == toset([aws_sesv2_email_identity.confirmations[0].arn, aws_sesv2_configuration_set.confirmations[0].arn]) &&
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[1].Condition.StringEquals["ses:FromAddress"] == var.confirmation_worker.sender_email
    )
    error_message = "Logs and email sends must stay scoped to the consumer log group, identity/configuration set and exact sender."
  }

  assert {
    condition = (
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[2].Effect == "Allow" &&
      toset(jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[2].Action) == toset([
        "ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets",
        "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses"
      ]) &&
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[3].Effect == "Deny" &&
      jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[3].Condition.ArnEquals["lambda:SourceFunctionArn"] == local.confirmation_function_arn &&
      toset(jsondecode(aws_iam_role_policy.confirmation_runtime[0].policy).Statement[3].Action) == setunion(toset(local.lambda_eni_actions), toset(["ec2:DetachNetworkInterface"])) &&
      jsondecode(aws_ecr_repository_policy.lambda[0].policy).Statement[0].Principal.Service == "lambda.amazonaws.com" &&
      toset(jsondecode(aws_ecr_repository_policy.lambda[0].policy).Statement[0].Action) == toset(["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]) &&
      jsondecode(aws_ecr_repository_policy.lambda[0].policy).Statement[0].Resource == var.lambda_repository.arn &&
      toset(jsondecode(aws_ecr_repository_policy.lambda[0].policy).Statement[0].Condition.ArnLike["aws:SourceArn"]) == toset([local.confirmation_function_arn, "${local.confirmation_function_arn}:*"])
    )
    error_message = "Lambda service ENI management must be denied to function code; image retrieval must be restricted to the worker and repository."
  }

  assert {
    condition = (
      aws_sesv2_email_identity.confirmations[0].email_identity == var.confirmation_worker.email_domain &&
      aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].next_signing_key_length == "RSA_2048_BIT" &&
      aws_sesv2_email_identity.confirmations[0].configuration_set_name == aws_sesv2_configuration_set.confirmations[0].configuration_set_name &&
      length(aws_route53_record.email_dkim) == 3 &&
      alltrue([for index, record in aws_route53_record.email_dkim :
        record.zone_id == var.confirmation_worker.hosted_zone_id &&
        record.type == "CNAME" &&
        record.name == "${aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].tokens[tonumber(index)]}._domainkey.${var.confirmation_worker.email_domain}" &&
        record.records == toset(["${aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].tokens[tonumber(index)]}.dkim.amazonses.com"])
      ]) &&
      toset(aws_sesv2_configuration_set.confirmations[0].suppression_options[0].suppressed_reasons) == toset(["BOUNCE", "COMPLAINT"]) &&
      aws_sesv2_configuration_set_event_destination.metrics[0].event_destination[0].enabled &&
      aws_sesv2_configuration_set_event_destination.metrics[0].event_destination[0].matching_event_types == toset(["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"]) &&
      aws_sesv2_configuration_set_event_destination.metrics[0].event_destination[0].cloud_watch_destination[0].dimension_configuration[0].dimension_name == "ses:configuration-set"
    )
    error_message = "SES must use domain DKIM, three DNS tokens, default configuration-set metrics and bounce/complaint suppression."
  }
}

run "reject_unverified_sender_polling" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { mapping_enabled = true }) }
  expect_failures = [aws_lambda_event_source_mapping.confirmations[0]]
}

run "enable_verified_worker" {
  module { source = "../modules/confirmations" }
  providers = { aws = aws.verified }
  command   = apply
  state_key = "verified-worker"
  variables { confirmation_worker = merge(var.confirmation_worker, { mapping_enabled = true, max_concurrency = 3 }) }
  assert {
    condition = (
      aws_lambda_event_source_mapping.confirmations[0].enabled &&
      aws_lambda_function.confirmations[0].reserved_concurrent_executions == 3 &&
      aws_lambda_event_source_mapping.confirmations[0].scaling_config[0].maximum_concurrency == 3
    )
    error_message = "Explicit activation must preserve a shared function/mapping concurrency cap."
  }
}

run "reject_pending_dkim_polling" {
  module { source = "../modules/confirmations" }
  providers = { aws = aws.pending_dkim }
  command   = apply
  state_key = "pending-dkim"
  variables { confirmation_worker = merge(var.confirmation_worker, { mapping_enabled = true }) }
  expect_failures = [aws_lambda_event_source_mapping.confirmations[0]]
}

run "reject_mutable_image" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { image_digest = "latest" }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_other_sender_domain" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { sender_email = "notifications@other.example.com" }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_multiple_at_signs" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { sender_email = "notifications@bad@example.com" }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_unnormalized_sender" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { sender_email = "Notifications@example.com" }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_single_consumer_concurrency" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { max_concurrency = 1 }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_fractional_concurrency" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { max_concurrency = 2.5 }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_excess_concurrency" {
  module { source = "../modules/confirmations" }
  command = plan
  variables { confirmation_worker = merge(var.confirmation_worker, { max_concurrency = 11 }) }
  expect_failures = [var.confirmation_worker]
}

run "reject_unrelated_zone" {
  module { source = "../modules/confirmations" }
  command = plan
  override_data {
    target = data.aws_route53_zone.email[0]
    values = { name = "unrelated.com", private_zone = false }
  }
  expect_failures = [data.aws_route53_zone.email[0]]
}
