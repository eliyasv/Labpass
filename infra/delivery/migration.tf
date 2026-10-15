resource "aws_ssm_document" "migrate" {
  name          = "${var.workload_name_prefix}-release-migration"
  document_type = "Command"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Run the reviewed image's migration on the dedicated operator host."
    parameters = { ImageDigest = {
      type = "String", allowedPattern = "^sha256:[0-9a-f]{64}$"
    } }
    mainSteps = [{
      action = "aws:runShellScript", name = "migration"
      inputs = {
        timeoutSeconds = "600"
        runCommand = [
          "set -eu",
          "exec 9>/run/labpass-release-migration.lock",
          "flock -n 9",
          "test -f /etc/labpass/migration/runtime.env",
          "umask 077",
          "printf '%s@%s\\n' '${var.aws_account_id}.dkr.ecr.us-east-1.amazonaws.com/${var.workload_name_prefix}/api' '{{ ImageDigest }}' > /etc/labpass/migration/image",
          "/usr/local/sbin/labpass-service migration pull",
          "/usr/local/sbin/labpass-service migration job"
        ]
      }
    }]
  })
}
