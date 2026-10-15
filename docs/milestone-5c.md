# Milestone 5C: application hosting

Verified offline on 15 October 2026. AWS resources have not been provisioned.

## Implementation

| Component | Configuration |
| --- | --- |
| ALB | Public subnets; HTTPS from CloudFront origin-facing addresses; `/api/*` forwarding and readiness checks |
| API and relay | Separate private ASGs and instance profiles; explicit image digest and numeric template versions |
| Instances | Amazon Linux 2023 x86_64, IMDSv2, encrypted gp3 root volumes, no public IP/SSH key |
| Container supervision | Systemd restart/shutdown; UID 10001, read-only filesystem, bounded memory/processes and CloudWatch logs |
| Operator jobs | Bootstrap/migration launch templates; explicit jobs before application capacity |
| IAM | Repository-specific ECR pulls, component log groups and SSM access |

## Findings and fixes

| Severity | Finding | Resolution |
| --- | --- | --- |
| Medium | Relay startup required an SES sender although it only publishes to SQS | Relay configuration omits the sender and constructs no SES client; Lambda still requires it |
| Low | Package installation preceded explicit SSM startup | Enable SSM before installing Docker so management startup has no Docker installation dependency |
| Low | Stopping a container required readable deployment configuration | Shutdown now uses the component name even if configuration is unavailable; regression test added |

## Verification

| Command/check | Result |
| --- | --- |
| `bash scripts/test-local.sh -q` | **180 passed**, real PostgreSQL; includes two relay dependency regressions |
| `.venv/bin/python -m pytest -q scripts/tests` | **27 passed**, including 18 host-helper cases |
| Terraform formatting, provider validation and mocked tests | **14 passed**; enabled/disabled hosting, network/role separation and invalid inputs |
| Python lint/format and shell syntax | Passed |
| Four rendered user-data scripts | Shell syntax and API/worker/operator configuration passed; each below 16 KiB |
| `systemd-analyze verify` with staged helper and dependency units | API/relay unit validation passed |
| API and Lambda image builds | Passed |
| Isolated cloud API container | Live 200; sanitized readiness 503 without credentials/network, under container resource/security limits |
| Relay configuration check in built image | Passed without SES settings or AWS calls |
| Offline Lambda runtime smoke | Imports, handler and runtime emulator passed |
| Lambda container dependency check | No broken requirements |

Host-helper tests execute the shell script with AWS/Docker stand-ins. They cover
immutable pulls, instance-role credential selection, ECR auth cleanup after errors,
container arguments, explicit operator jobs, missing configuration and shutdown.
They do not boot EC2, install packages or contact AWS.

## Remaining integration

CloudFront/S3/OAC, DNS/ACM provisioning, distribution-specific origin validation,
Lambda/SES deployment, CI/CD and alarms remain pending. Real EC2 bootstrap,
SSM/ECR/logging permissions, ALB TLS/health, refresh availability and database
connection limits require AWS verification. Single-AZ RDS and shared NAT remain
availability dependencies.

Configuration and commands: [Application hosting](application-hosting.md) and
[Terraform](../infra/README.md).
