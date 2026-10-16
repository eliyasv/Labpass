# Technical documentation

## Infrastructure and operations

| Order | Guide | Scope |
| --- | --- | --- |
| 1 | [Infrastructure](infrastructure.md) | Network tiers, routing, security groups, Multi-AZ boundaries, scaling limits and state ownership |
| 2 | [CI/CD and release security](delivery.md) | CI gates, OIDC roles, approvals, immutable images, saved plans, migrations and release failures |
| 3 | [Application hosting](application-hosting.md) | EC2 startup, ALB/ASG health, rolling refreshes, SSM, logs and failure investigation |
| 4 | [Terraform modules](../infra/modules/README.md) | Resource ownership, typed interfaces, module dependencies and provider/state boundaries |
| 5 | [Verification](verification.md) | Live AWS evidence, infrastructure/security regressions and operational limits |

## Service configuration

| Guide | Scope |
| --- | --- |
| [Terraform commands](../infra/README.md) | Provider versions, inputs/outputs, offline checks and backend configuration |
| [Frontend delivery](frontend-delivery.md) | Private S3/OAC, CloudFront routing, DNS/TLS, origin restrictions and publication |
| [Database runtime](database-runtime.md) | RDS, database privileges, Secrets Manager, bootstrap and migrations |
| [Confirmation worker](confirmation-worker.md) | Lambda/SQS/SES activation, concurrency, IAM and delivery metrics |

## Application and local development

| Guide | Scope |
| --- | --- |
| [Architecture and decisions](architecture.md) | AWS request flow, application responsibilities, outbox processing, transactions and authentication |
| [AWS worker runtime](aws-workers.md) | SDK/secret behaviour, delivery claims, partial failures and offline Lambda smoke |
| [Development](development.md) | Local setup, API requests, test commands, worker recovery and dependency updates |

Implemented capabilities, completed deployment checks and remaining operational
and application work: [Project status](checklist.md).
