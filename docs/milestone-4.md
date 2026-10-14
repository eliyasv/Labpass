# Milestone 4: local background confirmations

Local portion completed 14 October 2026 (Asia/Kolkata), with work/verification
spanning 13–14 October. AWS deployment and internet email delivery are pending.

## What changed and why

Bookings now lead to asynchronous local confirmation emails through a real
SQS-compatible ElasticMQ queue and Mailpit SMTP capture. The existing booking
transaction still commits inventory, booking, idempotency record and event
together. A separate relay publishes due events; a separate consumer claims,
sends and acknowledges them. Neither worker can cancel a booking or decrement
inventory on failure.

Migration `0003` preserves existing data and adds publication retry metadata and
durable email-delivery state. Relays coordinate using PostgreSQL `SKIP LOCKED`,
one event per transaction and at most five events per iteration. Publication
success is recorded after queue acceptance. Failed publishes back off, stop after
five committed attempts, and retain a failed row for operator review. A crash can
roll back attempt bookkeeping and cause republishing of the stable event ID.

Consumers validate an ID/type envelope against authoritative DB data, then commit
a claim before sending. The claim stores a random owner token, 90-second lease
and bounded attempt count. Completion/failure updates are fenced by token and
expiry. Sent/skipped duplicates do not resend. Queue messages are acknowledged
only after processing. The local queue has 120-second visibility and a DLQ after
five receives. Failed events, exhausted sends and expired leases have explicit
inspection/recovery commands. Live leases and sent deliveries cannot be reset.

Cancellation observed before the send claim suppresses the email. Cancellation
during sending can still produce a historical reservation email, whose wording
directs the recipient to current booking status. This race is intentional and
documented; no inventory lock is held across SMTP. Email acceptance followed by
a crash/DB failure can resend after recovery. Exactly-once email is not promised.

Local runtime configuration rejects real AWS endpoints/external SMTP. The SDK
uses explicit dummy credentials, a required local endpoint and disabled SDK
retries. No AWS credential files are read by the application and no paid resource
was provisioned. Mailpit has no internet forwarding configured. Its UI is bound
to loopback; queue/SMTP ports stay internal. Database, queue and mailbox volumes
are retained.

