# Technical documentation

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Booking invariants, authentication, transaction boundaries, failure scenarios and AWS design |
| [Infrastructure](infrastructure.md) | Network isolation, Multi-AZ boundaries, scaling limits, repositories, queues and database configuration |
| [AWS workers](aws-workers.md) | Worker entry points, SDK/secret behaviour, delivery claims, partial failures and offline Lambda smoke |
| [Database runtime](database-runtime.md) | RDS configuration, role privileges, API credentials, bootstrap and migrations |
| [Application hosting](application-hosting.md) | ALB/EC2, instance roles, service supervision, operator jobs and logs |
| [Frontend delivery](frontend-delivery.md) | Private S3, CloudFront routing, DNS/TLS, origin restrictions and frontend publication |
| [Confirmation worker deployment](confirmation-worker.md) | Lambda versions, SQS activation, SES/DKIM, scoped permissions and delivery metrics |
| [CI/CD and release security](delivery.md) | Security gates, OIDC roles, protected environments, private plans and release ordering |
| [Development](development.md) | Local setup, API requests, test commands and worker recovery |
| [Terraform](../infra/README.md) | Provider versions, offline checks and state/account configuration |
| [Terraform modules](../infra/modules/README.md) | Resource ownership, typed interfaces, dependencies and verification |
| [Verification](verification.md) | Live AWS evidence, booking/recovery regressions, security checks and unverified behaviour |
| [Project status](checklist.md) | Implemented capabilities, completed AWS checks and remaining application/operations work |
