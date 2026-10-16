locals {
  lambda_eni_actions = [
    "ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DescribeSubnets",
    "ec2:DeleteNetworkInterface", "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses",
  ]
}

# Add delivery permissions to the consumer role's existing database/SQS grants.
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
        Sid    = "SendConfirmation"
        Effect = "Allow"
        Action = ["ses:SendEmail"]
        Resource = concat(
          [aws_sesv2_email_identity.confirmations[0].arn, aws_sesv2_configuration_set.confirmations[0].arn],
          # SES can authorize sandbox recipients against their verified identity ARN.
          [for email in sort(tolist(var.confirmation_worker.verified_recipient_emails)) :
            "arn:aws:ses:${var.aws_region}:${var.aws_account_id}:identity/${email}"
          ]
        )
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
        # Preserve service-managed ENI access while denying these calls from handler code.
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

# Grant Lambda's service image reads only when retrieving this function's image.
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
      Condition = {
        ArnLike = { "aws:SourceArn" = [local.confirmation_function_arn, "${local.confirmation_function_arn}:*"] }
      }
    }]
  })
}