References: [ElasticMQ configuration/persistence](https://github.com/softwaremill/elasticmq),
[Mailpit Docker](https://mailpit.axllent.org/docs/install/docker/),
[Mailpit API](https://mailpit.axllent.org/docs/api-v1/),
[SQS receive/visibility semantics](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/receive_message.html),
and [Lambda partial batch responses](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html).

## Files changed

- `backend/labpass/outbox.py`: stable envelopes, locked publication, bounded backoff.
- `backend/labpass/delivery.py`: DB claims, payload validation, owner fencing,
  suppression, send recovery and Lambda-compatible partial-batch response core.
- `backend/labpass/queue.py`, `mail.py`, `background_config.py`, `background.py`:
  local SDK/SMTP adapters, endpoint safeguards, worker loops, health and recovery CLI.
- `backend/labpass/models.py`, `migrations/versions/0003_background_delivery.py`:
  retry fields, delivery table and state constraints.
- `backend/labpass/app.py`: readiness requires the new background schema.
- `backend/tests/test_background.py`, `test_queue.py`, `test_migrations.py`:
  real-PG concurrency/failure/recovery tests, SDK parameter checks and migrations.
- `backend/requirements.in`, `requirements.lock`: boto3 and exact transitive versions.
  The dev lock was regenerated against the runtime constraints; its versions stayed the same.
- `compose.yaml`, `local/elasticmq.conf`, `.env.example`: queue, DLQ, mailbox,
  workers, health dependencies, persistence and configurable mailbox UI port.
- `scripts/smoke-background.py`, `check-background-dlq.py`: real captured-email,
  duplicate and opt-in isolated poison/redrive checks.
- `README.md`, `docs/architecture.md`, `docs/checklist.md`, this report: operation,
  assumptions, evidence, recovery and remaining scope.

Frontend code and its API snapshot/types were unchanged and still match OpenAPI.
Existing `test.py` is untouched. Git is now initialized; `git status --short`
shows project source files untracked. No milestone commit or PR was created.

## Separate review findings and fixes

Reviewed every changed module/configuration and the model/migration agreement;
traced booking commit → relay → queue → claim → SMTP → completion → acknowledgement,
plus cancellation, duplicate redelivery, poison events and operator reset flows.

| Severity | Finding | Resolution/evidence |
| --- | --- | --- |
| High | A short requeue delay could exhaust receives while a post-send failure still held a live lease | Unknown/busy failures retain 120-second visibility, beyond the 90-second lease; regression checks the retry delay |
| High | An expired owner could record the result of a newer delivery claim | Completion/failure require current token and unexpired lease; real-PG reclaim/fencing test passes |
| High | Operator recovery must not reset a live sender or known sent email | Guarded SQL resets only failed/expired state; tests reject live/sent claims and fence the old expired owner |
| High | Backend readiness could pass on `0002` although booking ORM now needs `0003` | Readiness queries outbox retry/delivery columns; downgrade/readiness recovery test passes |
| High | Explicit dummy keys alone do not prevent SDK inspection of shared AWS configuration | Use a dedicated SDK session with shared config/credential files set to `/dev/null` and profile disabled; regression checks attempted file reads under hostile AWS environment settings |
| Medium | Worker-provided recipient/payload could route mail incorrectly | Queue contains only ID/type; DB payload IDs and normalized recipient are checked against booking/user; tampered payload test passes |
| Verification | Mailpit's `total` is the whole mailbox, not matching search results | Corrected smoke to use `messages_count`; repeated/default stack capture checks pass with multiple existing emails |
| Operations | Queue/mail data could disappear after restart once outbox publication was committed | Enabled retained storage; actual queue/Mailpit restart retained a DLQ record and three captured confirmations |

The review also checked lock order/isolation, rollback boundaries, retries after
lost acknowledgements, schema nullability/constraints, sanitized logs, sender
header safety, local-only endpoints, signals, non-root workers, image contexts,
health dependencies and absence of CORS/API contract changes. Fencing protects
DB state; it cannot revoke an already-running SMTP send. An expired slow sender
can still overlap a new sender, which is part of the duplicate-email limitation.

## Commands actually executed and results

| Command/check | Observed result |
| --- | --- |
| Official docs/installed API and dependency inspection | Verified queue configuration, boto3 methods, Mailpit search fields and Lambda response contract |
| Runtime/dev `pip-compile`, then locked installation | boto3/botocore 1.43.112 installed with pinned dependencies; existing package versions retained |
| Initial native test runner inside sandbox | PostgreSQL socket bind denied; retried with the required sandbox approval |
| `bash scripts/test-local.sh -q` before SDK/operator additions | 88 passed; 100 actual concurrent booking workers still verify 20 seats |
| Before final SDK file-isolation fix, `bash scripts/test-local.sh -q` | 92 passed in 3.78s |
| Final `bash scripts/test-local.sh -q` | **93 passed in 3.66s**, no warnings; temporary server stopped, files retained |
| Focused SDK tests | 3 passed; parameters verified using botocore Stubber and shared-file isolation verified under overridden AWS env, without network/AWS calls |
| `ruff check backend scripts`; `ruff format --check backend scripts` | All checks passed; 36 files formatted |
| Host `python -m pip check` | No broken requirements found |
| Existing startup regression suite | 9 passed in 0.08s |
| OpenAPI export `--check`; frontend `npm run check-contract` | Existing snapshot/generated types still match |
| Isolated Compose `up --build --wait --wait-timeout 120`, API 8003/mail 8026 | Migration exited 0; API/web/relay/consumer/mail healthy; local SQS operations succeed |
| First captured-email smoke | Real booking published, sent and captured once |
| Expanded smoke before count fix | Failed because mailbox total was used; diagnostics showed one matching email and two overall |
| Corrected expanded smoke on isolated stack | Publication, SMTP capture and duplicate suppression passed |
| Isolated opt-in poison check | Poison message reached configured DLQ after bounded receives; retained for inspection |
| Restart isolated queue and Mailpit, recheck persistence | One DLQ poison record and three captured confirmations survived restart |
| Default Compose rebuild/start, seed and background smoke | Applied `0003` to retained DB; real email capture and duplicate suppression passed on default stack |
| Existing HTTP smoke on default stack | Register/login/me/booking/retry/history/cancel/logout passed |
| Default `alembic check`; consumer `id`; background `status` | No schema drift; UID/GID 10001; pending/failed outbox counts 0, sent 1 and skipped 4 at inspection |
| Default rebuild/smoke after final SDK isolation, status and container `pip check` | Capture/duplicate check passed again; pending/failed 0, sent 2, skipped 4; no broken requirements |
| Isolated verification Compose `stop`, then default `ps -a` | Test services stopped; volumes retained; default API/web/mail/relay/consumer remain healthy |

Concurrency/failure tests use actual PostgreSQL transactions and thread overlap.
External queue/mail acceptance is injected in focused crash tests; the end-to-end
smokes use actual ElasticMQ and Mailpit. A barrier inside two publication calls
requires both relay transactions to reach publication while holding different
real locks. Competing consumers overlap an actual committed claim with an
in-flight sender. No SQLite/database mock replaces booking or delivery tests.

## Untested behavior and remaining scope

- Real AWS SQS/SES/Lambda behavior, IAM, SES identities/sandbox rules, Lambda
  packaging/event-source mapping and private DB networking are not implemented
  or verified. The tested partial-batch function is a reusable core, not a deployed handler.
- Emulator durability was tested across clean service restarts, not host/disk
  loss, broker corruption or abrupt power loss. Local volumes are not backups.
- Long-running sends, clock jumps, process kill during SMTP and physical network
  loss during DB COMMIT were not injected. Tests exercise the resulting claim/
  commit failure paths with controlled hooks. Duplicate-email ambiguity remains.
- Source/SDK parameters were verified; no load test, fleet-scale throughput,
  distributed attempt throttling, reconciliation or CloudWatch alarms exist yet.
- Relay attempt bookkeeping rolls back on process/DB failure; the five-attempt
  limit counts committed attempts rather than arbitrary crashes.
- Cancellation after the check can race with a send. Mail wording describes the
  original reservation and does not assert that it remains active.
- Outbox/delivery records have no retention policy yet. Manual replay can resend
  uncertain email outcomes; validate/fix poison records before redriving them.
- Migration downgrade removes retry/delivery evidence and is not a safe operational
  rollback. Python artifact hashes, base-image digests and restricted DB roles
  remain delivery hardening work.

## Run and inspect locally

The default stack serves LabPass at <http://127.0.0.1:8000/> and Mailpit at
<http://127.0.0.1:8025/>. Register/login, reserve an available seat, wait a few
seconds and inspect its email before cancelling. Captured mail stays local.
The temporary Compose binary is still used because the plugin is absent.

```bash
/tmp/labpass-compose/docker-compose up --build --wait --wait-timeout 120
/tmp/labpass-compose/docker-compose exec -T consumer python < scripts/smoke-background.py
/tmp/labpass-compose/docker-compose exec relay python -m labpass.background status
/tmp/labpass-compose/docker-compose logs --tail=30 relay consumer
```

The smoke cleans up its active booking/session while retaining its account,
history, event and captured email. Recovery commands and limits are in README.
Use this isolated configuration for a repeatable poison test:

```bash
LABPASS_PORT=8003 LABPASS_MAIL_PORT=8026 /tmp/labpass-compose/docker-compose \
  -p labpass-m4-verification up --build --wait --wait-timeout 120
LABPASS_PORT=8003 LABPASS_MAIL_PORT=8026 /tmp/labpass-compose/docker-compose \
  -p labpass-m4-verification exec -T -e LABPASS_DLQ_CHECK=true consumer python \
  < scripts/check-background-dlq.py
```

This deliberately inserts a poison record and can take about a minute. It stays
in the test DLQ. Run it only in an isolated project, not as routine production health.

## Next implementation step

Prepare AWS-specific SQS/SES adapters and a Lambda entry point around the tested
delivery core, including partial-batch event-source configuration, secret loading,
restricted DB credentials and private connectivity. Then define Terraform with
explicit region/domain/budget and egress/availability decisions. No paid
provisioning, AWS deployment or resource deletion is authorized by this milestone.
