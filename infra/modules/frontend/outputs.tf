output "frontend_delivery" {
  description = "Frontend URL, publication bucket, distribution and origin DNS; null when disabled."
  value = local.frontend_enabled ? {
    url                    = "https://${var.frontend.domain_name}"
    bucket_name            = aws_s3_bucket.frontend[0].id
    distribution_id        = aws_cloudfront_distribution.site[0].id
    distribution_domain    = aws_cloudfront_distribution.site[0].domain_name
    origin_domain          = aws_route53_record.origin[0].fqdn
    viewer_certificate_arn = aws_acm_certificate_validation.site["viewer"].certificate_arn
    origin_certificate_arn = aws_acm_certificate_validation.site["origin"].certificate_arn
  } : null
}

output "certificates" {
  description = "DNS-validated ACM certificate ARNs keyed by viewer and origin; empty when frontend delivery is disabled."
  value       = { for name, certificate in aws_acm_certificate_validation.site : name => certificate.certificate_arn }
}
