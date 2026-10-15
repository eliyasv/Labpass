# Milestone 5E: confirmation workload deployment

Verified offline on 15 October 2026. AWS resources have not been provisioned.

## Implementation

| Component | Configuration |
| --- | --- |
| Lambda | Digest-pinned x86_64 image, existing handler, published numeric version and `live` alias |
| Runtime | 60 seconds, 512 MiB, private application subnets and consumer security group/role |
| SQS mapping | Alias target, disabled by default, batch size 1, zero window and `ReportBatchItemFailures` |
| Concurrency | Function reservation and mapping maximum share one validated setting; default 2 |
| IAM/ECR | Consumer-scoped secrets/queue/logs, exact SES sender, Lambda service image reads and conditional function-code ENI denial |
| SES | Domain identity, 2048-bit Easy DKIM, three CNAME records, default configuration set and bounce/complaint suppression |
| Feedback | CloudWatch event metrics grouped by configuration set; no recipient/message dimensions |
| Activation | SES verification and successful DKIM required before enabling queue polling; database/account checks remain explicit |

## Verification

| Check | Result |
| --- | --- |
| Terraform formatting and provider-schema validation | Passed |
| `terraform -chdir=infra/foundation test` | **28 passed**, including 14 confirmation-workload cases |
| Rendered Terraform environment against `AwsSettings.from_env()` | Passed with Lambda's region supplied and the local public CA path; no AWS calls |
| Script regression suite | **27 passed** |
| Combined frontend/application/worker configuration | **43 mocked tests passed**, including one co-enabled integration case |
| Documentation links, code fences and shell syntax | Passed |

Tests cover image/version/alias wiring, private networking, runtime metadata,
handler limits, concurrency, scoped permissions, DKIM records, metrics,
disabled polling, SES/DKIM activation and invalid sender/domain/concurrency inputs.
Mocked SES states are isolated so verified and pending cases are independent.

The combined check includes the frontend-delivery configuration and both test
suites; it verifies that their DNS, certificates, IAM roles and secret references
coexist. All infrastructure checks use mocked AWS resources. Backend/frontend
source and container packaging are unchanged; database, browser and image-build
suites were not rerun in this milestone.

## Deployment checks

Actual image retrieval, regional concurrency quotas, private connectivity, ENI
authorization, SES verification, sandbox restrictions, mailbox delivery, alias
updates and SQS retry/redrive remain unverified. Database bootstrap and RDS
connection headroom must be checked before activation. Alarms, alert routing,
feedback processing and CI/CD remain pending.

Configuration and commands: [Confirmation worker deployment](confirmation-worker.md).
