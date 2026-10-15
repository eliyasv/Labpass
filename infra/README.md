# Infrastructure

Terraform root: `foundation/`. Region: `us-east-1`.

## Resources

| Resource | Configuration |
| --- | --- |
| VPC | `10.42.0.0/16`, two availability zones |
| Subnets | Two public, two private application, two isolated database |
| Egress | One zonal NAT gateway; S3 gateway endpoint |
| Default security group | Empty ingress and egress rules |
| ECR | API/relay and Lambda repositories; immutable tags, AES256, scan-on-push, `force_delete=true` |
| SQS | Standard, SQS-managed encryption, 360-second visibility, 4-day retention; redrive after 5 receives |
| DLQ | Standard, SQS-managed encryption, 14-day retention; source queue restricted |
| RDS | Private PostgreSQL 18.6, Single-AZ `db.t4g.micro`, encrypted 20 GiB gp3, seven-day backups |
| Database access | PostgreSQL ingress from API/relay/consumer/migration/bootstrap groups |
| Secrets | RDS-managed master password; four role-secret containers |
| IAM | Component-specific secret reads, bootstrap secret writes, relay/consumer SQS scopes and EC2 profiles |

## Requirements

- Terraform 1.15.x.
- AWS provider 6.68.0, pinned in `foundation/.terraform.lock.hcl`.

## Offline checks

Run from the repository root:

```bash
terraform -chdir=infra/foundation init -backend=false -input=false
terraform -chdir=infra/foundation fmt -check -recursive
terraform -chdir=infra/foundation validate
terraform -chdir=infra/foundation test
```

Tests use a mocked AWS provider and require no AWS credentials.

## Inputs

| Variable | Default | Purpose |
| --- | --- | --- |
| `aws_account_id` | Required | 12-digit target account ID; enforced by `allowed_account_ids` |
| `aws_region` | `us-east-1` | Region; validation restricts this root to `us-east-1` |
| `name_prefix` | `labpass-demo` | Resource name prefix |
| `database_engine_version` | `18.6` | Exact PostgreSQL 18 minor version; target-region orderability check |
| `database_deletion_protection` | `true` | RDS deletion protection; final snapshot remains enabled |

## Outputs

| Output | Contents |
| --- | --- |
| `network` | VPC ID, availability zones and subnet IDs |
| `image_repositories` | API and Lambda repository URLs |
| `confirmation_queue` | Source queue ARN/URL and DLQ ARN |
| `database` | Endpoint, master/role-secret ARNs and database security group |
| `runtime_access` | Workload security groups, IAM role ARNs and EC2 profile names |

## State

Backend: local. State, saved plans, local variable files and provider binaries
are excluded from Git. The provider lockfile is tracked.

Password values are created by RDS and the SDK bootstrap, outside Terraform.

## Integration status

Compute, frontend hosting, DNS/TLS certificates, Lambda mapping, SES permissions,
VPC attachment permissions, ECR/SSM/logging policies and monitoring remain pending.
Database bootstrap and deployed access/TLS checks have not run in AWS.

[Infrastructure design](../docs/infrastructure.md) ·
[Database runtime](../docs/database-runtime.md) ·
[Verification](../docs/milestone-5b.md)
