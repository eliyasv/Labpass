# Verification

Results recorded during local verification on 13–15 October 2026. PostgreSQL
transactions and local browser/queue/email integrations use real services.
AWS API responses and Terraform resources use offline stand-ins. GitHub workflow
execution, AWS deployment and recovery have not been verified.

## Booking correctness and authentication

The capacity test holds the inventory row in a separate transaction, checks out
100 PostgreSQL worker connections and requires the database to report all 100
waiting on locks before release. For 20 seats, it verifies exactly 20 successful
bookings, 80 `workshop_full` conflicts, 20 outbox events and 20 idempotency keys,
with reserved-count/booking-count agreement. This demonstrates capacity safety
under database contention; HTTP throughput has not been measured.

Real transactions also cover:

- Same-key retries, different-key duplicate bookings, user-scoped keys and payload mismatch.
- Cancellation retries, cancellation/booking races and capacity changes below reservations.
- Unique/bounds constraints, outbox persistence failure and injected pre-commit failures.
- Migration upgrade/downgrade/upgrade and Alembic metadata checks.
- Salted password hashes, rehashing, generic credential errors and passwordless-account denial.
- Concurrent/case-only registration, session expiry/rotation/revocation and role changes read from the database.
- Session use across two application instances, cross-user denial and rejected role injection.
- Missing/hostile Origin, incorrect CSRF, rejected legacy identity headers and credential absence from responses/logs.

The authentication migration was tested against a committed legacy dataset with
case-conflicting users. A rejected upgrade preserved both users and the previous
schema revision. Readiness tests reject missing authentication and outbox/delivery
schema columns, then recover after migration.

Admin CLI imports/options and database provisioning were exercised. The interactive
hidden-password prompt was not tested through a human terminal.

Failure hooks run around real transactions. Physical network loss during COMMIT,
database failover and abrupt process termination were not injected. Alembic
metadata checks have normal detection limits; constraints are also exercised
directly. No alternate Python/PostgreSQL version matrix was tested.

## Browser and HTTP flows

Eight Chromium tests run against the production frontend container and real
API/PostgreSQL services. They cover registration/login, session reload, cookie
flags, CSRF/Origin denial, admin authorization, full inventory, safe rendering of
HTML-like titles, capacity validation, cancellation/rebooking and logout.

Lost-response tests drop the response after a real booking commit. Retrying the
same key recovers that booking even when inventory is full or a displayed history
page omits it. Cancelling the recovered booking retires its key; rebooking uses a
new key. Delayed requests cannot overwrite a newer account's UI state.

The HTTP smoke also passed immediately after an API container restart. Readiness
polling has a bounded deadline, retries connection errors/503 and rejects unexpected
statuses or payloads; booking mutations are not automatically retried.

Frontend contract generation, strict compilation, formatting and production builds
passed. Desktop and 390px Chromium checks found no page runtime errors or
horizontal overflow. Firefox, WebKit, public HTTPS cookie behaviour, a full
accessibility audit, forced backend IP changes and browser crashes remain untested.
Full multi-page datasets and the complete native Vite authentication flow were
not exercised. Generated TypeScript types do not validate runtime JSON responses.

## Confirmation processing

Competing relay tests overlap publication while holding different PostgreSQL row
locks. Consumer tests overlap an actual committed delivery claim with an in-flight
sender. Reclaimed claims fence stale owners from updating newer results.

| Outcome | Evidence |
| --- | --- |
| Booking survives email failure | Publication/send failures retain the booking and inventory transaction |
| Known duplicate does not resend | Sent/skipped claims are acknowledged; local smoke captures one confirmation after replay |
| Failed work remains recoverable | Bounded retries, lease expiry, poison validation and guarded operator resets are exercised |
| Local poison messages reach the DLQ | ElasticMQ redrive passed after bounded receives; the record remained available for inspection |
| Local queue/mail data survives restart | A DLQ record and three captured confirmations survived clean service restarts |
| Cloud handler returns retryable failures | SDK shape validation covers source ARN checks, mixed batches of 3/10, SES rejection, missing acceptance IDs and partial failures |
| Dependency outages do not multiply initialization | One secret/initialization failure defers the remaining batch without repeated setup or raw upstream logging |

Cloud adapter tests use boto3 Stubber and prohibit SDK HTTP requests. They verify
credential refresh, resolved HTTPS endpoints despite overrides, TLS parameters
and record admission before/after secret retrieval. Cancellation observed before
claiming suppresses the send.

SES acceptance followed by a failed database completion leaves a live claim and
retryable record. A later retry can send another email. Owner fencing cannot
revoke an already-running send. Physical network loss, clock jumps, process kill
during sending, broker corruption, disk loss and abrupt host failure were not
injected. Local persisted volumes are not backups.

