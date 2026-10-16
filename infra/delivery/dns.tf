# Registrar delegation uses these nameservers before the foundation validates ACM certificates.
resource "aws_route53_zone" "public" {
  count         = var.public_domain_name == null ? 0 : 1
  name          = var.public_domain_name
  comment       = "LabPass public application DNS"
  force_destroy = false
}
