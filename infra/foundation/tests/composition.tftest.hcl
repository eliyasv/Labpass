# Fictional resource identifiers; the complete graph uses a mock provider.
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

  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b"] }
  }
  mock_data "aws_rds_orderable_db_instance" {
    defaults = { instance_class = "db.t4g.micro" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      address = "mock.example.us-east-1.rds.amazonaws.com"
      master_user_secret = [{
        secret_arn    = "arn:aws:secretsmanager:us-east-1:123456789012:secret:rds!db-mock-AbCd12"
        kms_key_id    = "mock-key"
        secret_status = "active"
      }]
    }
  }
  mock_resource "aws_lambda_function" {
    defaults = {
      arn     = "arn:aws:lambda:us-east-1:123456789012:function:labpass-demo-confirmations"
      version = "7"
    }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:us-east-1:123456789012:function:labpass-demo-confirmations:live" }
  }
  mock_resource "aws_sesv2_email_identity" {
    defaults = {
      arn                         = "arn:aws:ses:us-east-1:123456789012:identity/example.test"
      verified_for_sending_status = false
      dkim_signing_attributes = {
        tokens = ["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "cccccccccccccccccccccccccccccccc"]
        status = "SUCCESS"
      }
    }
  }
  mock_resource "aws_sesv2_configuration_set" {
    defaults = { arn = "arn:aws:ses:us-east-1:123456789012:configuration-set/labpass-demo-confirmations" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/labpass-demo-confirmations" }
  }

}

override_resource {
  target = module.frontend.aws_cloudfront_response_headers_policy.site["api"]
  values = { id = "00000000-0000-0000-0000-000000000004" }
}

override_resource {
  target = module.frontend.aws_cloudfront_response_headers_policy.site["shell"]
  values = { id = "00000000-0000-0000-0000-000000000005" }
}

override_resource {
  target = module.frontend.aws_cloudfront_response_headers_policy.site["assets"]
  values = { id = "00000000-0000-0000-0000-000000000006" }
}

override_data {
  target = module.frontend.data.aws_route53_zone.site[0]
  values = { name = "example.test.", private_zone = false }
}

override_resource {
  target = module.application.aws_lb.api[0]
  values = {
    arn      = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/mock/0000000000000000"
    dns_name = "mock-alb.us-east-1.elb.amazonaws.com"
    zone_id  = "Z35SXDOTRQ7X7K"
  }
}

override_resource {
  target = module.frontend.aws_route53_record.origin[0]
  values = { fqdn = "origin.labpass.example.test." }
}

override_resource {
  target = module.frontend.aws_acm_certificate.site["viewer"]
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
  target = module.frontend.aws_acm_certificate.site["origin"]
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

override_data {
  target = module.confirmations.data.aws_route53_zone.email[0]
  values = { name = "example.test.", private_zone = false }
}
override_resource {
  target = module.database.aws_iam_role.runtime["api"]
  values = { arn = "arn:aws:iam::123456789012:role/labpass-demo-api" }
}
override_resource {
  target = module.database.aws_iam_role.runtime["relay"]
  values = { arn = "arn:aws:iam::123456789012:role/labpass-demo-relay" }
}
override_resource {
  target = module.database.aws_iam_role.runtime["bootstrap"]
  values = { arn = "arn:aws:iam::123456789012:role/labpass-demo-bootstrap" }
}
override_resource {
  target = module.database.aws_iam_role.runtime["migration"]
  values = { arn = "arn:aws:iam::123456789012:role/labpass-demo-migration" }
}
override_resource {
  target = module.database.aws_iam_role.runtime["consumer"]
  values = { arn = "arn:aws:iam::123456789012:role/labpass-demo-consumer" }
}
override_resource {
  target = module.application.aws_launch_template.runtime["api"]
  values = { id = "lt-00000000000000001", latest_version = 3 }
}
override_resource {
  target = module.application.aws_launch_template.runtime["relay"]
  values = { id = "lt-00000000000000002", latest_version = 3 }
}
override_resource {
  target = module.application.aws_launch_template.runtime["bootstrap"]
  values = { id = "lt-00000000000000003", latest_version = 3 }
}
override_resource {
  target = module.application.aws_launch_template.runtime["migration"]
  values = { id = "lt-00000000000000004", latest_version = 3 }
}
override_resource {
  target = aws_ecr_repository.application["api"]
  values = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/labpass-demo/api", repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/api" }
}
override_resource {
  target = aws_ecr_repository.application["lambda"]
  values = { arn = "arn:aws:ecr:us-east-1:123456789012:repository/labpass-demo/lambda", repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/lambda" }
}
override_resource {
  target = aws_sqs_queue.confirmations
  values = { arn = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations" }
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

  confirmation_worker = {
    image_digest   = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    email_domain   = "example.test"
    sender_email   = "notifications@example.test"
    hosted_zone_id = "Z00000000000001"
  }
}
run "all_workloads_composed" {
  command = apply
  assert {
    condition = (
      module.application.listener_certificate_arn == module.frontend.certificates["origin"] &&
      module.frontend.certificates["viewer"] != module.frontend.certificates["origin"] &&
      output.frontend_delivery.origin_certificate_arn == module.application.listener_certificate_arn &&
      output.frontend_delivery.url == var.application.public_origin &&
      module.application.alb_origin.dns_name == output.application_hosting.alb_dns_name &&
      module.application.alb_origin.zone_id == output.application_hosting.alb_zone_id
    )
    error_message = "Frontend certificates and the ALB origin must compose without dependency cycles."
  }
  assert {
    condition = (
      length(output.network.availability_zones) == 2 &&
      length(output.network.application_subnet_ids) == 2 &&
      length(output.application_hosting.launch_templates) == 4 &&
      output.application_hosting.launch_templates.api.id != output.application_hosting.launch_templates.relay.id &&
      output.confirmation_worker.alias_arn == "arn:aws:lambda:us-east-1:123456789012:function:labpass-demo-confirmations:live" &&
      !output.confirmation_worker.mapping_enabled &&
      alltrue([for name, arn in output.runtime_access.role_arns : endswith(arn, "/labpass-demo-${name}")])
    )
    error_message = "The root must preserve workload output contracts, distinct runtime identities and disabled initial polling."
  }
}
run "standalone_hosting" {
  command = plan
  variables {
    frontend            = null
    confirmation_worker = null
    application         = merge(var.application, { origin_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000003" })
  }
  assert {
    condition     = module.application.listener_certificate_arn == var.application.origin_certificate_arn && output.frontend_delivery == null && output.confirmation_worker == null
    error_message = "Standalone hosting must use its supplied certificate and omit frontend/confirmation workloads."
  }
}
run "optional_workloads_disabled" {
  command = plan
  variables {
    application         = null
    frontend            = null
    confirmation_worker = null
    origin_verify_token = null
  }
  assert {
    condition     = output.application_hosting == null && output.frontend_delivery == null && output.confirmation_worker == null
    error_message = "Optional workload outputs must remain null when disabled."
  }
}
