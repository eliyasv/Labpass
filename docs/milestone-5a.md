# Milestone 5A: Terraform foundation

Verified 14 October 2026 (Asia/Kolkata). Foundation configuration is prepared and
tested offline. No AWS resources, application deployment, DNS changes or cloud
teardown were performed. This is the first part of the Terraform milestone;
workloads and delivery remain pending.

## Changes

The demo targets `us-east-1`, an owned `labpass.shop` domain and a $10 total
spending target for screenshots and cleanup. The initial two-hour estimate is
an assumption, not a confirmed session length. Existing DNS hosting/delegation
must be checked before creating the proposed demo/origin subdomains.

Terraform defines a dedicated two-AZ VPC with public, private application and
isolated database subnets. One zonal NAT provides private egress; an S3 gateway
endpoint supplies a separate S3 path. This chooses a shared egress failure point
for the short demo. The database route table owns no non-local routes and the
default security group owns no ingress/egress rules. Future workloads require
their own explicitly scoped security groups.

ECR has API/relay and Lambda repositories with immutable tags and disposable-demo
cleanup behavior. Standard SQS/DLQ resources preserve the existing worker contract:
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
| `infra/foundation/variables.tf` | Required account, selected region and demo naming inputs |
| `infra/foundation/network.tf` | AZ discovery, VPC, six subnets, routes, NAT/EIP and S3 endpoint |
| `infra/foundation/services.tf` | ECR and SQS/DLQ resources |
| `infra/foundation/outputs.tf` | IDs/URLs for later workload integration |
| `infra/foundation/tests/foundation.tftest.hcl` | Mocked topology/policy checks and invalid-input cases |
| `infra/README.md` | Offline commands, state/account requirements and cleanup ownership |
| `docs/demo-plan.md` | Cost comparisons, assumptions, screenshot plan and teardown checks |
| `.gitignore`, `README.md`, `docs/architecture.md`, `docs/checklist.md`, this report | State protection, infrastructure links, selected demo design and remaining scope |

## Separate review

Reviewed all changed configuration, provider lock, tests and documents. Traced
public-subnet internet routing, application NAT/S3 egress, database isolation,
default-group rules, queue retry/redrive and output compatibility with the worker
configuration. No application source/schema or authenticated request flow changed.

- **Low, fixed:** default-group rules and database routes were implicit. Explicit
  empty rule/route collections now declare the intended isolation, and tests check them.
- **Test setup, fixed:** computed IDs were unavailable to plan-only assertions.
  The topology test now uses the mock provider's in-memory apply. An initial
  attempt to generate resource values during the plan caused inconsistent random
  mock values during apply; default apply-phase generation fixes this. Distinct
  fixed source/DLQ identities make the queue-reference assertions meaningful.
- **Reviewed limitation:** one NAT and the planned Single-AZ database have shared
  failure points. They suit the temporary budget; high availability is not claimed.
- **Reviewed cleanup behavior:** ECR `force_delete=true` removes demo images during
  an authorized destroy. Dedicated demo resources must not absorb shared resources.

No unresolved high-severity issue was found in the reviewed foundation. Mocked
tests do not validate real AWS permissions, networking or service behavior.

## Executed checks

| Command/check | Result |
| --- | --- |
| `terraform version -json` | Installed Terraform 1.15.9, Linux amd64 |
| `aws --version` | AWS CLI 1.46.1 available; no authenticated AWS command run |
| `terraform -chdir=infra/foundation init -backend=false -input=false` | Installed AWS provider 6.68.0, signed by HashiCorp; generated provider lockfile |
| `terraform -chdir=infra/foundation fmt -check -recursive` | Passed |
| `terraform -chdir=infra/foundation validate -no-color` | Configuration valid |
| `terraform -chdir=infra/foundation test -no-color` | **4 passed, 0 failed** |
| Public RDS price-list download and local extraction | Verified us-east-1 PostgreSQL instance/storage rates; publication 6 October 2026 |
| `git diff --check` | Passed |
| Ignore checks | Provider directory, state, plan and local variables ignored; provider lock remains trackable |

Registry/price-list DNS was initially blocked by the sandbox. Provider IPC sockets
also prevented validation/testing there. Initialization/download and offline
provider checks succeeded after execution permission was requested. The price
list remains in `/tmp/labpass-rds-prices-us-east-1.json`; it is not tracked.

Tests use a mock AWS provider throughout, with fictional test-only identifiers
and in-memory state. They verify two-AZ separation, distinct subnet ranges, no
automatic public IPs, NAT/S3 routing, isolated DB routes, empty default-group
rules, ECR immutability, queue encryption/visibility/retention and source-only
redrive. Negative cases reject another region, an empty account ID and one
available zone. No persistent foundation state was created by testing.

## Run and inspect

Use the commands in [Terraform](../infra/README.md#offline-checks). They initialize
only local provider dependencies, validate configuration and execute mocked tests.
No AWS credentials are needed. Do not apply the foundation while the application
stack is unfinished; NAT incurs charges even without application traffic.

The [demo plan](demo-plan.md) uses a $3 planning allowance for an initial short
session, leaving margin within the requested $10. The fixed compute/NAT/ALB
subtotal is not the whole bill. Traffic, storage, DNS, requests, monitoring,
delays and tax remain additional. Budget notifications cannot enforce a hard cap.
Recalculate against the complete resource plan before provisioning.

## Remaining work

Real account authorization/AZ availability, AWS apply/destroy, network reachability,
ECR publishing, SQS redrive, costs and cleanup have not been tested in AWS.
No cloud endpoint, screenshot, performance or recovery result is claimed.
The application suite was not rerun because this change touches only Terraform
and documentation; its previous verification is recorded in earlier reports.

Next: add RDS and restricted DB roles, secret bootstrap/refresh integration,
ALB/EC2/SSM, CloudFront/S3/OAC, DNS/ACM, Lambda/SES and scoped runtime roles.
Confirm DNS management and an actual deployment window, then add remote state,
GitHub Actions OIDC, immutable releases, single migrations, alarms and a tested
demo/teardown runbook. Provisioning/deployment/destruction still require explicit
authorization after the complete plan is reviewable.
