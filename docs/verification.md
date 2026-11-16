# Verification

Local verification was recorded on 13–16 October 2026; live AWS deployment and
release verification on 16 October. These are recorded results, not current
availability or security-scan claims.

## Live AWS verification

| Outcome | Evidence |
| --- | --- |
| Protected release completes | [Release run](../images/relessesucces.png) completes preflight, CI, OIDC image publication, saved-plan application, migration, rollout and readiness verification |
| CI gates complete | [CI run](../images/ci-success.png) passes security, backend, frontend, Terraform and image checks |
| API traffic reaches healthy private instances | [ALB resource map](../images/alb-resoursemap.png) shows two healthy targets; [VPC map](../images/vpc-resoursemap.png) shows the subnet and routing tiers |
| Frontend and API served through HTTPS | [Application](../images/liveapplication.png) and [CloudFront origins](../images/cloudfront-origin.png); registration, login, workshop management, booking and cancellation exercised through the public hostname |
| Booking data and delivery claims use RDS | Deployed API readiness, booking mutations and Lambda delivery succeeded with role-specific Secrets Manager credentials and `sslmode=verify-full` |
| Reservation email reaches the recipient | [Lambda delivery log](../images/lamda-confirmation.png) records `sent`; [received email](../images/labpassreservationmail.png) confirms mailbox delivery after SES domain/DKIM verification |

These checks establish successful deployment and the normal booking/email path.
They do not establish measured throughput, AZ failover, backup restoration or
failure recovery under injected AWS outages.

## Infrastructure and release checks

| Area | Method | Important checks |
| --- | --- | --- |
| Terraform | Mocked AWS provider; format/schema validation for both roots | Five module contracts, combined TLS/ALB wiring, IAM scopes, disabled polling, invalid inputs and SES verification guards |
| Release | Subprocess and AWS/GitHub stand-ins | Commit/environment guards, allowed plan actions/fields, manifest checksums, migration target validation, migration-before-apply, numeric fleet versions and HTML-last publication |
| Host startup | Real shell helper with AWS/Docker stand-ins; rendered user-data and systemd validation | Immutable pulls, credential cleanup after failure, container limits, explicit operator jobs, startup-script size and syntax |
| Security controls | Workflow/installer policy tests and configuration scans | Pinned actions/tools, PR credential boundaries, fail-closed scans and scoped expiring exceptions |

Mock tests do not establish effective AWS permissions or recovery during an AWS
outage. The live release establishes the normal deployment path separately.
Security configuration exceptions are recorded in
[Trivy exceptions](../security/trivy-exceptions.yaml); policy tests enforce scope
and expiry.

## Dependency and image security

Python and JavaScript dependency audits, secret scans, Ruff, Bandit and actionlint
passed at verification time. Trivy 0.76.0 scanned image vulnerabilities and secrets,
including unfixed findings, with no image vulnerability exceptions.

| Image | Initial high-severity package findings | Remediated result |
| --- | --- | --- |
| API | 48 findings representing 12 distinct advisories | Zero vulnerabilities at every severity; no secret findings |
| Lambda | 37 findings representing 22 distinct advisories | Zero vulnerabilities at every severity; no secret findings |

The API remediation used a pinned Python/Alpine base and hash-verified binary
wheels, with PostgreSQL tests using the shipped musl libraries. Lambda retained
the AWS Python base with packages from a pinned Amazon Linux repository. Release
images exclude pip/ensurepip and the Lambda emulator. Fresh image/dependency
changes require fresh scans; these results describe the recorded image inventory
and advisory database.

The offline Lambda smoke passed direct handler and runtime-emulator invocations
without external networking, as UID/GID 10001 with a read-only root and writable
`/tmp`. It checks packaging/imports, CA parsing, empty batches and retryable
configuration/time-budget failures; it does not exercise the AWS Lambda service.

## Database and host boundaries

Real PostgreSQL tests bootstrap restricted roles, then exercise runtime
credentials. Runtime roles are denied schema changes, truncation and migration
access; workers cannot write inventory. An injected grant failure is recoverable
by rerunning bootstrap. Secrets Manager responses are stubbed.

All four rendered startup scripts passed shell syntax and user-data size checks;
API/relay systemd units passed validation. An isolated API container returned
liveness 200 and sanitized readiness 503 without cloud credentials/network. These
checks do not boot EC2. The live deployment separately exercised image pulls,
SSM migration execution and logging.

## Confirmation processing

Real PostgreSQL plus ElasticMQ/Mailpit checks cover competing relays, delivery
claims, stale-owner rejection, duplicate suppression, publication/send failures
that retain bookings, guarded recovery and local poison-message redrive. Queue
and mailbox records survived clean local service restarts; volumes are not backups.

Stubbed SDK tests cover source validation, secret refresh, verified TLS, SES
rejection/missing acceptance IDs, mixed-batch failures and initialization failures.
The consumer's cancellation-before-claim and post-send database-failure paths are
exercised. An accepted email followed by a failed completion update can still be
sent again after claim expiry. AWS outage/redrive tests remain outstanding.

## Booking correctness and authentication

The contention test holds the workshop row, starts 100 PostgreSQL worker
connections and verifies that all are waiting on locks before release. With
20 seats it produces **20 bookings and 80 capacity conflicts**, with 20 outbox
records, 20 idempotency keys and matching inventory. This measures database
correctness under contention, not HTTP throughput.

Other real-database checks cover same-key retries, duplicate bookings, cancellation
races, capacity bounds, transaction rollback, migrations, session expiry/rotation,
role/ownership checks and CSRF/Origin rejection. A rejected authentication
migration preserves case-conflicting legacy users and the prior schema revision.
Readiness rejects incomplete schemas and recovers after migration.

## Browser and HTTP flows

Eight Chromium tests use the production frontend container with real API and
PostgreSQL services. They cover login/session reload, browser security checks,
admin operations, booking, capacity changes, cancellation/rebooking and logout.
Lost-response tests recover committed bookings with the original key; delayed
responses cannot overwrite another account's state.

The HTTP smoke passed after an API restart. Readiness polling retries connection
errors/503 within a deadline; writes are not automatically retried. API contract
generation, strict compilation, formatting and production builds passed. Desktop
and 390px Chromium checks found no runtime errors or horizontal overflow.

## Deployment and operational limits

- AZ failover, backup restoration and measured recovery targets have not been demonstrated; RDS and shared NAT remain Single-AZ dependencies.
- Direct S3 denial, unrelated-distribution ALB rejection, public cache/cookie security and repository ruleset enforcement need dedicated deployment checks.
- Live secret rotation, connection headroom, SES rejection, AWS SQS failure/redrive and partial-rollout recovery remain unverified.
- HTTP throughput, metric-driven EC2 scaling, operational alarms, WAF and distributed authentication throttling are absent or unmeasured.
- Physical connection loss during commit/send, clock jumps, abrupt host failures, broker/disk loss and alternate runtime versions were not injected/tested.
- Other browsers, full accessibility, large multi-page datasets, native Vite authentication, forced API address changes and browser crashes remain untested. The interactive admin password prompt was not exercised through a human terminal.

Remaining work: [Project status](project-status.md). Run commands:
[Development](development.md), [Terraform](../infra/README.md#offline-checks) and
[offline Lambda smoke](confirmation-worker.md#run-offline).
