# Milestone 5A: Terraform foundation

Verified 14 October 2026. Foundation configuration is validated and tested
offline. Application workloads and AWS deployment remain pending.

## Changes

Terraform defines a dedicated two-AZ VPC with public, private application and
isolated database subnets. One zonal NAT provides private egress; an S3 gateway
endpoint supplies a separate S3 path. The NAT is a shared egress dependency.
The database route table owns no non-local routes and the
default security group owns no ingress/egress rules. Future workloads require
their own explicitly scoped security groups.

ECR has API/relay and Lambda repositories with immutable tags and scan-on-push.
Standard SQS/DLQ resources preserve the existing worker contract:
360-second visibility, five receives before redrive, encrypted queues and longer
DLQ retention. The DLQ permits only this source queue. Roles, queue consumers and
event-source mapping are not installed yet.

Provider configuration requires the actual account ID and restricts operation to
that account/region. Terraform 1.15.x and AWS provider 6.68.0 are pinned; signed
provider package checksums are committed. State, plans, provider installs, local
variable files and crash logs are excluded from Git.

## Files

| Files | Purpose |
| --- | --- |
| `infra/foundation/versions.tf`, `.terraform.lock.hcl` | Terraform/provider compatibility, account guard and signed provider lock |
| `infra/foundation/variables.tf` | Required account, selected region and resource naming inputs |
| `infra/foundation/network.tf` | AZ discovery, VPC, six subnets, routes, NAT/EIP and S3 endpoint |
| `infra/foundation/services.tf` | ECR and SQS/DLQ resources |
| `infra/foundation/outputs.tf` | IDs/URLs for later workload integration |
| `infra/foundation/tests/foundation.tftest.hcl` | Mocked topology/policy checks and invalid-input cases |
| `infra/README.md` | Offline commands, state/account requirements and resource ownership |
| `docs/infrastructure.md` | Network boundaries, resource configuration and integration requirements |
| `.gitignore`, `README.md`, `docs/architecture.md`, `docs/checklist.md`, this report | State protection, infrastructure links, design decisions and remaining scope |

## Review findings

- **Low, fixed:** default-group rules and database routes were implicit. Explicit
  empty rule/route collections now declare the intended isolation, and tests check them.
- **Test setup, fixed:** computed IDs were unavailable to plan-only assertions.
  The topology test uses the mock provider's in-memory apply with apply-phase
  resource-value generation. Distinct fixed source/DLQ identities verify queue references.
- **Availability limitation:** one NAT creates a shared egress dependency.
  Database failover is separate from two-AZ subnet placement and is not implemented.
- **Artifact retention:** ECR `force_delete=true` permits removal of repositories
  containing images.

Mocked tests do not validate real AWS permissions, networking or service behavior.

## Verification

| Command/check | Result |
| --- | --- |
| `terraform version -json` | Installed Terraform 1.15.9, Linux amd64 |
| `terraform -chdir=infra/foundation init -backend=false -input=false` | Installed AWS provider 6.68.0, signed by HashiCorp; generated provider lockfile |
| `terraform -chdir=infra/foundation fmt -check -recursive` | Passed |
| `terraform -chdir=infra/foundation validate -no-color` | Configuration valid |
| `terraform -chdir=infra/foundation test -no-color` | **4 passed, 0 failed** |
| `git diff --check` | Passed |
| Ignore checks | Provider directory, state, plan and local variables ignored; provider lock remains trackable |

Tests use a mock AWS provider throughout, with fictional test-only identifiers
and in-memory state. They verify two-AZ separation, distinct subnet ranges, no
automatic public IPs, NAT/S3 routing, isolated DB routes, empty default-group
rules, ECR immutability, queue encryption/visibility/retention and source-only
redrive. Negative cases reject another region, an empty account ID and one
available zone. No persistent foundation state was created by testing.

## Run and inspect

Commands: [Terraform offline checks](../infra/README.md#offline-checks).
Tests use a mocked provider and require no AWS credentials.
Resource boundaries and pending workloads: [Infrastructure](infrastructure.md).

## Remaining work

Real account authorization/AZ availability, AWS provisioning, network reachability,
ECR publishing and SQS redrive have not been tested in AWS.
Cloud performance and recovery remain unverified.

Pending components: RDS and restricted DB roles, secret bootstrap/refresh,
ALB/EC2/SSM, CloudFront/S3/OAC, DNS management and ACM validation, Lambda/SES,
scoped runtime roles, remote state, GitHub Actions OIDC, immutable releases,
single migrations, alarms and deployment/recovery runbooks.
