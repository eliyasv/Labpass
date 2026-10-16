# All account and resource identifiers are fictional. No AWS credentials are used.
mock_provider "aws" {
  mock_resource "aws_s3_bucket" {
    defaults = {
      id  = "labpass-demo-123456789012-tfstate"
      arn = "arn:aws:s3:::labpass-demo-123456789012-tfstate"
    }
  }
  mock_resource "aws_iam_openid_connect_provider" {
    defaults = { arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
  }
  mock_resource "aws_ssm_document" {
    defaults = { arn = "arn:aws:ssm:us-east-1:123456789012:document/labpass-demo-release-migration" }
  }
  mock_resource "aws_route53_zone" {
    defaults = {
      zone_id = "Z00000000000000000001"
      name_servers = [
        "ns-1.example.net", "ns-2.example.net", "ns-3.example.net", "ns-4.example.net"
      ]
    }
  }
}

variables {
  aws_account_id       = "123456789012"
  github_repository    = "example/labpass"
  github_owner_id      = "1"
  github_repository_id = "2"
}

run "private_state_and_oidc_boundaries" {
  command = apply

  assert {
    condition     = length(aws_route53_zone.public) == 0 && output.public_dns == null
    error_message = "Omitting the domain must leave existing bootstrap deployments without a new DNS zone."
  }
  assert {
    condition = (
      !aws_s3_bucket.state.force_destroy &&
      aws_s3_bucket_public_access_block.state.block_public_acls &&
      aws_s3_bucket_public_access_block.state.block_public_policy &&
      aws_s3_bucket_public_access_block.state.ignore_public_acls &&
      aws_s3_bucket_public_access_block.state.restrict_public_buckets &&
      aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled" &&
      one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256" &&
      jsondecode(aws_s3_bucket_policy.state.policy).Statement[0].Condition.Bool["aws:SecureTransport"] == "false" &&
      aws_s3_bucket_lifecycle_configuration.plans.rule[0].filter[0].prefix == "plans/"
    )
    error_message = "Remote state must remain private, encrypted, versioned and TLS-only; expiration must target release plans only."
  }
  assert {
    condition = alltrue([for key, role in aws_iam_role.delivery :
      jsondecode(role.assume_role_policy).Statement[0].Action == "sts:AssumeRoleWithWebIdentity" &&
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com" &&
      jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example@1/labpass@2:environment:labpass-${key}" &&
      !can(jsondecode(role.assume_role_policy).Statement[0].Condition.StringLike)
    ])
    error_message = "Each OIDC role must trust only its exact repository identity, audience and protected environment."
  }
  assert {
    condition = (
      toset(jsondecode(aws_iam_role_policy.publish.policy).Statement[1].Resource) == toset(local.ecr_arns) &&
      !contains(jsondecode(aws_iam_role_policy.publish.policy).Statement[1].Action, "ecr:BatchDeleteImage") &&
      jsondecode(aws_iam_role_policy.state["plan"].policy).Statement[1].Action == ["s3:GetObject"] &&
      jsondecode(aws_iam_role_policy.state["apply"].policy).Statement[1].Action == ["s3:GetObject", "s3:PutObject"] &&
      jsondecode(aws_iam_role_policy.state["apply"].policy).Statement[3].Action == ["s3:GetObjectVersion"] &&
      alltrue([for policy in aws_iam_role_policy.metadata :
        jsondecode(policy.policy).Statement[2].Effect == "Deny" &&
        contains(jsondecode(policy.policy).Statement[2].Action, "secretsmanager:GetSecretValue")
      ])
    )
    error_message = "Publishing, planning and applying must retain separate image, state and secret-value permissions."
  }
  assert {
    condition = alltrue([for policy in aws_iam_role_policy.metadata :
      alltrue([for action in ["ec2:GetManagedPrefixListEntries", "ec2:GetInstanceUefiData", "ses:ListTagsForResource"] :
        contains(jsondecode(policy.policy).Statement[0].Action, action)
      ])
    ])
    error_message = "Plan and apply must read managed prefix-list entries, AMI UEFI data and SES tags during foundation refresh."
  }
  assert {
    condition = alltrue([for policy in aws_iam_role_policy.metadata :
      jsondecode(policy.policy).Statement[1].Resource == local.frontend_arn &&
      alltrue([for action in [
        "s3:ListBucket", "s3:GetBucketAcl", "s3:GetBucketCORS", "s3:GetBucketLogging",
        "s3:GetBucketOwnershipControls", "s3:GetBucketPolicy", "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketRequestPayment", "s3:GetBucketVersioning", "s3:GetBucketWebsite",
        "s3:GetBucketObjectLockConfiguration", "s3:GetEncryptionConfiguration",
        "s3:GetAccelerateConfiguration", "s3:GetLifecycleConfiguration", "s3:GetReplicationConfiguration"
        ] : anytrue([for allowed in jsondecode(policy.policy).Statement[1].Action :
          action == allowed || (endswith(allowed, "*") && startswith(action, trimsuffix(allowed, "*")))
      ])]) &&
      !contains(jsondecode(policy.policy).Statement[1].Action, "s3:GetObject") &&
      !contains(jsondecode(policy.policy).Statement[1].Action, "s3:*")
    ])
    error_message = "Both delivery roles must refresh S3 bucket settings with the actual IAM action names, scoped to the frontend bucket without object reads or S3 administration."
  }
  assert {
    condition = (
      !strcontains(aws_iam_role_policy.release.policy, "ssm:SendCommand") &&
      !strcontains(aws_iam_role_policy.release.policy, "ec2:CreateLaunchTemplateVersion") &&
      !strcontains(aws_iam_role_policy.release.policy, "ec2:RunInstances") &&
      !strcontains(aws_iam_role_policy.release.policy, "ec2:CreateTags") &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[2].Condition.StringEquals["iam:PassedToService"] == "lambda.amazonaws.com" &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[2].Resource == "arn:aws:iam::123456789012:role/labpass-demo-consumer" &&
      jsondecode(aws_ssm_document.migrate.content).parameters.ImageDigest.allowedPattern == "^sha256:[0-9a-f]{64}$" &&
      contains(jsondecode(aws_ssm_document.migrate.content).mainSteps[0].inputs.runCommand, "test -f /etc/labpass/migration/runtime.env") &&
      contains(jsondecode(aws_ssm_document.migrate.content).mainSteps[0].inputs.runCommand, "flock -n 9")
    )
    error_message = "Operator command and launch-template writes require exact IDs; migration input must be a validated digest."
  }
}

run "scoped_existing_runtime_updates" {
  command = apply
  variables {
    runtime_launch_template_ids = {
      api       = "lt-00000000000000001", relay = "lt-00000000000000002"
      bootstrap = "lt-00000000000000003", migration = "lt-00000000000000004"
    }
    migration_instance_id = "i-00000000000000001"
  }
  assert {
    condition = (
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[5].Resource) == toset([for id in var.runtime_launch_template_ids : "arn:aws:ec2:us-east-1:123456789012:launch-template/${id}"]) &&
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[6].Resource) == toset([
        aws_ssm_document.migrate.arn, "arn:aws:ec2:us-east-1:123456789012:instance/i-00000000000000001"
      ]) &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[6].Action == ["ssm:SendCommand"]
    )
    error_message = "Delivery must not modify other launch templates or run arbitrary commands on other hosts."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.release.policy).Statement[7].Action == ["ec2:RunInstances"] &&
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[7].Condition.ArnEquals["ec2:LaunchTemplate"]) == toset([
        "arn:aws:ec2:us-east-1:123456789012:launch-template/lt-00000000000000001",
        "arn:aws:ec2:us-east-1:123456789012:launch-template/lt-00000000000000002",
      ]) &&
      !contains(jsondecode(aws_iam_role_policy.release.policy).Statement[7].Resource, "*") &&
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[8].Resource) == toset([
        "arn:aws:iam::123456789012:role/labpass-demo-api",
        "arn:aws:iam::123456789012:role/labpass-demo-relay",
      ]) &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[8].Action == ["iam:PassRole"] &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[8].Condition.StringEquals["iam:PassedToService"] == "ec2.amazonaws.com"
    )
    error_message = "Auto Scaling launch validation must require an API/relay template and pass only the two fleet roles to EC2."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.release.policy).Statement[9].Action == ["ec2:CreateTags"] &&
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[9].Resource) == toset([
        "arn:aws:ec2:us-east-1:123456789012:instance/*",
        "arn:aws:ec2:us-east-1:123456789012:volume/*",
      ]) &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[9].Condition.StringEquals["ec2:CreateAction"] == "RunInstances" &&
      jsondecode(aws_iam_role_policy.release.policy).Statement[9].Condition.StringEquals["aws:RequestTag/Project"] == "LabPass" &&
      toset(jsondecode(aws_iam_role_policy.release.policy).Statement[9].Condition.StringEquals["aws:RequestTag/Component"]) == toset(["api", "relay"])
    )
    error_message = "Tagging must be limited to instance/volume creation with the LabPass API/relay tags."
  }
}

