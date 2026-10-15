# Project status

Implementation and local verification as of 15 October 2026. AWS resources have
not been provisioned; live service integration and GitHub protection settings
remain unverified. Evidence: [Verification](verification.md).

## Implemented

| Area | Behaviour |
| --- | --- |
| Booking API | Transactional capacity enforcement, one active booking per user/workshop, idempotent retries and cancellation |
| Authentication | Argon2id, database sessions, ownership/admin checks, Secure cookies, Origin and CSRF validation |
| Frontend | Workshop browsing, booking/history/cancellation and admin capacity management with real-backend browser coverage |
| Confirmations | Transactional outbox, competing relays, durable delivery claims, retries, duplicate suppression and guarded recovery |
| Cloud runtime | SQS/SES adapters, Lambda partial failures, role-specific secret refresh, verified-TLS configuration and restricted database roles |
| Infrastructure | Five Terraform modules covering networking, private RDS, API/relay hosting, S3/CloudFront/DNS/TLS and Lambda/SQS/SES |
| Delivery | Credential-free CI, dependency/secret/image scans, separate OIDC roles, private remote state/plans and controlled runtime releases |

Product scope and consistency limits: [Architecture](architecture.md).
Inputs and operator commands: [Infrastructure](../infra/README.md),
[Development](development.md) and [Delivery](delivery.md).

## Remaining deployment validation

- [ ] Configure GitHub rulesets, reviewer environments and delivery variables; verify OIDC and effective AWS permissions.
- [ ] Verify authoritative DNS, ACM issuance, S3/OAC authorization, origin restrictions and browser flows through CloudFront.
- [ ] Verify RDS orderability, private reachability/TLS, database bootstrap, role-secret refresh and connection headroom.
- [ ] Verify EC2 startup, SSM/ECR/logging access, ALB health and fleet refresh behaviour.
- [ ] Verify Lambda image/VPC access, SES/DKIM/account quotas, email delivery, alias updates and SQS retry/DLQ behaviour.
- [ ] Exercise a complete release, migration failure and partial-rollout recovery.

## Remaining application and operations work

- [ ] Distributed login/registration abuse controls, email verification/recovery and scheduled session cleanup.
- [ ] k6 load/latency measurements, capacity/pool tuning and metric-driven scaling policies.
- [ ] CloudWatch latency/errors, healthy targets, DB connections, inventory reconciliation, outbox backlog, queue age/DLQ and Lambda alarms.
- [ ] Backup/restore runbook and a restoration exercise; verify migration/data rollback limits.
- [ ] Define idempotency/outbox/delivery retention and deployed-image retention policies.
- [ ] Secret-rotation scheduling, SES feedback handling and alert routing.
