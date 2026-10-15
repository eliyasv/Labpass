resource "aws_cloudwatch_log_group" "runtime" {
  for_each          = local.hosting_roles
  name              = "/labpass/${var.name_prefix}/${each.key}"
  retention_in_days = 7
}

resource "aws_iam_role_policy_attachment" "ssm" {
  for_each   = local.hosting_roles
  role       = var.runtime_roles[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "container_runtime" {
  for_each = local.hosting_roles
  name     = "container-runtime"
  role     = var.runtime_roles[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
        Resource = var.api_repository.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"]
        Resource = [aws_cloudwatch_log_group.runtime[each.key].arn, "${aws_cloudwatch_log_group.runtime[each.key].arn}:*"]
      }
    ]
  })
}
