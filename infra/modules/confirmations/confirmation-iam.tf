locals {
  lambda_eni_actions = [
    "ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets",
    "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses",
  ]
}

resource "aws_iam_role_policy" "confirmation_runtime" {
  count = local.confirmation_enabled ? 1 : 0
  name  = "confirmation-runtime"
  role  = var.consumer_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DeliveryLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.confirmations[0].arn}:*"
      },
      {
        Sid      = "SendConfirmation"
        Effect   = "Allow"
        Action   = ["ses:SendEmail"]
        Resource = [aws_sesv2_email_identity.confirmations[0].arn, aws_sesv2_configuration_set.confirmations[0].arn]
        Condition = {
          StringEquals = { "ses:FromAddress" = var.confirmation_worker.sender_email }
        }
      },
      {
        Sid      = "LambdaVpcInterfaces"
        Effect   = "Allow"
        Action   = local.lambda_eni_actions
        Resource = "*"
      },
      {
        Sid      = "DenyFunctionCodeVpcChanges"
        Effect   = "Deny"
        Action   = concat(local.lambda_eni_actions, ["ec2:DetachNetworkInterface"])
        Resource = "*"
        Condition = {
          ArnEquals = { "lambda:SourceFunctionArn" = local.confirmation_function_arn }
        }
      }
    ]
  })
}

resource "aws_ecr_repository_policy" "lambda" {
  count      = local.confirmation_enabled ? 1 : 0
  repository = var.lambda_repository.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "LambdaImageRetrieval"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Resource  = var.lambda_repository.arn
      Condition = {
        ArnLike = { "aws:SourceArn" = [local.confirmation_function_arn, "${local.confirmation_function_arn}:*"] }
      }
    }]
  })
}
