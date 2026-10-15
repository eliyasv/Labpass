output "application_hosting" {
  description = "ALB, groups and launch templates; operator templates do not launch hosts automatically."
  value = local.hosting_enabled ? {
    alb_dns_name     = aws_lb.api[0].dns_name
    alb_zone_id      = aws_lb.api[0].zone_id
    api_target_group = aws_lb_target_group.api[0].arn
    api_asg_name     = aws_autoscaling_group.api[0].name
    relay_asg_name   = aws_autoscaling_group.relay[0].name
    launch_templates = {
      for name, template in aws_launch_template.runtime : name => {
        id      = template.id
        version = template.latest_version
      }
    }
    log_groups = { for name, group in aws_cloudwatch_log_group.runtime : name => group.name }
  } : null
}

output "alb_origin" {
  description = "ALB DNS name and canonical hosted zone ID, available after origin listener rules are configured."
  value = local.hosting_enabled ? {
    dns_name = aws_lb.api[0].dns_name
    zone_id  = aws_lb.api[0].zone_id
  } : null
  depends_on = [aws_lb_listener_rule.api]
}

output "listener_certificate_arn" {
  description = "Certificate ARN used by the HTTPS listener; null when hosting is disabled."
  value       = local.hosting_enabled ? aws_lb_listener.api_https[0].certificate_arn : null
}
