# Fictional metadata only. Every resource uses the mock provider.
mock_provider "aws" {
  source = "./tests/fixtures/common"
}

variables {
  aws_account_id      = "123456789012"
  origin_verify_token = "0000000000000000000000000000000000000000000000000000000000000000"
  application = {
    ami_id                 = "ami-00000000000000001"
    image_digest           = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    public_origin          = "https://labpass.example.test"
    api_desired_capacity   = 2
    relay_desired_capacity = 1
  }

  vpc_id                 = "vpc-00000000000000001"
  public_subnet_ids      = ["subnet-00000000000000003", "subnet-00000000000000004"]
  application_subnet_ids = ["subnet-00000000000000005", "subnet-00000000000000006"]
  database = {
    host              = "mock.example.us-east-1.rds.amazonaws.com"
    port              = 5432
    name              = "labpass"
    master_secret_arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-mock-AbCd12"
    secret_arns = {
      api       = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-api-AbCd12"
      relay     = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-relay-AbCd12"
      consumer  = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-consumer-AbCd12"
      migration = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-migration-AbCd12"
    }
  }
  runtime_roles = {
    api = {
      id   = "labpass-demo-api"
      name = "labpass-demo-api"
    }
    relay = {
      id   = "labpass-demo-relay"
      name = "labpass-demo-relay"
    }
    bootstrap = {
      id   = "labpass-demo-bootstrap"
      name = "labpass-demo-bootstrap"
    }
    migration = {
      id   = "labpass-demo-migration"
      name = "labpass-demo-migration"
    }
  }
  instance_profiles = {
    api       = "labpass-demo-api"
    relay     = "labpass-demo-relay"
    bootstrap = "labpass-demo-bootstrap"
    migration = "labpass-demo-migration"
  }
  client_security_group_ids = {
    api       = "sg-00000000000000001"
    relay     = "sg-00000000000000002"
    bootstrap = "sg-00000000000000004"
    migration = "sg-00000000000000005"
  }
  api_repository = {
    repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/api"
    arn            = "arn:aws:ecr:us-east-1:123456789012:repository/labpass-demo/api"
  }
  queue_arn                = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations"
  listener_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000001"
}

override_resource {
  target = aws_launch_template.runtime["api"]
  values = { id = "lt-00000000000000001", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["relay"]
  values = { id = "lt-00000000000000002", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["bootstrap"]
  values = { id = "lt-00000000000000003", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["migration"]
  values = { id = "lt-00000000000000004", latest_version = 3 }
}

run "hosting_disabled" {
  module { source = "../modules/application" }
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
  module { source = "../modules/application" }
  command = apply

  assert {
    condition = (
      length(aws_launch_template.runtime) == 4 &&
      alltrue([for name, template in aws_launch_template.runtime :
        template.iam_instance_profile[0].name == var.instance_profiles[name] &&
        template.key_name == null &&
        template.metadata_options[0].http_tokens == "required" &&
        template.metadata_options[0].http_put_response_hop_limit == 2 &&
        template.network_interfaces[0].associate_public_ip_address == "false" &&
        toset(template.network_interfaces[0].security_groups) == toset([var.client_security_group_ids[name]]) &&
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
      aws_lb_listener.api_https[0].certificate_arn == var.listener_certificate_arn &&
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
      toset(aws_autoscaling_group.api[0].vpc_zone_identifier) == toset(var.application_subnet_ids) &&
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
      jsondecode(policy.policy).Statement[1].Resource == var.api_repository.arn &&
      toset(jsondecode(policy.policy).Statement[2].Resource) == toset([aws_cloudwatch_log_group.runtime[name].arn, "${aws_cloudwatch_log_group.runtime[name].arn}:*"])
    ])
    error_message = "ECR pulls and log writes must be scoped to the application repository and component log group."
  }

  assert {
    condition = (
      local.runtime_environment["api"].LABPASS_DB_SECRET_ARN == var.database.secret_arns["api"] &&
      local.runtime_environment["relay"].LABPASS_DB_SECRET_ARN == var.database.secret_arns["relay"] &&
      local.runtime_environment["bootstrap"].LABPASS_DB_SECRET_ARN == var.database.master_secret_arn &&
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
  module { source = "../modules/application" }
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
  module { source = "../modules/application" }
  command = plan
  variables {
    application = merge(var.application, { image_digest = "latest" })
  }
  expect_failures = [var.application]
}

run "reject_insecure_public_origin" {
  module { source = "../modules/application" }
  command = plan
  variables {
    application = merge(var.application, { public_origin = "http://labpass.example.test" })
  }
  expect_failures = [var.application]
}

run "reject_cross_account_certificate" {
  command = plan
  variables {
    frontend    = null
    application = merge(var.application, { origin_certificate_arn = "arn:aws:acm:us-east-1:999999999999:certificate/00000000-0000-0000-0000-000000000001" })
  }
  expect_failures = [var.application]
}

run "reject_single_api_instance" {
  module { source = "../modules/application" }
  command = plan
  variables {
    application = merge(var.application, { api_desired_capacity = 1 })
  }
  expect_failures = [var.application]
}

run "reject_missing_listener_certificate" {
  module { source = "../modules/application" }
  command = plan
  variables { listener_certificate_arn = null }
  expect_failures = [aws_lb_listener.api_https[0]]
}

run "reject_cross_account_listener_certificate" {
  module { source = "../modules/application" }
  command = plan
  variables { listener_certificate_arn = "arn:aws:acm:us-east-1:999999999999:certificate/00000000-0000-0000-0000-000000000001" }
  expect_failures = [aws_lb_listener.api_https[0]]
}
