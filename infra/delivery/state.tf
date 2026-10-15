locals {
  state_bucket_name = "${var.workload_name_prefix}-${var.aws_account_id}-tfstate"
  state_key         = "foundation/terraform.tfstate"
}

resource "aws_s3_bucket" "state" {
  bucket        = local.state_bucket_name
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "plans" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-release-plans"
    status = "Enabled"
    filter { prefix = "plans/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.state]
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*"
      Resource  = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
