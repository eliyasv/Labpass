# Infrastructure

Terraform roots: `foundation/` for workloads; `delivery/` for OIDC roles,
remote state storage, the migration document and public DNS. Region: `us-east-1`.

The foundation composes local `network`, `database`, `application`, `frontend`
and `confirmations` modules. Shared ECR and SQS resources remain in the root.
[Module interfaces](modules/README.md).

Resource layout, subnet routing and availability limits:
[Infrastructure design](../docs/infrastructure.md).

## Requirements

- Terraform 1.15.x.
- AWS provider 6.68.0, pinned in `foundation/.terraform.lock.hcl`.

## Offline checks

Run from the repository root:

```bash
terraform fmt -check -recursive infra
for task_root in infra/foundation infra/delivery; do
  terraform -chdir="$task_root" init -backend=false -input=false -lockfile=readonly
  terraform -chdir="$task_root" validate
  terraform -chdir="$task_root" test
done
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
| `confirmation_worker` | `null` | Lambda image digest, email domain/sender and public zone ID; SQS concurrency defaults to 2, reservation to enabled and polling to disabled |

Hosting desired capacities default to zero for controlled database setup. See
[application inputs](../docs/application-hosting.md#configuration).
Frontend integration provisions the origin certificate; omit
`application.origin_certificate_arn` in that mode. Zone ownership/delegation,
publication and origin-token handling: [Frontend delivery](../docs/frontend-delivery.md).
Confirmation configuration and activation:
[Confirmation processing](../docs/confirmation-worker.md).

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
| `confirmation_worker` | Function/version/alias, mapping state, log group, SES verification and DKIM metadata; null when disabled |

## State

The foundation declares a partial S3 backend. Configure its bucket/key, encryption
and S3 locking before real plans. The delivery bootstrap uses separate local state
that must be preserved outside Git. State, saved plans, local variable files and
provider binaries are ignored; provider lockfiles are tracked.

Password values are created by RDS and the SDK bootstrap, outside Terraform.
The CloudFront/ALB origin token is stored in state and saved plans despite its
sensitive input flag. Release plans use private versioned S3 and are not uploaded
to GitHub artifacts. Backend initialization, state migration and role setup:
[CI/CD and release security](../docs/delivery.md).

## Validation

[Deployment and test results](../docs/verification.md) ·
[Capabilities, trade-offs and remaining work](../docs/project-status.md).

[Infrastructure design](../docs/infrastructure.md) ·
[Database runtime](../docs/database-runtime.md) ·
[Application hosting](../docs/application-hosting.md) ·
[Frontend delivery](../docs/frontend-delivery.md) ·
[Confirmation worker](../docs/confirmation-worker.md)
