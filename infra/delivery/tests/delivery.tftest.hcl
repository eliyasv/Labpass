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
    condition = (
      !strcontains(aws_iam_role_policy.release.policy, "ssm:SendCommand") &&
      !strcontains(aws_iam_role_policy.release.policy, "ec2:CreateLaunchTemplateVersion") &&
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
