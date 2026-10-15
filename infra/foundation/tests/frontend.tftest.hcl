mock_provider "aws" {
  source = "./tests/fixtures/common"

  mock_resource "aws_s3_bucket" {
    defaults = {
      id                          = "labpass-demo-123456789012-frontend"
      arn                         = "arn:aws:s3:::labpass-demo-123456789012-frontend"
      bucket_regional_domain_name = "labpass-demo-123456789012-frontend.s3.us-east-1.amazonaws.com"
    }
  }
  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      id             = "E0000000000001"
      arn            = "arn:aws:cloudfront::123456789012:distribution/E0000000000001"
      domain_name    = "d0000000000001.cloudfront.net"
      hosted_zone_id = "Z2FDTNDATAQYW2"
    }
  }
  mock_resource "aws_cloudfront_cache_policy" {
    defaults = { id = "00000000-0000-0000-0000-000000000003" }
  }
}

override_resource {
  target = aws_cloudfront_response_headers_policy.site["api"]
  values = { id = "00000000-0000-0000-0000-000000000004" }
}
override_resource {
  target = aws_cloudfront_response_headers_policy.site["shell"]
  values = { id = "00000000-0000-0000-0000-000000000005" }
}
override_resource {
  target = aws_cloudfront_response_headers_policy.site["assets"]
  values = { id = "00000000-0000-0000-0000-000000000006" }
}

override_data {
  target = data.aws_route53_zone.site[0]
  values = { name = "example.test.", private_zone = false }
}

override_resource {
  target = aws_route53_record.origin[0]
  values = { fqdn = "origin.labpass.example.test." }
}
override_resource {
  target = aws_acm_certificate.site["viewer"]
  values = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000001"
    domain_validation_options = [{
      domain_name           = "labpass.example.test"
      resource_record_name  = "_viewer.labpass.example.test."
      resource_record_type  = "CNAME"
      resource_record_value = "_viewer.acm-validations.aws."
    }]
  }
}
override_resource {
  target = aws_acm_certificate.site["origin"]
  values = {
    arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000002"
    domain_validation_options = [{
      domain_name           = "origin.labpass.example.test"
      resource_record_name  = "_origin.labpass.example.test."
      resource_record_type  = "CNAME"
      resource_record_value = "_origin.acm-validations.aws."
    }]
  }
}

