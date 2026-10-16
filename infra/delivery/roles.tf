locals {
  repository_parts = split("/", var.github_repository)
  subject_prefix = var.oidc_subject_format == "immutable" ? (
    "repo:${local.repository_parts[0]}@${var.github_owner_id}/${local.repository_parts[1]}@${var.github_repository_id}"
  ) : "repo:${var.github_repository}"
  environments = { publish = "labpass-publish", plan = "labpass-plan", apply = "labpass-apply" }
  oidc_arn     = var.existing_oidc_provider_arn != null ? var.existing_oidc_provider_arn : aws_iam_openid_connect_provider.github[0].arn
  base_arn     = "arn:aws"
  account_arn  = "${local.base_arn}:iam::${var.aws_account_id}"
  regional_arn = "${local.base_arn}:%s:us-east-1:${var.aws_account_id}"
  lambda_arn   = "${format(local.regional_arn, "lambda")}:function:${var.workload_name_prefix}-confirmations"
  ecr_arns     = [for name in ["api", "lambda"] : "${format(local.regional_arn, "ecr")}:repository/${var.workload_name_prefix}/${name}"]
  frontend_arn = "arn:aws:s3:::${var.workload_name_prefix}-${var.aws_account_id}-frontend"
  fleet_template_arns = [for component, id in var.runtime_launch_template_ids :
    "${format(local.regional_arn, "ec2")}:launch-template/${id}" if contains(["api", "relay"], component)
  ]
}

# Reuse an account's existing GitHub provider when supplied; otherwise create it once.
resource "aws_iam_openid_connect_provider" "github" {
  count          = var.existing_oidc_provider_arn == null ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

# Each role trusts one repository/environment subject; GitHub enforces its dev-only rule.
resource "aws_iam_role" "delivery" {
  for_each             = local.environments
  name                 = "${var.workload_name_prefix}-delivery-${each.key}"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.oidc_arn }
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "${local.subject_prefix}:environment:${each.value}"
      } }
    }]
  })
}

# ECR login requires wildcard scope; image uploads are limited to the two repositories.
resource "aws_iam_role_policy" "publish" {
  role = aws_iam_role.delivery["publish"].id
  name = "publish-images"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Resource = local.ecr_arns, Action = [
        "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DescribeImages"
      ] }
    ]
  })
}

# Metadata reads needed to refresh the foundation. No secret values or log bodies.
resource "aws_iam_role_policy" "metadata" {
  for_each = toset(["plan", "apply"])
  role     = aws_iam_role.delivery[each.key].id
  name     = "foundation-metadata"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Resource = "*", Action = [
        "ec2:Describe*", "ec2:GetManagedPrefixListEntries", "ec2:GetInstanceUefiData",
        "autoscaling:Describe*", "elasticloadbalancing:Describe*",
        "rds:Describe*", "rds:ListTagsForResource", "ecr:DescribeRepositories", "ecr:GetRepositoryPolicy", "ecr:ListTagsForResource",
        "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ListQueueTags",
        "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy",
        "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:ListTagsLogGroup",
        "acm:DescribeCertificate", "acm:ListTagsForCertificate",
        "route53:GetHostedZone", "route53:ListResourceRecordSets", "route53:ListTagsForResource", "route53:GetChange",
        "cloudfront:GetDistribution", "cloudfront:GetDistributionConfig", "cloudfront:ListTagsForResource",
        "cloudfront:GetOriginAccessControl", "cloudfront:GetCachePolicy", "cloudfront:GetResponseHeadersPolicy",
        "ses:GetEmailIdentity", "ses:GetConfigurationSet", "ses:GetConfigurationSetEventDestinations", "ses:ListTagsForResource",
        "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionConcurrency", "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetRuntimeManagementConfig", "lambda:ListVersionsByFunction", "lambda:GetAlias", "lambda:ListTags", "lambda:GetEventSourceMapping",
        "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetInstanceProfile"
      ] },
      { Effect = "Allow", Resource = local.frontend_arn, Action = [
        "s3:ListBucket", "s3:GetBucket*", "s3:GetEncryptionConfiguration", "s3:GetAccelerateConfiguration",
        # These IAM action names omit "Bucket", unlike their S3 API operations.
        "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration"
      ] },
      { Effect = "Deny", Resource = "*", Action = ["secretsmanager:GetSecretValue", "secretsmanager:BatchGetSecretValue"] }
    ]
  })
}

