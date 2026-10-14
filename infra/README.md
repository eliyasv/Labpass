# Terraform

Infrastructure configuration for LabPass in `us-east-1`.

## Foundation

`foundation/` defines:

- A VPC with two public, two private application and two isolated database subnets.
- One zonal NAT gateway shared by the application subnets.
- An S3 gateway endpoint for private S3 access and ECR layer retrieval.
- Empty default security-group rules; workloads will receive their own groups.
- Two ECR repositories with immutable image tags, for the API/relay and Lambda.
- An encrypted standard SQS confirmation queue and a dedicated DLQ.

The source queue uses 360-second visibility, five receives before redrive,
four-day retention and a DLQ with fourteen-day retention. IAM access and the
Lambda mapping are added with the workloads.

This is the foundation, not a deployable application stack. RDS, runtime roles,
secrets, compute, frontend hosting, TLS/DNS and monitoring remain to be added.
Network boundaries and integration requirements are documented in
[infrastructure design](../docs/infrastructure.md).

## Offline checks

Requires Terraform 1.15.x. The AWS provider is pinned to 6.68.0, with signed
package checksums recorded in `foundation/.terraform.lock.hcl`.

From the repository root:

```bash
terraform -chdir=infra/foundation init -backend=false -input=false
terraform -chdir=infra/foundation fmt -check -recursive
terraform -chdir=infra/foundation validate
terraform -chdir=infra/foundation test
```

Initialization downloads provider binaries; validation and tests do not require
AWS credentials. Tests replace the AWS provider with a mock. The primary test
applies to in-memory mock state so generated resource IDs can be checked; it
does not run an AWS apply. The remaining tests reject another region, an empty
account ID and insufficient availability zones. See
[Terraform provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking).

## State and account

Real plans require `aws_account_id` to identify the approved account; there is
no default or sample account in executable configuration. The AWS provider's
`allowed_account_ids` guard rejects credentials for another account. Use an
authenticated role/profile instead of credentials in Terraform variables.

This root currently uses Terraform's local backend. Preserve its state outside
Git. Before CI/shared execution, configure encrypted, versioned S3 state with
locking and scoped access.
S3 supports `use_lockfile`; the state backend does not require a DynamoDB table.
See [S3 backend configuration](https://developer.hashicorp.com/terraform/language/backend/s3).

Provider binaries, state, plan files, local variable files and crash logs are
ignored. Commit the provider lockfile. No secret values are stored in this
foundation's inputs or outputs.

## Resource ownership

Workload integration uses the foundation's network, repository and queue outputs.
Existing shared resources should retain separate state ownership. ECR currently
sets `force_delete=true`, which permits repository removal when images are present.
Review artifact retention before reusing this configuration for a persistent
environment.
