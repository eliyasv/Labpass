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

resource "aws_iam_instance_profile" "runtime" {
  for_each = toset(["api", "relay", "migration", "bootstrap"])
  name     = "${var.name_prefix}-${each.key}"
  role     = aws_iam_role.runtime[each.key].name
}
