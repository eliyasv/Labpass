# Fictional metadata; no credentials or real AWS resources.
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
  defaults = { latest_version = 3 }
}


override_resource {
  target = aws_launch_template.runtime["api"]
  values = { id = "lt-00000000000000001", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["relay"]
  values = { id = "lt-00000000000000002", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["bootstrap"]
  values = { id = "lt-00000000000000003", latest_version = 3 }
}
override_resource {
  target = aws_launch_template.runtime["migration"]
  values = { id = "lt-00000000000000004", latest_version = 3 }
}

override_resource {
  target = aws_ecr_repository.application["api"]
  values = {
    repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/labpass-demo/api"
    arn            = "arn:aws:ecr:us-east-1:123456789012:repository/labpass-demo/api"
  }
}
override_resource {
  target = aws_sqs_queue.confirmations
  values = { arn = "arn:aws:sqs:us-east-1:123456789012:mock-confirmations" }
}
override_resource {
  target = aws_secretsmanager_secret.database["api"]
  values = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-api-AbCd12" }
}
override_resource {
  target = aws_secretsmanager_secret.database["relay"]
  values = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-relay-AbCd12" }
}
override_resource {
  target = aws_secretsmanager_secret.database["consumer"]
  values = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-consumer-AbCd12" }
}
override_resource {
  target = aws_secretsmanager_secret.database["migration"]
  values = { arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:mock-migration-AbCd12" }
}
