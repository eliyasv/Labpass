# Project status

[Architecture and component flows](architecture.md) ·
[Deployment and test evidence](verification.md).

## Implemented

| Capability | Current behavior | Trade-off or limit |
| --- | --- | --- |
| Availability and scaling | Two-AZ ALB/API tier, instance replacement and rolling refreshes; bounded Lambda concurrency | Single-AZ RDS, shared NAT and one baseline relay; no traffic-driven EC2 scaling policy |
| Releases | Tests/scans, OIDC roles, approvals, immutable images, saved-plan verification, migrations and rollout checks | Existing workloads only; no automatic rollback; migrations must support overlapping API versions |
| Runtime access | Private compute/database, separate IAM/SQL roles, Secrets Manager, verified RDS TLS and SSM | Origin token remains in state/plans; deployed secret rotation is unverified |
| Confirmations | Transactional outbox, SQS retries/DLQ and Lambda delivery claims | SES acceptance followed by a failed database update can duplicate an email |
| Booking and authentication | Atomic capacity updates, idempotent reservations/cancellation, password hashing, database sessions and CSRF/Origin checks | Popular-workshop writes serialize; ownership verification, account recovery and distributed throttling are absent |
| Frontend | Static React UI, private S3/CloudFront delivery, generated API types and real-backend Chromium checks | Types do not validate runtime JSON; other browsers and a full accessibility audit are untested |
| Operations and recovery | Component logs, SES metrics, readiness checks, RDS backups/deletion protection and versioned Terraform state | No operational alarms, demonstrated restore targets or measured HTTP capacity |

## Improvement priorities

### Remaining infrastructure and operations work

1. Add actionable alarms for API latency/errors, healthy targets, DB connections,
   outbox backlog, queue age/DLQ, Lambda failures and inventory reconciliation;
   define SLOs and alert routing.
2. Document and exercise database restoration and release recovery; measure
   recovery time and recoverable data loss before choosing additional redundancy.
3. Evaluate Multi-AZ RDS, per-AZ NAT and a second relay against uptime requirements.
4. Measure HTTP load/latency, lock waits and connection headroom before tuning
   pools or adding metric-driven scaling. Define retention for idempotency,
   outbox/delivery records and deployed images.
5. Add edge filtering and distributed authentication throttling; schedule and test
   secret rotation, and implement SES feedback handling.

## Remaining deployment validation

- [ ] Verify repository ruleset enforcement for required CI, PR review and CODEOWNERS.
- [ ] Exercise direct S3 denial, ALB origin-bypass rejection and public cache/cookie security checks.
- [ ] Verify deployed credential rotation, connection headroom and dependency-outage recovery.
- [ ] Inject AWS SQS partial failures/poison messages and verify redrive to the DLQ.
- [ ] Exercise migration failure and partial-rollout recovery on AWS.

## Remaining application work

- [ ] Email ownership verification and account recovery.
- [ ] Scheduled cleanup of expired sessions.
