# Public RDS trust bundle

`rds-global-bundle.pem` contains public CA certificates, not credentials or private
keys. Downloaded on 14 October 2026 from AWS's documented commercial-region
[RDS trust store](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem).
The file is deliberately tracked so image builds do not download a changing bundle.

SHA-256: `fe45bbebf92ad3e27a583bbb2ddd1553c521ed4d49af5514dc0a40372ea5395c`.

Refresh deliberately when AWS changes the trust store or before a database CA
rotation. Download to a temporary file, inspect certificates/validity, review the
diff, update this checksum and rebuild/retest both images. Compare the selected
RDS CA against the bundle during the authorized deployment. Never replace
`verify-full` with an encryption-only mode to bypass a certificate failure.

See [RDS TLS and certificate bundles](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html)
and [PostgreSQL hostname verification](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).
