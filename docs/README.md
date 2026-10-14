# Technical documentation

| Guide | Contents |
| --- | --- |
| [Architecture](architecture.md) | Booking invariants, authentication, transaction boundaries, failure scenarios and AWS target |
| [Infrastructure](infrastructure.md) | Implemented Terraform resources, network isolation, queue settings and integration status |
| [AWS workers](aws-workers.md) | Runtime configuration, secret retrieval, TLS, IAM scopes and Lambda/SQS contracts |
| [Development](development.md) | Local setup, API requests, test commands and worker recovery |
| [Terraform](../infra/README.md) | Provider versions, offline checks and state/account configuration |
| [Project checklist](checklist.md) | Completed implementation and remaining deployment work |

## Verification records

Results below are verification snapshots for their respective implementation
stages. Earlier test totals are superseded by the later backend suite, not added
together. AWS deployment and recovery remain unverified.

| Stage | Evidence |
| --- | --- |
| [Booking API](milestone-1.md) | 25 PostgreSQL tests; 100 concurrent lock waiters competing for 20 seats |
| [Authentication](milestone-2.md) | 63 backend tests; cookie sessions, Origin/CSRF, ownership and migration failures |
| [Frontend](milestone-3.md) | 8 Chromium tests against the real API/database; lost-response retry and cancellation/rebooking |
| [Local confirmations](milestone-4.md) | 93 backend tests; competing relays, delivery fencing, actual queue redrive and email capture |
| [Cloud worker preparation](milestone-4b.md) | 135 backend tests, 9 smoke regressions, image builds and an offline Lambda runtime smoke |
| [Terraform foundation](milestone-5a.md) | Provider-schema validation and 4 mocked infrastructure tests |
