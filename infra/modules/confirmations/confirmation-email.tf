data "aws_route53_zone" "email" {
  count        = local.confirmation_enabled ? 1 : 0
  zone_id      = var.confirmation_worker.hosted_zone_id
  private_zone = false

  lifecycle {
    postcondition {
      condition = !self.private_zone && (
        var.confirmation_worker.email_domain == trimsuffix(self.name, ".") ||
        endswith(var.confirmation_worker.email_domain, ".${trimsuffix(self.name, ".")}")
      )
      error_message = "The SES domain must belong to the selected public hosted zone; public delegation must be configured separately."
    }
  }
}

resource "aws_sesv2_configuration_set" "confirmations" {
  count                  = local.confirmation_enabled ? 1 : 0
  configuration_set_name = local.confirmation_name

  sending_options {
    sending_enabled = true
  }
  suppression_options {
    suppressed_reasons = ["BOUNCE", "COMPLAINT"]
  }
}

resource "aws_sesv2_email_identity" "confirmations" {
  count                  = local.confirmation_enabled ? 1 : 0
  email_identity         = var.confirmation_worker.email_domain
  configuration_set_name = aws_sesv2_configuration_set.confirmations[0].configuration_set_name

  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
}

resource "aws_route53_record" "email_dkim" {
  for_each = local.confirmation_enabled ? toset(["0", "1", "2"]) : toset([])
  zone_id  = data.aws_route53_zone.email[0].zone_id
  name     = "${aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].tokens[tonumber(each.key)]}._domainkey.${var.confirmation_worker.email_domain}"
  type     = "CNAME"
  records  = ["${aws_sesv2_email_identity.confirmations[0].dkim_signing_attributes[0].tokens[tonumber(each.key)]}.dkim.amazonses.com"]
  ttl      = 300
}

resource "aws_sesv2_configuration_set_event_destination" "metrics" {
  count                  = local.confirmation_enabled ? 1 : 0
  configuration_set_name = aws_sesv2_configuration_set.confirmations[0].configuration_set_name
  event_destination_name = "delivery-metrics"

  event_destination {
    enabled              = true
    matching_event_types = ["SEND", "DELIVERY", "BOUNCE", "COMPLAINT", "REJECT", "DELIVERY_DELAY"]
    cloud_watch_destination {
      dimension_configuration {
        dimension_name          = "ses:configuration-set"
        dimension_value_source  = "MESSAGE_TAG"
        default_dimension_value = aws_sesv2_configuration_set.confirmations[0].configuration_set_name
      }
    }
  }
}
