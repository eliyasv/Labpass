# Project checklist

Updated 15 October 2026. Local application and background processing are complete.
Cloud workers, database access, application hosting and confirmation-workload
configuration are verified offline; AWS deployment remains pending.
Verification records: [Technical documentation](README.md#verification-records).

## Milestone 1: local booking correctness

- [x] Document architecture, repository layout and implementation scope.
- [x] FastAPI browsing, availability, booking/history/cancellation routes.
- [x] Development-only identity explicitly gated; ownership and admin checks.
- [x] Admin workshop creation and safe capacity updates.
- [x] PostgreSQL/SQLAlchemy models, constraints, indexes and initial Alembic migration.
- [x] Transactional inventory locks and one active booking per user/workshop.
- [x] Scoped idempotency keys with payload validation and stable booking identity.
- [x] Booking, inventory, key and pending outbox event commit together.
- [x] Repeated cancellation releases inventory only once.
- [x] Unit and real-PostgreSQL integration tests.
- [x] 100 live database workers observed waiting concurrently for 20 seats.
- [x] Retry conflicts, cancellation/booking/capacity races and rollback tests.
- [x] Migration upgrade/downgrade/upgrade and Alembic metadata check.
- [x] Exact-version runtime and development dependency locks; compatibility check.
- [x] Docker build, startup, health, non-root runtime, seed, HTTP smoke and shutdown.
- [x] Structured request, booking and event IDs; sanitized database errors.
- [x] Local run and inspection instructions.

## Accepted decisions and limits

- PostgreSQL owns seats, bookings and delivery claims.
- Lock order is user, workshop, booking; READ COMMITTED isolation and fresh request sessions.
- Retry returns the original booking ID with its current status; cancellation does not reactivate it.
- Idempotency records have no expiry yet; only successful requests retain keys.
- Free bookings only. No payments, scheduling cutoff, expiry or waitlist in this milestone.
- Milestone 2 removed `X-User-ID` and `LABPASS_DEV_IDENTITY`; all protected routes use sessions.
- Argon2id passwords, eight-hour opaque DB sessions, HttpOnly cookies, Origin and CSRF checks.
- Default cookie policy is Secure; local HTTP exception is restricted to loopback.
- Legacy users are preserved with no passwords and cannot log in; create a new operator account.
- Email ownership, recovery, attempt-rate throttling and scheduled session cleanup remain pending.
- Compose publishes only loopback HTTP and uses a development DB superuser.
  Restricted database roles and verified TLS must precede AWS deployment.
- Direct SQL bypassing services can make the counter disagree with bookings.
  Add reconciliation monitoring before deployment.
- Version locks have no artifact hashes and local base image tags are mutable.
  Delivery will add hash/base digest policies and deploy immutable application image digests.

## Milestone 2: authentication

- [x] Registration and login with verified package APIs and pinned dependencies.
- [x] Password hashing, real authentication and explicit admin CLI; remove development identity.
- [x] DB sessions, cookie policy, Origin/CSRF defenses, logout and login rotation.
- [x] Authentication, cross-user denial, admin authorization and session failure tests.
- [x] Additive migration, legacy preservation and case-conflict failure checks.
- [x] Seed only a workshop; use generated credentials in the real HTTP smoke test.
- [x] Readiness requires auth schema; validate Origin/port and local-only insecure configuration.
- [x] Fix startup race: bounded smoke readiness polling, Compose health wait,
  nine regression tests and HTTP smoke immediately after API restart.

## Milestone 3: frontend

- [x] React/TypeScript/Vite with lockfile and frontend/backend contract checks.
- [x] Workshop availability and booking flow with per-action idempotency keys.
- [x] History, cancellation and admin workshop/capacity management.
- [x] Use existing title/capacity fields; explicitly defer schedules and deadlines.
- [x] Eight real-backend Chromium tests, input/error handling, and build checks.
- [x] Use same-origin `/api` requests with cookie credentials and CSRF state in memory.
- [x] Non-root web proxy, health ordering, preserved API smoke and desktop/mobile review.
- [x] Regression checks for lost-response recovery and rebooking.

## Milestone 4: background processing

- [x] Multiple relays coordinate via database locks and bounded publish attempts.
- [x] Test publication failures, competing relays and publish-before-commit duplicates.
- [x] Persistent local SQS-compatible queue/DLQ, Mailpit capture and background workers.
- [x] Durable PostgreSQL delivery claims with leases, owner fencing and bounded sends.
- [x] Cloud SQS publisher and SES sender reuse stable IDs and PostgreSQL claims.
- [x] Lambda entry point with source validation, partial failures and time admission checks.
- [x] Worker Secrets Manager refresh, sanitized failures, bounded pools and verified TLS configuration.
- [x] Build Lambda image and verify imports/runtime emulator offline as non-root with networking disabled.
- [x] Real-PostgreSQL tests with stubbed AWS responses, including SES acceptance/commit failure.
- [x] Document scoped IAM/DB permissions, private connectivity and mapping/release requirements.
- [ ] Verify deployed SQS/Lambda/SES/DLQ, policies, RDS TLS and secret rotation.
- [x] Test consumer duplicates, retry/lease expiry, poison validation and partial batch failure.
- [x] Actual queue redrive, duplicate capture smoke, queue/mail persistence after restart.
- [x] Operator resets refuse sent deliveries/live leases; failure or expired-lease recovery tested.
- [x] Suppress confirmations when cancellation is observed before sending; document the in-flight race.
- [x] Document duplicate-email risk after SES acceptance followed by completion failure.

## Milestone 5A: Terraform foundation

- [x] Target `us-east-1` with an explicit account guard.
- [x] Document network boundaries and egress/availability trade-offs.
- [x] Two-AZ public/application/isolated-database subnets, one zonal NAT and an S3 gateway endpoint.
- [x] ECR repositories with immutable tags and standard SQS/DLQ matching the worker contract.
- [x] Required account ID, empty default security-group rules and Terraform artifact/state ignores.
- [x] Pin and lock the AWS provider; formatting, validation and offline mock-provider tests.
- [x] Document foundation verification and integration requirements.
- [ ] Configure DNS hosting/delegation and certificate validation.

## Milestone 5B: database and runtime access

- [x] Private encrypted PostgreSQL 18 RDS configuration and target-region orderability lookup.
- [x] Database subnet group, TLS/SCRAM parameters, backups and deletion protection.
- [x] Separate database client security groups and component-specific secret/SQS access.
- [x] RDS-managed master password and runtime secrets initialized outside Terraform state.
- [x] Restricted API/relay/consumer database roles and separate migration schema owner.
- [x] Repeatable bootstrap with a session advisory lock, migrations and explicit table grants.
- [x] Thread-safe API credential refresh, bounded pool, Secure cookies and sanitized outage responses.
- [x] Real-PostgreSQL privilege denial, worker flow and interrupted-bootstrap recovery tests.
- [ ] Verify RDS orderability, network/TLS, IAM and role-secret refresh in AWS.

## Milestone 5C: application hosting

- [x] Optional HTTPS ALB, CloudFront origin prefix-list access and API readiness target group.
- [x] Separate private API/relay ASGs spanning the two application subnets.
- [x] Explicit AMI/digest inputs, numeric template versions and rolling refresh configuration.
- [x] IMDSv2, encrypted root volumes, SSM and scoped ECR/container logging permissions.
- [x] Systemd supervision and resource-bounded non-root containers.
- [x] Bootstrap/migration templates with explicit operator jobs and zero initial service capacity.
- [x] Relay configuration without an SES dependency.
- [x] Mocked hosting tests, host-helper failure checks, rendered startup and container validation.
- [ ] Verify deployed EC2 startup, permissions, ALB health/TLS and refresh behaviour.

## Milestone 5E: confirmation workload deployment

- [x] Optional digest-pinned x86_64 Lambda, numeric published version and stable alias.
- [x] Consumer-role private RDS connectivity and metadata-only runtime environment.
- [x] Exact-sender SES permissions, scoped log writes and function-restricted ECR image retrieval.
- [x] Lambda service ENI access with conditional function-code denial.
- [x] Disabled-by-default SQS mapping, batch/window/visibility contract and shared concurrency limit.
- [x] SES domain, 2048-bit Easy DKIM and three CNAMEs in an existing public hosted zone.
- [x] Configuration-set suppression and delivery/bounce/complaint metrics.
- [x] SES/DKIM activation guards and offline Terraform coverage.
- [ ] Verify deployed image retrieval, VPC/IAM, SES sandbox/quotas/delivery, alias updates and SQS retries/DLQ.

## Remaining milestones 5–6: workloads, delivery and operations

- [ ] Terraform for private S3/OAC, CloudFront API forwarding/no cache and TLS.
- [ ] Origin DNS/ACM and distribution-specific ALB access validation.
- [ ] Verify deployed RDS engine/class availability, private reachability and TLS.
- [ ] Scoped GitHub OIDC trust and release permissions.
- [ ] Distributed login/registration abuse controls, email verification/recovery and session cleanup.
- [ ] Extend Terraform validation/tests and IAM/network review to the complete workload stack.
- [ ] GitHub Actions CI, immutable image digests, single migrations, release ordering and smoke tests.
- [ ] k6 tests with real overlap and measured results; capacity/pool tuning.
- [ ] CloudWatch latency/errors, targets, DB connections, outbox, queue age/DLQ and Lambda alarms.
- [ ] Backup/restore runbook and actual restoration exercise; migration rollback limits.
