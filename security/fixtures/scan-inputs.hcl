# Fictional inputs used only by Trivy to evaluate all optional resources.
aws_account_id       = "123456789012"
github_repository    = "example/labpass"
github_owner_id      = "1"
github_repository_id = "2"
public_domain_name   = "example.test"
origin_verify_token  = "0000000000000000000000000000000000000000000000000000000000000000"
application = {
  ami_id                 = "ami-00000000000000001"
  image_digest           = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  public_origin          = "https://labpass.example.test"
  api_desired_capacity   = 2
  relay_desired_capacity = 1
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
