# Fictional metadata only. Every resource uses the mock provider.
mock_provider "aws" {
  source = "./tests/fixtures/hosting"
}

variables {
  aws_account_id      = "123456789012"
  origin_verify_token = "0000000000000000000000000000000000000000000000000000000000000000"
  application = {
    ami_id                 = "ami-00000000000000001"
    image_digest           = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    public_origin          = "https://labpass.example.test"
    origin_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000001"
    api_desired_capacity   = 2
    relay_desired_capacity = 1
  }
}

run "hosting_disabled" {
  command = plan
  variables {
    application = null
  }
  assert {
    condition = (
      length(aws_launch_template.runtime) == 0 &&
      length(aws_lb.api) == 0 &&
      length(aws_autoscaling_group.api) == 0 &&
      output.application_hosting == null
    )
    error_message = "Hosting must remain disabled without explicit configuration."
  }
}

run "private_application_hosting" {
  command = apply

  assert {
    condition = (
      length(aws_launch_template.runtime) == 4 &&
      alltrue([for name, template in aws_launch_template.runtime :
        template.iam_instance_profile[0].name == aws_iam_instance_profile.runtime[name].name &&
        template.key_name == null &&
        template.metadata_options[0].http_tokens == "required" &&
        template.metadata_options[0].http_put_response_hop_limit == 2 &&
        template.network_interfaces[0].associate_public_ip_address == "false" &&
        toset(template.network_interfaces[0].security_groups) == toset([aws_security_group.database_client[name].id]) &&
        template.block_device_mappings[0].ebs[0].encrypted == "true" &&
        template.credit_specification[0].cpu_credits == "standard"
      ])
    )
    error_message = "Templates must preserve component roles, private networking, IMDSv2 and encrypted storage."
  }

  assert {
    condition = (
      aws_lb_listener.api_https[0].port == 443 &&
      aws_lb_listener.api_https[0].protocol == "HTTPS" &&
      aws_lb_listener.api_https[0].certificate_arn == var.application.origin_certificate_arn &&
      one([for condition in aws_lb_listener_rule.api[0].condition : condition.http_header[0] if length(condition.http_header) == 1]).values == toset([var.origin_verify_token]) &&
      aws_vpc_security_group_ingress_rule.cloudfront_https[0].prefix_list_id == data.aws_ec2_managed_prefix_list.cloudfront[0].id &&
      aws_vpc_security_group_ingress_rule.cloudfront_https[0].cidr_ipv4 == null &&
      aws_vpc_security_group_ingress_rule.api_alb[0].referenced_security_group_id == aws_security_group.alb[0].id &&
      aws_lb_target_group.api[0].health_check[0].path == "/api/health/ready"
    )
    error_message = "HTTPS must originate from CloudFront addresses; only the ALB reaches the API port."
  }

  assert {
    condition = (
      toset(aws_autoscaling_group.api[0].vpc_zone_identifier) == toset([for subnet in aws_subnet.application : subnet.id]) &&
      aws_autoscaling_group.api[0].desired_capacity == 2 &&
      aws_autoscaling_group.api[0].health_check_type == "ELB" &&
      aws_autoscaling_group.api[0].launch_template[0].version == "3" &&
      aws_autoscaling_group.api[0].launch_template[0].id == aws_launch_template.runtime["api"].id &&
      aws_autoscaling_group.relay[0].launch_template[0].version == "3" &&
      aws_autoscaling_group.relay[0].launch_template[0].id == aws_launch_template.runtime["relay"].id &&
      aws_launch_template.runtime["api"].id != aws_launch_template.runtime["relay"].id &&
      aws_autoscaling_group.relay[0].desired_capacity == 1 &&
      length(aws_autoscaling_group.relay[0].target_group_arns) == 0
    )
    error_message = "API and relay must have separate private fleets and numeric template versions."
  }

  assert {
    condition = alltrue([for name, policy in aws_iam_role_policy.container_runtime :
      jsondecode(policy.policy).Statement[0].Resource == "*" &&
      jsondecode(policy.policy).Statement[0].Action == ["ecr:GetAuthorizationToken"] &&
      jsondecode(policy.policy).Statement[1].Resource == aws_ecr_repository.application["api"].arn &&
      toset(jsondecode(policy.policy).Statement[2].Resource) == toset([aws_cloudwatch_log_group.runtime[name].arn, "${aws_cloudwatch_log_group.runtime[name].arn}:*"])
    ])
    error_message = "ECR pulls and log writes must be scoped to the application repository and component log group."
  }

  assert {
    condition = (
      local.runtime_environment["api"].LABPASS_DB_SECRET_ARN == aws_secretsmanager_secret.database["api"].arn &&
      local.runtime_environment["relay"].LABPASS_DB_SECRET_ARN == aws_secretsmanager_secret.database["relay"].arn &&
      local.runtime_environment["bootstrap"].LABPASS_DB_SECRET_ARN == aws_db_instance.main.master_user_secret[0].secret_arn &&
      !contains(keys(local.runtime_environment["relay"]), "LABPASS_SES_FROM") &&
      alltrue([for environment in local.runtime_environment : !contains(keys(environment), "DATABASE_URL")]) &&
      alltrue([for name, template in aws_launch_template.runtime :
        strcontains(base64decode(template.user_data), "@${var.application.image_digest}") &&
        !strcontains(base64decode(template.user_data), "alembic upgrade") &&
        length(base64decode(template.user_data)) <= 16384
      ])
    )
    error_message = "User data must use digests and role-specific ARNs without inline credentials or automatic migrations."
  }
}

run "zero_capacity_before_database_setup" {
  command = plan
  variables {
    application = merge(var.application, { api_desired_capacity = 0, relay_desired_capacity = 0 })
  }
  assert {
    condition = (
      aws_autoscaling_group.api[0].min_size == 0 &&
      aws_autoscaling_group.api[0].desired_capacity == 0 &&
      aws_autoscaling_group.relay[0].desired_capacity == 0
    )
    error_message = "Bootstrap must be possible before starting API or relay instances."
  }
}

run "reject_mutable_image" {
  command = plan
  variables {
    application = merge(var.application, { image_digest = "latest" })
  }
  expect_failures = [var.application]
}

run "reject_insecure_public_origin" {
  command = plan
  variables {
    application = merge(var.application, { public_origin = "http://labpass.example.test" })
  }
  expect_failures = [var.application]
}

run "reject_cross_account_certificate" {
  command = plan
  variables {
    application = merge(var.application, { origin_certificate_arn = "arn:aws:acm:us-east-1:999999999999:certificate/00000000-0000-0000-0000-000000000001" })
  }
  expect_failures = [var.application]
}

run "reject_single_api_instance" {
  command = plan
  variables {
    application = merge(var.application, { api_desired_capacity = 1 })
  }
  expect_failures = [var.application]
}
