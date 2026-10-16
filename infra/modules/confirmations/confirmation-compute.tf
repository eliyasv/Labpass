resource "aws_cloudwatch_log_group" "confirmations" {
  count             = local.confirmation_enabled ? 1 : 0
  name              = "/aws/lambda/${local.confirmation_name}"
  retention_in_days = 7
}

# Use the consumer's SQL identity in private subnets; SES/Secrets Manager use NAT.
# The image is pinned by digest, and publish creates a version for the live alias.
# Reserved concurrency -1 uses the account pool; the SQS mapping limit still applies.
resource "aws_lambda_function" "confirmations" {
  count                          = local.confirmation_enabled ? 1 : 0
  function_name                  = local.confirmation_name
  role                           = var.consumer_role.arn
  package_type                   = "Image"
  image_uri                      = "${var.lambda_repository.repository_url}@${var.confirmation_worker.image_digest}"
  architectures                  = ["x86_64"]
  publish                        = true
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = var.confirmation_worker.reserve_concurrency ? var.confirmation_worker.max_concurrency : -1

  image_config {
    command = ["labpass.lambda_handler.lambda_handler"]
  }
  ephemeral_storage {
    size = 512
  }
  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.confirmations[0].name
  }
  vpc_config {
    subnet_ids         = var.application_subnet_ids
    security_group_ids = [var.consumer_security_group_id]
  }
  environment {
    variables = {
      LABPASS_AWS_ENABLED   = "true"
      LABPASS_QUEUE_ARN     = var.queue_arn
      LABPASS_DB_SECRET_ARN = var.database.secret_arn
      LABPASS_DB_HOST       = var.database.host
      LABPASS_DB_NAME       = var.database.name
      LABPASS_DB_PORT       = tostring(var.database.port)
      LABPASS_DB_CA_FILE    = "/var/task/certs/rds-global-bundle.pem"
      LABPASS_SES_FROM      = var.confirmation_worker.sender_email
    }
  }

  depends_on = [
    aws_iam_role_policy.confirmation_runtime,
    aws_ecr_repository_policy.lambda,
  ]
}

# The queue invokes a named alias so releases can move it to a published version.
resource "aws_lambda_alias" "confirmations" {
  count            = local.confirmation_enabled ? 1 : 0
  name             = "live"
  function_name    = aws_lambda_function.confirmations[0].function_name
  function_version = aws_lambda_function.confirmations[0].version
}

# AWS polls SQS and invokes Lambda; failed records are retried rather than acknowledged.
resource "aws_lambda_event_source_mapping" "confirmations" {
  count                              = local.confirmation_enabled ? 1 : 0
  event_source_arn                   = var.queue_arn
  function_name                      = aws_lambda_alias.confirmations[0].arn
  enabled                            = var.confirmation_worker.mapping_enabled
  batch_size                         = 1
  maximum_batching_window_in_seconds = 0
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.confirmation_worker.max_concurrency
  }

  lifecycle {
    # Leave enough visibility time for processing and Lambda retries.
    precondition {
      condition     = var.queue_visibility_timeout_seconds >= 6 * aws_lambda_function.confirmations[0].timeout
      error_message = "SQS visibility must be at least six times the Lambda timeout with a zero batching window."
    }
    # This checks SES/DKIM only; database readiness and sandbox recipients need operator checks.
    precondition {
      condition = !var.confirmation_worker.mapping_enabled || (
        aws_sesv2_email_identity.confirmations[0].verified_for_sending_status &&
        aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].status == "SUCCESS"
      )
      error_message = "Keep the mapping disabled until SES reports the sender domain verified and DKIM successful. Complete database bootstrap and check recipient/account restrictions before enabling it."
    }
  }

  depends_on = [aws_route53_record.email_dkim, aws_sesv2_configuration_set_event_destination.metrics]
}