variables {
  aws_account_id      = "123456789012"
  origin_verify_token = "0000000000000000000000000000000000000000000000000000000000000000"
  application = {
    ami_id        = "ami-00000000000000001"
    image_digest  = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    public_origin = "https://labpass.example.test"
  }
  frontend = {
    hosted_zone_id     = "Z00000000000001"
    domain_name        = "labpass.example.test"
    origin_domain_name = "origin.labpass.example.test"
  }

  alb_origin = {
    dns_name = "mock-alb.us-east-1.elb.amazonaws.com"
    zone_id  = "Z35SXDOTRQ7X7K"
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

run "delivery_disabled" {
  module { source = "../modules/frontend" }
  command = plan
  variables {
    frontend            = null
    origin_verify_token = null
  }
  assert {
    condition = (
      length(aws_cloudfront_distribution.site) == 0 &&
      length(aws_s3_bucket.frontend) == 0 &&
      length(aws_acm_certificate.site) == 0 &&
      length(aws_route53_record.site) == 0 &&
      output.frontend_delivery == null
    )
    error_message = "Disabling delivery must omit frontend resources and outputs."
  }
}

run "private_storage_and_dns" {
  module { source = "../modules/frontend" }
  command = apply

  assert {
    condition = (
      aws_s3_bucket_public_access_block.frontend[0].block_public_acls &&
      aws_s3_bucket_public_access_block.frontend[0].block_public_policy &&
      aws_s3_bucket_public_access_block.frontend[0].ignore_public_acls &&
      aws_s3_bucket_public_access_block.frontend[0].restrict_public_buckets &&
      aws_s3_bucket_ownership_controls.frontend[0].rule[0].object_ownership == "BucketOwnerEnforced" &&
      one(aws_s3_bucket_server_side_encryption_configuration.frontend[0].rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256" &&
      aws_s3_bucket_versioning.frontend[0].versioning_configuration[0].status == "Enabled" &&
      !aws_s3_bucket.frontend[0].force_destroy &&
      aws_cloudfront_origin_access_control.frontend[0].signing_behavior == "always" &&
      aws_cloudfront_origin_access_control.frontend[0].signing_protocol == "sigv4"
    )
    error_message = "Frontend storage must be private, encrypted, versioned and signed through OAC."
  }

  assert {
    condition = (
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[0].Principal.Service == "cloudfront.amazonaws.com" &&
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[0].Action == "s3:GetObject" &&
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[0].Resource == "${aws_s3_bucket.frontend[0].arn}/*" &&
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == aws_cloudfront_distribution.site[0].arn &&
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[1].Effect == "Deny" &&
      jsondecode(aws_s3_bucket_policy.frontend[0].policy).Statement[1].Condition.Bool["aws:SecureTransport"] == "false"
    )
    error_message = "Bucket reads must be scoped to this distribution; insecure S3 transport must be denied."
  }

  assert {
    condition = (
      toset(keys(aws_route53_record.site)) == toset(["A", "AAAA"]) &&
      alltrue([for record in aws_route53_record.site :
        record.name == var.frontend.domain_name &&
        record.zone_id == var.frontend.hosted_zone_id &&
        record.alias[0].name == aws_cloudfront_distribution.site[0].domain_name &&
        record.alias[0].zone_id == aws_cloudfront_distribution.site[0].hosted_zone_id &&
        !record.alias[0].evaluate_target_health
      ]) &&
      aws_route53_record.origin[0].alias[0].name == var.alb_origin.dns_name &&
      aws_cloudfront_distribution.site[0].viewer_certificate[0].acm_certificate_arn == aws_acm_certificate_validation.site["viewer"].certificate_arn &&
      aws_acm_certificate.site["viewer"].domain_name == var.frontend.domain_name &&
      aws_acm_certificate.site["origin"].domain_name == var.frontend.origin_domain_name &&
      aws_acm_certificate.site["viewer"].arn != aws_acm_certificate.site["origin"].arn &&
      alltrue([for name, certificate in aws_acm_certificate_validation.site :
        certificate.validation_record_fqdns == toset([aws_route53_record.certificate[name].fqdn])
      ])
    )
    error_message = "Public DNS must point to CloudFront; separate validated certificates must cover the viewer and ALB origin."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.site[0].default_root_object == "index.html" &&
      aws_cloudfront_distribution.site[0].default_cache_behavior[0].target_origin_id == "frontend" &&
      toset(aws_cloudfront_distribution.site[0].aliases) == toset([var.frontend.domain_name]) &&
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "frontend"]).domain_name == aws_s3_bucket.frontend[0].bucket_regional_domain_name &&
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "frontend"]).origin_access_control_id == aws_cloudfront_origin_access_control.frontend[0].id &&
      output.frontend_delivery.url == "https://${var.frontend.domain_name}"
    )
    error_message = "The frontend must use the regional S3 REST origin with OAC and the configured public domain."
  }
}