Runtime contracts: [AWS workers](aws-workers.md).
Recovery and isolated DLQ exercise: [Development](development.md#worker-recovery).

## Database and host boundaries

Privilege tests create fresh PostgreSQL databases with a non-superuser bootstrap
operator holding CREATEROLE. Real runtime connections exercise authentication,
booking/retry/cancellation, publication and duplicate suppression. Runtime roles
are denied DDL, truncation and migration-table access; workers are denied
inventory writes. An injected grant failure is recoverable by rerunning bootstrap.
Secrets Manager responses remain stubbed.

Host-helper tests execute the shell script with AWS/Docker stand-ins. They cover
immutable image pulls, instance-role credential selection, ECR-auth cleanup after
errors, container limits, explicit operator jobs, missing configuration and
shutdown without readable deployment configuration. Relay validation succeeds
without SES settings. SSM starts independently of Docker package installation.

All four rendered startup scripts passed shell syntax checks and fit the 16 KiB
user-data limit. API/relay units passed `systemd-analyze verify` with staged helper
and dependency units. An isolated API container returned liveness 200 and sanitized
readiness 503 without cloud credentials/network under its runtime limits.
These checks do not boot EC2 or validate AWS package, SSM, ECR or logging access.

## Infrastructure and release checks

| Suite | Latest recorded result | Coverage |
| --- | --- | --- |
| Backend | 180 passed | Real PostgreSQL, including the Alpine API test target's production application libraries |
| Chromium | 8 passed | Browser booking/auth/admin flows against real local services |
| Script regressions | 66 passed | Readiness, host-helper and release security/failure cases |
| Foundation Terraform | 48 passed | Five module contracts, combined workloads, isolation, IAM scopes and invalid inputs |
| Delivery Terraform | 7 passed | OIDC trust, state storage, scoped release roles and input guards |
| Security policy/installer | 9 passed | Action pins, credential boundaries, scanner gates, exception scope/expiry and verified tool extraction |

Terraform formatting and provider-schema validation passed for both roots.
Infrastructure tests use a mock AWS provider, fictional identifiers and in-memory
state. Combined tests verify frontend/ALB certificate wiring without dependency
cycles, component identities, stable public outputs and disabled initial polling.
SES verified, unverified and pending-DKIM cases are isolated.

Release tests reject stale commits, unsupported refs/retries, missing environment
protections, unsafe Terraform actions/fields, resource-address moves, mismatched
manifests and invalid migration targets. They verify that migration failure
prevents apply, fleet checks wait for numeric template versions, and frontend
publication retains old assets and writes HTML last. AWS/GitHub calls use offline
stand-ins; effective permissions and live rollout behaviour remain unverified.

## Dependency and image security

Runtime/development/security-tool Python audits and the JavaScript audit reported
no known vulnerabilities at verification time. Git history/source secret scans,
Ruff, Bandit and actionlint passed. Full-workload configuration scanning passed
with the five file-scoped, expiring entries in
[Trivy exceptions](../security/trivy-exceptions.yaml).

| Image | Initial high-severity package findings | Remediated result |
| --- | --- | --- |
| API | 48 findings representing 12 distinct advisories | Zero vulnerabilities at every severity; no secret findings |
| Lambda | 37 findings representing 22 distinct advisories | Zero vulnerabilities at every severity; no secret findings |

API remediation uses a digest-pinned Python 3.14/Alpine 3.24 base and hash-verified
binary wheels; the real database suite verified the application libraries on
musl. Lambda retains the AWS Python 3.14 base with packages updated from the
pinned `2023.12.20261013` Amazon Linux repository. Both release images check
installed dependency consistency before removing pip and ensurepip. Lambda's
emulator is confined to its `local` target.

Trivy 0.76.0 scanned vulnerabilities and secrets. No image vulnerability exceptions
or `--ignore-unfixed` option were used. Scan results describe the image inventory
and advisory database at verification time; future dependency/base updates require
fresh scans.

The Lambda smoke passed direct handler and real emulator requests as UID/GID
10001, with a read-only root filesystem, writable `/tmp`, no published ports and
external networking disabled. It checks imports, CA parsing, empty batches and
retryable failures for missing configuration/insufficient time. It does not
exercise the AWS Lambda service.

## Deployment and operational limits

- AWS orderability/quotas, private networking, RDS TLS handshakes, credential rotation and effective IAM remain unverified.
- CloudFront/S3/OAC authorization, public DNS delegation, ACM issuance, ALB origin rejection and public browser sessions require deployed checks.
- GitHub rulesets/environments, OIDC, restricted SSM migrations, saved-plan application, EC2 refreshes and Lambda alias updates require live validation.
- SES/DKIM verification, sandbox restrictions, mailbox delivery and real SQS partial failures/redrive remain unverified.
- Login/registration throttling, email verification/recovery and scheduled session cleanup are unimplemented.
- Load/latency measurements, metric-driven scaling, reconciliation/queue/latency alarms and backup restoration remain pending.

Run commands: [Development](development.md), [Terraform](../infra/README.md#offline-checks)
and [offline Lambda smoke](aws-workers.md#run-offline).
Deployment configuration: [CI/CD and release security](delivery.md).
