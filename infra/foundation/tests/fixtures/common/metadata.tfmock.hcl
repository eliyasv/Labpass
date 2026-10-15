mock_data "aws_availability_zones" {
  defaults = { names = ["us-east-1a", "us-east-1b"] }
}

mock_data "aws_rds_orderable_db_instance" {
  defaults = { instance_class = "db.t4g.micro" }
}

mock_data "aws_ami" {
  defaults = {
    id               = "ami-00000000000000001"
    root_device_name = "/dev/xvda"
  }
}

mock_data "aws_ec2_managed_prefix_list" {
  defaults = { id = "pl-00000000000000001" }
}

mock_resource "aws_lb" {
  defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/mock/0000000000000000" }
}

mock_resource "aws_lb_listener" {
  defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/mock/0000000000000000/0000000000000001" }
}

mock_resource "aws_lb_target_group" {
  defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/mock/0000000000000000" }
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

mock_resource "aws_launch_template" {
  defaults = { id = "lt-00000000000000001", latest_version = 3 }
}
mock_resource "aws_iam_role" {
  defaults = { arn = "arn:aws:iam::123456789012:role/labpass-demo-consumer" }
}


mock_data "aws_route53_zone" {
  defaults = { name = "example.test.", zone_id = "Z00000000000001", private_zone = false }
}
