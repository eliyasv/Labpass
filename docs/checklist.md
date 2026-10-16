# Project status

Implementation and verification as of 16 October 2026. AWS deployment, the
booking/email path and a protected GitHub Actions release have been verified.
Evidence and verification limits: [Verification](verification.md).

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

## Verified on AWS

- [x] DNS and ACM-backed HTTPS routing through CloudFront to S3 and the API.
- [x] Workshop management, seat reservation and cancellation through the deployed frontend.
- [x] Private RDS access, database bootstrap and runtime connections with verified TLS.
- [x] EC2 startup, ECR pulls, SSM migration execution, healthy ALB targets and completed fleet refreshes.
- [x] SQS-to-Lambda processing, SES domain/DKIM verification and received reservation email.
- [x] Required-reviewer/dev-only environments, OIDC roles and a complete saved-plan release with Lambda alias update.

## Remaining deployment validation

- [ ] Confirm repository ruleset enforcement for required CI, PR review and CODEOWNERS.
- [ ] Exercise direct S3 denial, ALB origin-bypass rejection and public cache/cookie security checks.
- [ ] Verify live secret rotation, database connection headroom and service-outage recovery.
- [ ] Inject SQS partial failures/poison messages and verify AWS redrive to the DLQ.
- [ ] Exercise migration failure and partial-rollout recovery on AWS.

## Remaining application and operations work

- [ ] Edge request filtering and distributed login/registration abuse controls, email verification/recovery and scheduled session cleanup.
- [ ] k6 load/latency measurements, capacity/pool tuning and metric-driven scaling policies.
- [ ] CloudWatch latency/errors, healthy targets, DB connections, inventory reconciliation, outbox backlog, queue age/DLQ and Lambda alarms.
- [ ] Backup/restore runbook and a restoration exercise; verify migration/data rollback limits.
- [ ] Define idempotency/outbox/delivery retention and deployed-image retention policies.
- [ ] Secret-rotation scheduling, SES feedback handling and alert routing.
