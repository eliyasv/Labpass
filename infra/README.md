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

## Outputs

| Output | Contents |
| --- | --- |
| `network` | VPC ID, availability zones and subnet IDs |
| `image_repositories` | API and Lambda repository URLs |
| `confirmation_queue` | Source queue ARN/URL and DLQ ARN |

## State

Backend: local. State, saved plans, local variable files and provider binaries
are excluded from Git. The provider lockfile is tracked.

## Integration status

RDS, compute, frontend hosting, runtime IAM, secrets, TLS/DNS, Lambda mapping
and monitoring remain pending.

[Infrastructure design](../docs/infrastructure.md) ·
[Verification](../docs/milestone-5a.md)
