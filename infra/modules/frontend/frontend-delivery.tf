locals {
  # AWS managed CachingDisabled and AllViewerExceptHostHeader policies.
  api_cache_policy_id   = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  api_request_policy_id = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
}

# Hashed Vite assets can cache for a year without mixing cookies or query strings.
resource "aws_cloudfront_cache_policy" "static" {
  for_each    = local.frontend_enabled ? toset(["assets"]) : toset([])
  name        = "${var.name_prefix}-${each.key}"
  min_ttl     = 0
  default_ttl = 31536000
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Apply browser security headers consistently; HTML revalidates and API data is no-store.
resource "aws_cloudfront_response_headers_policy" "site" {
  for_each = local.frontend_enabled ? toset(["shell", "assets", "api"]) : toset([])
  name     = "${var.name_prefix}-${each.key}"

  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
      override                = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "same-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = false
      preload                    = false
      override                   = true
    }
  }

  dynamic "custom_headers_config" {
    for_each = each.key == "assets" ? [] : [each.key == "api" ? "no-store" : "no-cache"]
    content {
      items {
        header   = "Cache-Control"
        value    = custom_headers_config.value
        override = true
      }
    }
  }
}

resource "aws_cloudfront_distribution" "site" {
  count               = local.frontend_enabled ? 1 : 0
  enabled             = true
  is_ipv6_enabled     = true
  aliases             = [var.frontend.domain_name]
  default_root_object = "index.html"
  http_version        = "http2and3"
  price_class         = "PriceClass_100"
  wait_for_deployment = true

  # Frontend requests are signed with OAC; the bucket policy admits this distribution.
  origin {
    origin_id                = "frontend"
    domain_name              = aws_s3_bucket.frontend[0].bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend[0].id
  }

  # The HTTPS ALB origin checks the injected header in addition to CloudFront source IPs.
  origin {
    origin_id           = "api"
    domain_name         = trimsuffix(aws_route53_record.origin[0].fqdn, ".")
    connection_attempts = 1
    connection_timeout  = 5

    custom_header {
      name  = "X-LabPass-Origin"
      value = var.origin_verify_token
    }
    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "https-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 30
      origin_keepalive_timeout = 5
    }
  }

  # Fetch the current HTML entry point; only the explicit /assets/* rule caches content.
  default_cache_behavior {
    target_origin_id           = "frontend"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = local.api_cache_policy_id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site["shell"].id
    compress                   = true
  }

  # Forward API methods/cookies/query strings without caching or SPA error fallbacks.
  dynamic "ordered_cache_behavior" {
    for_each = ["/api", "/api/*"]
    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "api"
      allowed_methods            = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
      cached_methods             = ["GET", "HEAD"]
      viewer_protocol_policy     = "https-only"
      cache_policy_id            = local.api_cache_policy_id
      origin_request_policy_id   = local.api_request_policy_id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.site["api"].id
      compress                   = true
    }
  }

  ordered_cache_behavior {
    path_pattern               = "/assets/*"
    target_origin_id           = "frontend"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    viewer_protocol_policy     = "redirect-to-https"
    cache_policy_id            = aws_cloudfront_cache_policy.static["assets"].id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site["assets"].id
    compress                   = true
  }

  # Preserve origin error bodies/statuses, including API authorization and outages.
  dynamic "custom_error_response" {
    for_each = toset([400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site["viewer"].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

}
