locals {
  hosting_enabled = var.application != null
  hosting_roles   = local.hosting_enabled ? toset(["api", "relay", "bootstrap", "migration"]) : toset([])
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = local.hosting_enabled ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  count       = local.hosting_enabled ? 1 : 0
  name        = "${var.name_prefix}-alb"
  description = "HTTPS from CloudFront origin-facing addresses"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "cloudfront_https" {
  count             = local.hosting_enabled ? 1 : 0
  security_group_id = aws_security_group.alb[0].id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront[0].id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "alb_api" {
  count                        = local.hosting_enabled ? 1 : 0
  security_group_id            = aws_security_group.alb[0].id
  referenced_security_group_id = var.client_security_group_ids["api"]
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "api_alb" {
  count                        = local.hosting_enabled ? 1 : 0
  security_group_id            = var.client_security_group_ids["api"]
  referenced_security_group_id = aws_security_group.alb[0].id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_lb" "api" {
  count                      = local.hosting_enabled ? 1 : 0
  name                       = substr("${var.name_prefix}-alb", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = var.public_subnet_ids
  security_groups            = [aws_security_group.alb[0].id]
  drop_invalid_header_fields = true
  desync_mitigation_mode     = "strictest"
}

resource "aws_lb_target_group" "api" {
  count                = local.hosting_enabled ? 1 : 0
  name                 = substr("${var.name_prefix}-api", 0, 32)
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "instance"
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    path                = "/api/health/ready"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "api_https" {
  count             = local.hosting_enabled ? 1 : 0
  load_balancer_arn = aws_lb.api[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.listener_certificate_arn

  lifecycle {
    precondition {
      condition     = can(regex("^arn:aws:acm:${var.aws_region}:${var.aws_account_id}:certificate/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.listener_certificate_arn))
      error_message = "Enabled hosting requires a listener certificate in the configured account and region."
    }
  }

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      status_code  = "404"
      message_body = "Not found"
    }
  }
}

resource "aws_lb_listener_rule" "api" {
  count        = local.hosting_enabled ? 1 : 0
  listener_arn = aws_lb_listener.api_https[0].arn
  priority     = 100

  condition {
    path_pattern {
      values = ["/api", "/api/*"]
    }
  }

  condition {
    http_header {
      http_header_name = "X-LabPass-Origin"
      values           = concat([var.origin_verify_token], var.origin_verify_previous_token == null ? [] : [var.origin_verify_previous_token])
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}
