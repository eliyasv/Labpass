# Project checklist

Updated 14 October 2026 (Asia/Kolkata). Milestones 1–3 and the local part of
Milestone 4 are complete, with Milestone 4B cloud worker code verified offline.
AWS email deployment remains pending.
Evidence and remaining limits are recorded in [milestone-1.md](milestone-1.md)
and [milestone-2.md](milestone-2.md), with frontend evidence in
[milestone-3.md](milestone-3.md).
Local background processing is recorded in [milestone-4.md](milestone-4.md).
Cloud worker evidence is in [milestone-4b.md](milestone-4b.md).

## Milestone 1: local booking correctness

- [x] Inspect repository and applicable instructions; preserve existing `test.py`.
- [x] Explain architecture, assumptions, repository layout and phased plan.
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
- [x] Separate review of every changed file and affected flows; fixes rechecked.
- [x] Local run and inspection instructions; verification services stopped with data retained.

## Accepted decisions and limits

- PostgreSQL owns seats and bookings. DynamoDB inventory is excluded without a new requirement.
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
- Local Git commits capture the verified baseline; development now uses `dev`
  tracking `origin/dev`. No PR or push is performed by this milestone.
  See [Git workflow](git-workflow.md) for grouping and future milestone commits.
- Compose was downloaded temporarily for verification; install the official plugin for normal use.
- Passing tests establish tested scenarios, not proof of correctness or production readiness.

## Milestone 2: authentication

- [x] Registration and login with verified package APIs and pinned dependencies.
- [x] Password hashing, real authentication and explicit admin CLI; remove development identity.
- [x] DB sessions, cookie policy, Origin/CSRF defenses, logout and login rotation.
- [x] Authentication, cross-user denial, admin authorization and session failure tests.
- [x] Additive migration, legacy preservation and case-conflict failure checks.
- [x] Seed only a workshop; use generated credentials in the real HTTP smoke test.
- [x] Readiness requires auth schema; validate Origin/port and local-only insecure configuration.
- [x] Documentation and separate review; recheck affected tests and containers.
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
- [x] Separate review and regression checks for lost-response recovery and rebooking.

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
- [ ] Provision/verify real SQS/Lambda/SES/DLQ, policies, RDS TLS and secret rotation after authorization.
- [x] Test consumer duplicates, retry/lease expiry, poison validation and partial batch failure.
- [x] Actual queue redrive, duplicate capture smoke, queue/mail persistence after restart.
- [x] Operator resets refuse sent deliveries/live leases; failure or expired-lease recovery tested.
- [x] Suppress confirmations when cancellation is observed before sending; document the in-flight race.
- [x] Document SES-success/recording-failure ambiguity; do not promise exactly-once email.

## Milestones 5–6: infrastructure, delivery and operations

- [ ] Confirm AWS region, domain and budget before selecting network/availability options.
- [ ] Compare current NAT/endpoints/RDS Multi-AZ costs and failure paths.
- [ ] Terraform for private S3/OAC, CloudFront API forwarding/no cache and TLS.
- [ ] ALB, two-AZ private EC2 ASG, ECR retrieval and explicit private egress/bootstrap paths.
- [ ] RDS engine availability/version, private network, restricted DB roles and verified TLS.
- [ ] Roles, runtime Secrets Manager retrieval, SSM and scoped GitHub OIDC trust.
- [ ] Distributed login/registration abuse controls, email verification/recovery and session cleanup.
- [ ] Terraform formatting/validation and provider locks; IAM/network review.
- [ ] GitHub Actions CI, immutable image digests, single migrations, release ordering and smoke tests.
- [ ] k6 tests with real overlap and measured results; capacity/pool tuning.
- [ ] CloudWatch latency/errors, targets, DB connections, outbox, queue age/DLQ and Lambda alarms.
- [ ] Backup/restore runbook and actual restoration exercise; migration rollback limits.
- [ ] Obtain explicit authorization before provisioning, AWS deployment or resource destruction.
