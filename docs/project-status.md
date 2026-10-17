# Project status

Deployment and test evidence: [Verification](verification.md).

## Implemented

| Area | Implemented capability | Trade-off or limit |
| --- | --- | --- |
| Infrastructure | Five Terraform modules for networking, database/access, API/relay hosting, frontend delivery and confirmations; separate delivery state | Initial provisioning and database bootstrap are separate from application releases |
| Availability | ALB and two API instances across two AZs; readiness checks and ASG instance replacement | Single-AZ RDS, one shared zonal NAT and one baseline relay leave shared failure points |
| Scalability | API ASG supports 2–4 instances, relay ASG 1–2; Lambda has bounded SQS concurrency | No traffic-driven EC2 scaling policy; HTTP throughput and database connection headroom are unmeasured |
| Delivery | CI dependency/secret/image scans, OIDC roles, approvals, private saved plans, digest-pinned images and rolling releases | No automatic rollback; migrations must remain compatible with the old fleet during rollout |
| Cloud runtime security | Private compute/database, scoped IAM and SQL roles, role-specific secret refresh, verified RDS TLS and SSM access | Origin token is stored in Terraform state; live secret rotation and negative access tests remain unverified |
| Confirmations | Transactional outbox, competing relays, SQS retries/DLQ, Lambda partial failures, durable delivery claims and duplicate suppression | At-least-once processing; SES acceptance followed by failed DB completion can duplicate an email; AWS failure/redrive tests remain outstanding |
| Booking API | Transactional capacity enforcement, one active booking per user/workshop, idempotent retries and cancellation | PostgreSQL is the shared inventory store; writes to a popular workshop serialize on its row lock |
| Authentication | Argon2id, database sessions, ownership/admin checks, Secure cookies, Origin and CSRF validation | No distributed authentication throttling, email ownership verification or account recovery; WAF is not configured |
| Frontend | Workshop browsing, booking/history/cancellation and admin capacity management with real-backend browser tests | Generated API types do not validate runtime JSON; Firefox/WebKit and a full accessibility audit are untested |
| Observability | Component CloudWatch logs, Lambda delivery logs, SES metrics and ALB readiness checks | No operational alarms or established SLOs; relay EC2 health does not prove outbox publication |
| Recovery | Seven-day RDS backup retention, deletion protection, final-snapshot defaults and versioned Terraform state | Restore procedures and recovery targets have not been demonstrated; state versioning does not back up application data |

Product scope and consistency limits: [Architecture](architecture.md).
Inputs and operator commands: [Infrastructure](../infra/README.md),
[Development](development.md) and [Delivery](delivery.md).

## Improvement priorities

| Priority | Change | Purpose |
| --- | --- | --- |
| 1 | Actionable CloudWatch alarms and investigation runbooks | Detect booking failures, unhealthy targets and delayed confirmations |
| 2 | RDS restore and release-failure exercises | Measure recovery time and potential data loss; validate recovery procedures |
| 3 | Evaluate Multi-AZ RDS, per-AZ NAT and a second relay | Reduce shared failure points where uptime requirements justify the recurring cost |
| 4 | Load tests, connection-pool tuning and measured autoscaling | Scale against demonstrated bottlenecks without overwhelming PostgreSQL |
| 5 | Distributed authentication throttling, edge filtering and tested secret rotation | Strengthen public access and credential handling; verify S3 and ALB access restrictions |

## Remaining deployment validation

- [ ] Confirm repository ruleset enforcement for required CI, PR review and CODEOWNERS.
- [ ] Exercise direct S3 denial, ALB origin-bypass rejection and public cache/cookie security checks.
- [ ] Verify live secret rotation, database connection headroom and service-outage recovery.
- [ ] Inject SQS partial failures/poison messages and verify AWS redrive to the DLQ.
- [ ] Exercise migration failure and partial-rollout recovery on AWS.

## Remaining infrastructure and operations work

- [ ] Edge request filtering and distributed login/registration abuse controls.
- [ ] CloudWatch latency/errors, healthy targets, DB connections, inventory reconciliation, outbox backlog, queue age/DLQ and Lambda alarms.
- [ ] Backup/restore runbook and a restoration exercise; verify migration/data rollback limits.
- [ ] k6 load/latency measurements, capacity/pool tuning and metric-driven scaling policies.
- [ ] Define idempotency/outbox/delivery retention and deployed-image retention policies.
- [ ] Secret-rotation scheduling, SES feedback handling and alert routing.

## Remaining application work

- [ ] Email ownership verification and account recovery.
- [ ] Scheduled cleanup of expired sessions.
