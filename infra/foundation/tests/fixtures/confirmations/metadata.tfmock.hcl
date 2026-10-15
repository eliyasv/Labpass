mock_data "aws_availability_zones" {
  defaults = { names = ["us-east-1a", "us-east-1b"] }
}
mock_data "aws_route53_zone" {
  defaults = { name = "example.com.", private_zone = false }
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
    arn                         = "arn:aws:ses:us-east-1:123456789012:identity/example.com"
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
