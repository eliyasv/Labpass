# API/relay share one image; Lambda has its own AWS-runtime image and repository.
resource "aws_ecr_repository" "application" {
  for_each = toset(["api", "lambda"])

  name                 = "${var.name_prefix}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  # Allow repository deletion even when it contains published images.
  force_delete = true

  encryption_configuration {
    encryption_type = "AES256"
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Failed events outlive source messages, leaving time for inspection and replay.
resource "aws_sqs_queue" "dead_letter" {
  name                      = "${var.name_prefix}-confirmations-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

# Decouple confirmation delivery from the booking transaction and relay process.
# Visibility is six times the Lambda's 60-second timeout, checked by the mapping.
resource "aws_sqs_queue" "confirmations" {
  name                       = "${var.name_prefix}-confirmations"
  visibility_timeout_seconds = 360
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 5
  })
}

# Prevent unrelated queues from using this DLQ as their redrive destination.
resource "aws_sqs_queue_redrive_allow_policy" "dead_letter" {
  queue_url = aws_sqs_queue.dead_letter.id
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.confirmations.arn]
  })
}