run "api_forwarding_and_origin_gate" {
  module { source = "../modules/frontend" }
  command = apply

  assert {
    condition = (
      [for behaviour in aws_cloudfront_distribution.site[0].ordered_cache_behavior : behaviour.path_pattern] == ["/api", "/api/*", "/assets/*"] &&
      alltrue([for behaviour in slice(aws_cloudfront_distribution.site[0].ordered_cache_behavior, 0, 2) :
        behaviour.target_origin_id == "api" &&
        behaviour.cache_policy_id == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" &&
        behaviour.origin_request_policy_id == "b689b0a8-53d0-40ab-baf2-68738e2966ac" &&
        behaviour.viewer_protocol_policy == "https-only" &&
        toset(behaviour.allowed_methods) == toset(["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]) &&
        behaviour.response_headers_policy_id == aws_cloudfront_response_headers_policy.site["api"].id
      ]) &&
      one(aws_cloudfront_response_headers_policy.site["api"].custom_headers_config[0].items).value == "no-store" &&
      alltrue([for error in aws_cloudfront_distribution.site[0].custom_error_response :
        error.error_caching_min_ttl == 0 && error.response_page_path == null && error.response_code == null
      ])
    )
    error_message = "API traffic must use disabled caching, complete viewer forwarding except Host, HTTPS and unchanged error responses."
  }

  assert {
    condition = (
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).domain_name == var.frontend.origin_domain_name &&
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).connection_attempts == 1 &&
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).custom_origin_config[0].origin_protocol_policy == "https-only" &&
      one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).custom_origin_config[0].origin_ssl_protocols == toset(["TLSv1.2"]) &&
      one(one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).custom_header).value == var.origin_verify_token &&
      one(one([for origin in aws_cloudfront_distribution.site[0].origin : origin if origin.origin_id == "api"]).custom_header).name == "X-LabPass-Origin"
    )
    error_message = "CloudFront and ALB must share an exact origin token over verified HTTPS, with fail-closed default routing and a matching application Origin."
  }

  assert {
    condition = (
      aws_cloudfront_distribution.site[0].default_cache_behavior[0].cache_policy_id == local.api_cache_policy_id &&
      aws_cloudfront_cache_policy.static["assets"].min_ttl == 0 &&
      aws_cloudfront_cache_policy.static["assets"].default_ttl == 31536000 &&
      aws_cloudfront_cache_policy.static["assets"].parameters_in_cache_key_and_forwarded_to_origin[0].cookies_config[0].cookie_behavior == "none" &&
      aws_cloudfront_cache_policy.static["assets"].parameters_in_cache_key_and_forwarded_to_origin[0].headers_config[0].header_behavior == "none" &&
      aws_cloudfront_distribution.site[0].ordered_cache_behavior[2].cache_policy_id == aws_cloudfront_cache_policy.static["assets"].id &&
      one(aws_cloudfront_response_headers_policy.site["shell"].custom_headers_config[0].items).value == "no-cache" &&
      alltrue([for policy in aws_cloudfront_response_headers_policy.site :
        policy.security_headers_config[0].content_type_options[0].override &&
        policy.security_headers_config[0].frame_options[0].frame_option == "DENY" &&
        strcontains(policy.security_headers_config[0].content_security_policy[0].content_security_policy, "connect-src 'self'")
      ])
    )
    error_message = "HTML must remain fresh; hashed assets may cache without viewer cookies and must receive browser security headers."
  }
}

run "reject_frontend_without_hosting" {
  command = plan
  variables { application = null }
  expect_failures = [var.frontend]
}

run "reject_mismatched_browser_origin" {
  command = plan
  variables { application = merge(var.application, { public_origin = "https://other.example.test" }) }
  expect_failures = [var.frontend]
}

run "reject_certificate_override_with_frontend" {
  command = plan
  variables { application = merge(var.application, { origin_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000005" }) }
  expect_failures = [var.frontend]
}

run "reject_missing_standalone_certificate" {
  command = plan
  variables { frontend = null }
  expect_failures = [var.frontend]
}

run "reject_wildcard_domain" {
  command = plan
  variables { frontend = merge(var.frontend, { origin_domain_name = "*.example.test" }) }
  expect_failures = [var.frontend]
}

run "reject_identical_domains" {
  command = plan
  variables { frontend = merge(var.frontend, { origin_domain_name = "labpass.example.test" }) }
  expect_failures = [var.frontend]
}

run "reject_missing_origin_token" {
  command = plan
  variables { origin_verify_token = null }
  expect_failures = [var.origin_verify_token]
}

run "reject_origin_token_patterns" {
  command = plan
  variables { origin_verify_token = "*" }
  expect_failures = [var.origin_verify_token]
}

run "accept_previous_token_during_rotation" {
  module { source = "../modules/application" }
  command = plan
  variables {
    origin_verify_previous_token = "1111111111111111111111111111111111111111111111111111111111111111"
  }
  assert {
    condition     = one([for condition in aws_lb_listener_rule.api[0].condition : condition.http_header[0] if length(condition.http_header) == 1]).values == toset([var.origin_verify_token, var.origin_verify_previous_token])
    error_message = "The ALB must accept old and new tokens while CloudFront moves to the new token."
  }
}

run "reject_invalid_previous_token" {
  command = plan
  variables { origin_verify_previous_token = "old-token*" }
  expect_failures = [var.origin_verify_previous_token]
}

run "reject_unrelated_zone" {
  module { source = "../modules/frontend" }
  command = plan
  override_data {
    target = data.aws_route53_zone.site[0]
    values = { name = "unrelated.test.", private_zone = false }
  }
  expect_failures = [data.aws_route53_zone.site[0]]
}