run "existing_provider_and_legacy_subject" {
  command = apply
  variables {
    oidc_subject_format        = "legacy"
    existing_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  }
  assert {
    condition = (
      length(aws_iam_openid_connect_provider.github) == 0 &&
      output.delivery.oidc_subjects.apply == "repo:example/labpass:environment:labpass-apply"
    )
    error_message = "Existing account OIDC providers and explicit legacy subjects must be supported without duplicate provider creation."
  }
}

run "reject_wildcard_repository" {
  command = plan
  variables { github_repository = "example/*" }
  expect_failures = [var.github_repository]
}
run "reject_cross_account_provider" {
  command = plan
  variables { existing_oidc_provider_arn = "arn:aws:iam::000000000000:oidc-provider/token.actions.githubusercontent.com" }
  expect_failures = [var.existing_oidc_provider_arn]
}
run "reject_incomplete_template_scope" {
  command = plan
  variables { runtime_launch_template_ids = { api = "lt-00000000000000001" } }
  expect_failures = [var.runtime_launch_template_ids]
}
run "reject_invalid_instance" {
  command = plan
  variables { migration_instance_id = "*" }
  expect_failures = [var.migration_instance_id]
}

run "public_zone_and_registrar_outputs" {
  command = apply
  variables { public_domain_name = "labpass.example.com" }

  assert {
    condition = (
      length(aws_route53_zone.public) == 1 &&
      aws_route53_zone.public[0].name == "labpass.example.com" &&
      length(aws_route53_zone.public[0].vpc) == 0 &&
      !aws_route53_zone.public[0].force_destroy &&
      output.public_dns.hosted_zone_id == aws_route53_zone.public[0].zone_id &&
      output.public_dns.domain_name == "labpass.example.com" &&
      toset(output.public_dns.name_servers) == toset([
        "ns-1.example.net", "ns-2.example.net", "ns-3.example.net", "ns-4.example.net"
      ])
    )
    error_message = "DNS must use a public zone, preserve populated zones on deletion and expose delegation details."
  }
}

run "reject_wildcard_zone" {
  command = plan
  variables { public_domain_name = "*.example.com" }
  expect_failures = [var.public_domain_name]
}
