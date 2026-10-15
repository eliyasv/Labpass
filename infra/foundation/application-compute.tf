data "aws_ami" "application" {
  count  = local.hosting_enabled ? 1 : 0
  owners = ["amazon"]

  filter {
    name   = "image-id"
    values = [var.application.ami_id]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-x86_64"]
  }
  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  application_image = local.hosting_enabled ? "${aws_ecr_repository.application["api"].repository_url}@${var.application.image_digest}" : null
  runtime_environment = { for component in local.hosting_roles : component => merge({
    AWS_REGION            = var.aws_region
    LABPASS_AWS_ENABLED   = "true"
    LABPASS_DB_HOST       = aws_db_instance.main.address
    LABPASS_DB_NAME       = aws_db_instance.main.db_name
    LABPASS_DB_PORT       = tostring(aws_db_instance.main.port)
    LABPASS_DB_CA_FILE    = "/app/certs/rds-global-bundle.pem"
    LABPASS_DB_SECRET_ARN = component == "bootstrap" ? aws_db_instance.main.master_user_secret[0].secret_arn : aws_secretsmanager_secret.database[component].arn
    }, component == "api" ? {
    APP_ORIGIN            = var.application.public_origin
    LABPASS_COOKIE_SECURE = "true"
    } : {}, component == "relay" ? {
    LABPASS_QUEUE_ARN = aws_sqs_queue.confirmations.arn
    } : {}, component == "bootstrap" ? {
    LABPASS_API_SECRET_ARN       = aws_secretsmanager_secret.database["api"].arn
    LABPASS_RELAY_SECRET_ARN     = aws_secretsmanager_secret.database["relay"].arn
    LABPASS_CONSUMER_SECRET_ARN  = aws_secretsmanager_secret.database["consumer"].arn
    LABPASS_MIGRATION_SECRET_ARN = aws_secretsmanager_secret.database["migration"].arn
  } : {}) }

  application_user_data = { for component in local.hosting_roles : component => templatefile("${path.module}/templates/user-data.sh.tftpl", {
    component          = component
    environment_base64 = base64encode(join("\n", concat([for key in sort(keys(local.runtime_environment[component])) : "${key}=${local.runtime_environment[component][key]}"], [""])))
    image              = local.application_image
    region             = var.aws_region
    log_group          = aws_cloudwatch_log_group.runtime[component].name
    service_script     = file("${path.module}/templates/labpass-service.sh")
    service_unit       = file("${path.module}/templates/labpass@.service")
  }) }
}

resource "aws_launch_template" "runtime" {
  for_each      = local.hosting_roles
  name          = "${var.name_prefix}-${each.key}"
  image_id      = data.aws_ami.application[0].id
  instance_type = "t3.micro"
  user_data     = base64encode(local.application_user_data[each.key])

  iam_instance_profile {
    name = aws_iam_instance_profile.runtime[each.key].name
  }

  network_interfaces {
    device_index                = 0
    associate_public_ip_address = false
    delete_on_termination       = true
    security_groups             = [aws_security_group.database_client[each.key].id]
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
    instance_metadata_tags      = "disabled"
  }

  credit_specification {
    cpu_credits = "standard"
  }

  block_device_mappings {
    device_name = data.aws_ami.application[0].root_device_name
    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${var.name_prefix}-${each.key}"
      Project     = "LabPass"
      Environment = "demo"
      ManagedBy   = "Terraform"
      Component   = each.key
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Project     = "LabPass"
      Environment = "demo"
      ManagedBy   = "Terraform"
      Component   = each.key
    }
  }

  lifecycle {
    precondition {
      condition     = length(local.application_user_data[each.key]) <= 16384
      error_message = "EC2 user data must fit the 16 KiB raw payload limit."
    }
  }

  depends_on = [
    aws_iam_role_policy.container_runtime,
    aws_iam_role_policy_attachment.ssm,
    aws_iam_role_policy.database_secret,
    aws_iam_role_policy.bootstrap_secrets,
    aws_iam_role_policy.queue,
    aws_route.application_egress,
    aws_vpc_endpoint.s3,
  ]
}

resource "aws_autoscaling_group" "api" {
  count                     = local.hosting_enabled ? 1 : 0
  name                      = "${var.name_prefix}-api"
  min_size                  = var.application.api_desired_capacity == 0 ? 0 : 2
  max_size                  = 4
  desired_capacity          = var.application.api_desired_capacity
  vpc_zone_identifier       = [for subnet in aws_subnet.application : subnet.id]
  target_group_arns         = [aws_lb_target_group.api[0].arn]
  health_check_type         = "ELB"
  health_check_grace_period = 600
  default_instance_warmup   = 120
  wait_for_capacity_timeout = "15m"
  min_elb_capacity          = var.application.api_desired_capacity == 0 ? 0 : 2

  launch_template {
    id      = aws_launch_template.runtime["api"].id
    version = tostring(aws_launch_template.runtime["api"].latest_version)
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 100
      max_healthy_percentage = 150
      instance_warmup        = 120
    }
  }

  depends_on = [aws_lb_listener_rule.api]
}

resource "aws_autoscaling_group" "relay" {
  count                     = local.hosting_enabled ? 1 : 0
  name                      = "${var.name_prefix}-relay"
  min_size                  = var.application.relay_desired_capacity == 0 ? 0 : 1
  max_size                  = 2
  desired_capacity          = var.application.relay_desired_capacity
  vpc_zone_identifier       = [for subnet in aws_subnet.application : subnet.id]
  health_check_type         = "EC2"
  health_check_grace_period = 300
  default_instance_warmup   = 120
  wait_for_capacity_timeout = "10m"

  launch_template {
    id      = aws_launch_template.runtime["relay"].id
    version = tostring(aws_launch_template.runtime["relay"].latest_version)
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 100
      max_healthy_percentage = 200
      instance_warmup        = 120
    }
  }
}
