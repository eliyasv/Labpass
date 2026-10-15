data "aws_route53_zone" "site" {
  count        = local.frontend_enabled ? 1 : 0
  zone_id      = var.frontend.hosted_zone_id
  private_zone = false

  lifecycle {
    postcondition {
      condition = !self.private_zone && alltrue([for name in [var.frontend.domain_name, var.frontend.origin_domain_name] :
        name == trimsuffix(self.name, ".") || endswith(name, ".${trimsuffix(self.name, ".")}")
      ])
      error_message = "Both names must belong to the selected public hosted zone. Registrar delegation must make that zone authoritative."
    }
  }
}

locals {
  site_domains = local.frontend_enabled ? {
    viewer = var.frontend.domain_name
    origin = var.frontend.origin_domain_name
  } : {}
}

# Both certificates use us-east-1: required for CloudFront and the ALB region.
resource "aws_acm_certificate" "site" {
  for_each          = local.site_domains
  domain_name       = each.value
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "certificate" {
  for_each = local.site_domains
  zone_id  = data.aws_route53_zone.site[0].zone_id
  name     = one(aws_acm_certificate.site[each.key].domain_validation_options).resource_record_name
  type     = one(aws_acm_certificate.site[each.key].domain_validation_options).resource_record_type
  records  = [one(aws_acm_certificate.site[each.key].domain_validation_options).resource_record_value]
  ttl      = 60
}

resource "aws_acm_certificate_validation" "site" {
  for_each                = local.site_domains
  certificate_arn         = aws_acm_certificate.site[each.key].arn
  validation_record_fqdns = [aws_route53_record.certificate[each.key].fqdn]
}

resource "aws_route53_record" "origin" {
  count   = local.frontend_enabled ? 1 : 0
  zone_id = data.aws_route53_zone.site[0].zone_id
  name    = var.frontend.origin_domain_name
  type    = "A"

  alias {
    name                   = aws_lb.api[0].dns_name
    zone_id                = aws_lb.api[0].zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "site" {
  for_each = local.frontend_enabled ? toset(["A", "AAAA"]) : toset([])
  zone_id  = data.aws_route53_zone.site[0].zone_id
  name     = var.frontend.domain_name
  type     = each.key

  alias {
    name                   = aws_cloudfront_distribution.site[0].domain_name
    zone_id                = aws_cloudfront_distribution.site[0].hosted_zone_id
    evaluate_target_health = false
  }
}
