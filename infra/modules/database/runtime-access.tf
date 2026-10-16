# Consumer runs on Lambda; API, relay and controlled operator jobs run on EC2.
resource "aws_iam_role" "runtime" {
  for_each = local.database_clients
  name     = "${var.name_prefix}-${each.key}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = each.key == "consumer" ? "lambda.amazonaws.com" : "ec2.amazonaws.com" }
    }]
  })
}

# Each runtime reads only its own database secret; SQL grants are set by bootstrap.
resource "aws_iam_role_policy" "database_secret" {
  for_each = aws_secretsmanager_secret.database
  name     = "database-secret"
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = each.value.arn
    }]
  })
}

# Only bootstrap reads the master secret and initializes the four runtime secrets.
resource "aws_iam_role_policy" "bootstrap_secrets" {
  name = "database-bootstrap"
  role = aws_iam_role.runtime["bootstrap"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_db_instance.main.master_user_secret[0].secret_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue"]
        Resource = [for secret in aws_secretsmanager_secret.database : secret.arn]
      }
    ]
  })
}

# Relay publishes; the consumer receives/deletes. The API has no queue dependency.
resource "aws_iam_role_policy" "queue" {
  for_each = toset(["relay", "consumer"])
  name     = "confirmation-queue"
  role     = aws_iam_role.runtime[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = each.key == "relay" ? ["sqs:SendMessage"] : ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = var.queue_arn
    }]
  })
}

# EC2 receives temporary role credentials through these profiles; Lambda uses its role directly.
resource "aws_iam_instance_profile" "runtime" {
  for_each = toset(["api", "relay", "migration", "bootstrap"])
  name     = "${var.name_prefix}-${each.key}"
  role     = aws_iam_role.runtime[each.key].name
}