# Plan reads state and writes plans; apply writes state and reads exact plan versions.
# Both jobs need lock-object writes/deletes to acquire and release Terraform's S3 lock.
resource "aws_iam_role_policy" "state" {
  for_each = toset(["plan", "apply"])
  role     = aws_iam_role.delivery[each.key].id
  name     = "private-state-and-plans"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Resource = aws_s3_bucket.state.arn, Action = ["s3:ListBucket", "s3:GetBucketLocation", "s3:GetBucketVersioning"] },
      { Effect = "Allow", Resource = "${aws_s3_bucket.state.arn}/${local.state_key}", Action = each.key == "apply" ? ["s3:GetObject", "s3:PutObject"] : ["s3:GetObject"] },
      { Effect = "Allow", Resource = "${aws_s3_bucket.state.arn}/${local.state_key}.tflock", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"] },
      { Effect = "Allow", Resource = "${aws_s3_bucket.state.arn}/plans/*", Action = each.key == "plan" ? ["s3:PutObject", "s3:GetObjectVersion"] : ["s3:GetObjectVersion"] }
    ]
  })
}

# Limit deployment writes to the existing fleets, worker, frontend and migration command.
# Launch-template and migration permissions appear only when their resource IDs are supplied.
resource "aws_iam_role_policy" "release" {
  role = aws_iam_role.delivery["apply"].id
  name = "existing-runtime-release"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      { Effect = "Allow", Resource = [for name in ["api", "relay"] : "${format(local.regional_arn, "autoscaling")}:autoScalingGroup:*:autoScalingGroupName/${var.workload_name_prefix}-${name}"], Action = ["autoscaling:UpdateAutoScalingGroup", "autoscaling:StartInstanceRefresh", "autoscaling:CancelInstanceRefresh"] },
      { Effect = "Allow", Resource = [local.lambda_arn, "${local.lambda_arn}:*"], Action = ["lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:PublishVersion", "lambda:UpdateAlias"] },
      { Effect = "Allow", Resource = "${local.account_arn}:role/${var.workload_name_prefix}-consumer", Action = ["iam:PassRole"], Condition = { StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" } } },
      { Effect = "Allow", Resource = "${local.frontend_arn}/*", Action = ["s3:PutObject"] },
      { Effect = "Allow", Resource = "*", Action = ["ssm:GetCommandInvocation"] }
      ], length(var.runtime_launch_template_ids) == 0 ? [] : [{
        Effect = "Allow", Resource = [for id in var.runtime_launch_template_ids : "${format(local.regional_arn, "ec2")}:launch-template/${id}"],
        Action = ["ec2:CreateLaunchTemplateVersion", "ec2:ModifyLaunchTemplate"]
        }], var.migration_instance_id == null ? [] : [{
        Effect = "Allow", Resource = [aws_ssm_document.migrate.arn, "${format(local.regional_arn, "ec2")}:instance/${var.migration_instance_id}"], Action = ["ssm:SendCommand"]
        }], [for statement in [
        {
          Sid    = "ValidateFleetLaunches"
          Effect = "Allow"
          Action = ["ec2:RunInstances"]
          Resource = concat(
            ["arn:aws:ec2:us-east-1::image/*"],
            [for kind in ["instance", "volume", "network-interface", "subnet", "security-group"] : "${format(local.regional_arn, "ec2")}:${kind}/*"],
            local.fleet_template_arns
          )
          Condition = { ArnEquals = { "ec2:LaunchTemplate" = local.fleet_template_arns } }
        },
        {
          Sid       = "PassFleetRoles"
          Effect    = "Allow"
          Action    = ["iam:PassRole"]
          Resource  = [for component in ["api", "relay"] : "${local.account_arn}:role/${var.workload_name_prefix}-${component}"]
          Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } }
        },
        {
          Sid      = "TagFleetLaunches"
          Effect   = "Allow"
          Action   = ["ec2:CreateTags"]
          Resource = [for kind in ["instance", "volume"] : "${format(local.regional_arn, "ec2")}:${kind}/*"]
          Condition = { StringEquals = {
            "ec2:CreateAction"         = "RunInstances"
            "aws:RequestTag/Project"   = "LabPass"
            "aws:RequestTag/Component" = ["api", "relay"]
          } }
        }
    ] : statement if length(local.fleet_template_arns) > 0])
  })
}
