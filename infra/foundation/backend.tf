# Supply bucket/key/region and use_lockfile during init; delivery owns the bucket.
# Keep backend configuration separate from workload variables and credentials.
terraform {
  backend "s3" {}
}
