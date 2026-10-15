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
| Optional hosting | HTTPS ALB; private API/relay ASGs; bootstrap/migration launch templates |
| Host access/logging | SSM, ECR pulls and component CloudWatch log groups with seven-day retention |
| Optional frontend delivery | Private versioned S3 with OAC, CloudFront, public/origin DNS records and separate DNS-validated ACM certificates |

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
| `application` | `null` | Hosting configuration; AMI, image digest, HTTPS origin and an existing certificate for standalone hosting |
| `frontend` | `null` | S3/CloudFront delivery; existing public hosted zone ID, public hostname and origin hostname |
| `origin_verify_token` | `null` | Required sensitive 64-character random hex token when application hosting is enabled |
| `origin_verify_previous_token` | `null` | Previous token accepted during staged rotation |

Hosting desired capacities default to zero for controlled database setup. See
[application inputs](../docs/application-hosting.md#configuration).
Frontend integration provisions the origin certificate; omit
`application.origin_certificate_arn` in that mode. Zone ownership/delegation,
publication and origin-token handling: [Frontend delivery](../docs/frontend-delivery.md).

## Outputs

| Output | Contents |
| --- | --- |
| `network` | VPC ID, availability zones and subnet IDs |
| `image_repositories` | API and Lambda repository URLs |
| `confirmation_queue` | Source queue ARN/URL and DLQ ARN |
| `database` | Endpoint, master/role-secret ARNs and database security group |
| `runtime_access` | Workload security groups, IAM role ARNs and EC2 profile names |
| `application_hosting` | ALB/target group, ASG names, template ID/versions and log groups; null when disabled |
| `frontend_delivery` | Public URL, bucket, distribution ID/domain and certificate/origin metadata; null when disabled |

## State

Backend: local. State, saved plans, local variable files and provider binaries
are excluded from Git. The provider lockfile is tracked.

Password values are created by RDS and the SDK bootstrap, outside Terraform.
The CloudFront/ALB origin token is stored in state and saved plans despite its
sensitive input flag. Restrict their access; shared deployment requires encrypted,
versioned remote state and locking.

## Integration status

Lambda mapping/SES/VPC permissions, release workflows and alarms remain pending.
CloudFront/S3/OAC, authoritative DNS, certificate issuance, EC2 bootstrap, database
access and ALB TLS/health have not been verified in AWS.

[Infrastructure design](../docs/infrastructure.md) ·
[Database runtime](../docs/database-runtime.md) ·
[Application hosting](../docs/application-hosting.md) ·
[Frontend delivery](../docs/frontend-delivery.md)
