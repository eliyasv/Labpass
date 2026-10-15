# Technical documentation

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Booking invariants, authentication, transaction boundaries, failure scenarios and AWS target |
| [Infrastructure](infrastructure.md) | Implemented Terraform resources, network isolation, queue settings and integration status |
| [AWS workers](aws-workers.md) | Runtime configuration, secret retrieval, TLS, IAM scopes and Lambda/SQS contracts |
| [Database runtime](database-runtime.md) | RDS configuration, role privileges, API credentials, bootstrap and migrations |
| [Application hosting](application-hosting.md) | ALB/EC2, instance roles, service supervision, operator jobs and logs |
| [Frontend delivery](frontend-delivery.md) | Private S3, CloudFront routing, DNS/TLS, origin restrictions and frontend publication |
| [Confirmation worker deployment](confirmation-worker.md) | Lambda versions, SQS activation, SES/DKIM, scoped permissions and delivery metrics |
| [Development](development.md) | Local setup, API requests, test commands and worker recovery |
| [Terraform](../infra/README.md) | Provider versions, offline checks and state/account configuration |
| [Project checklist](checklist.md) | Completed implementation and remaining deployment work |

## Verification records

Results are recorded per implementation stage. Each backend total is a snapshot
of the suite at that stage. AWS deployment and recovery remain unverified.

| Stage | Evidence |
| --- | --- |
| [Booking API](milestone-1.md) | 25 PostgreSQL tests; 100 concurrent lock waiters competing for 20 seats |
| [Authentication](milestone-2.md) | 63 backend tests; cookie sessions, Origin/CSRF, ownership and migration failures |
| [Frontend](milestone-3.md) | 8 Chromium tests against the real API/database; lost-response retry and cancellation/rebooking |
| [Local confirmations](milestone-4.md) | 93 backend tests; competing relays, delivery fencing, actual queue redrive and email capture |
| [Cloud worker preparation](milestone-4b.md) | 135 backend tests, 9 smoke regressions, image builds and an offline Lambda runtime smoke |
| [Terraform foundation](milestone-5a.md) | Provider-schema validation and 4 mocked infrastructure tests |
| [Database and runtime access](milestone-5b.md) | 178 backend tests, 9 smoke regressions, 7 mocked Terraform tests and container verification |
| [Application hosting](milestone-5c.md) | 180 backend tests, 27 script tests, 14 mocked Terraform tests, rendered startup/unit checks and offline container verification |
| [Frontend delivery](milestone-5d.md) | 28 mocked Terraform tests, frontend contract/build checks and 27 script regressions |
| [Confirmation workload](milestone-5e.md) | 28 mocked Terraform tests, 43 combined frontend/worker checks, runtime configuration validation and 27 script regressions |
