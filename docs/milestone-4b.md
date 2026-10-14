# Milestone 4B: AWS worker preparation

Verified 14 October 2026. Cloud worker code and packaging are
complete for offline verification. No AWS infrastructure was provisioned, no
real confirmation email was sent, and no SQS/SES/Secrets Manager call was made.
This report records the worker verification stage; current infrastructure status
is in the [project checklist](checklist.md).

## Implementation

The cloud relay publishes the existing stable event envelope to real SQS using
an execution-role SDK client. The Lambda entry point loads authoritative data
from PostgreSQL, sends via SES and uses the existing delivery claim/fencing logic.
It checks the source queue and available invocation time, returning failed IDs
through Lambda's partial-batch contract. Successful duplicates and cancellations
observed before sending do not call SES. Email failure preserves committed
bookings and seat inventory.

Worker configuration explicitly enables AWS mode, retrieves `AWSCURRENT` database
credentials from Secrets Manager and refreshes a five-minute cache. Expired pools
are disposed before refresh; failure has no stale-credential fallback. Database
URLs encode passwords safely and require hostname/CA verification. Cloud engines
have one pooled connection, bounded waits and hidden SQL parameters. SDK calls
use explicit regions, bounded timeouts, one attempt and ignore endpoint overrides.
The local credential-free SQS/SMTP path remains separate.

The official Python 3.14 Lambda image packages the existing locked dependencies
and reviewed public RDS CA bundle. A non-root, read-only, network-disabled runtime
emulator verifies imports, bundle parsing, invocation and fail-safe responses.
No new dependencies, schema changes or frontend contracts are introduced.

## Files changed

| Files | Purpose |
| --- | --- |
| `backend/labpass/aws_config.py` | Cloud opt-in, required settings, ARN/host/sender/CA validation |
| `backend/labpass/aws_runtime.py` | SDK clients, SES sender, secret cache and bounded TLS database pool |
| `backend/labpass/aws_relay.py` | Cloud relay CLI, configuration-only check and graceful shutdown |
| `backend/labpass/lambda_handler.py` | SQS entry point, partial failures, queue checks and time admission |
| `backend/labpass/mail.py` | Share the existing confirmation text between SMTP and SES |
| `backend/tests/test_aws.py` | 42 new offline configuration/SDK/real-PostgreSQL worker tests |
| `backend/Dockerfile.lambda`, `backend/Dockerfile` | Dedicated Lambda packaging; relay image includes public CA bundle |
| `backend/certs/`, `.gitignore` | Track only the named public bundle, provenance/checksum and refresh instructions |
| `scripts/smoke-lambda.py` | Actual offline runtime-emulator smoke |
| `docs/aws-workers.md` | IAM/DB access, private networking, mapping settings, configuration and release contract |
| `README.md`, `docs/architecture.md`, `docs/checklist.md`, `docs/git-workflow.md`, this report | Current progress, dev branch workflow, commands and verification limits |

## Review findings

Reviewed each changed source/config/test/document and traced booking → outbox →
SQS → claim → SES → completion, including failure and warm-runtime refresh paths.
Reviewed the unchanged transaction core, migration integration, local queue
isolation and generated API contract alongside these changes.

- **Medium, fixed:** initialization/secret failure could be attempted again for
  each record, multiplying AWS calls during an outage. One initialization failure
  now defers the remaining batch without repeating setup; the regression checks
  one attempt, all failed IDs and sanitized logs.
- **Medium, fixed:** delivery lease safety depended on an undocumented function
  timeout. Admission rejects more than 60 seconds remaining; the cloud claim lasts
  120 seconds, and Terraform's contract sets function timeout to 60 seconds and
  queue visibility to at least 360. Low remaining time is checked before and
  after secret retrieval. Tests verify records are deferred before claiming.
- **Low, fixed:** relay cleanup exceptions could escape with raw upstream text;
  cleanup logs a fixed code. A trial `return` in `finally` produced a Python 3.14
  syntax warning and was removed. Final tests have no warnings.
- **Test correction:** the first full run reported 131 passes and one failure
  because a test expected botocore to retain an input-only configuration flag in
  `client.meta.config`. It now verifies the actual resolved HTTPS endpoint despite
  an environment override. The endpoint behavior itself passed the first run.

No unresolved high-severity issue was found in these reviewed offline paths.
This does not establish production readiness or validate actual IAM/network rules.

## Verification

| Command/check | Observed result |
| --- | --- |
| `bash scripts/test-local.sh -q` | Final **135 passed in 5.18s**, real PostgreSQL 18.6, no warnings; includes the existing 100-user/20-seat overlap and migration tests |
| `.venv/bin/python -m pytest -q scripts/tests` | **9 passed in 0.06s** |
| `.venv/bin/ruff check backend scripts/smoke-lambda.py` | Passed |
| `.venv/bin/ruff format --check backend scripts/smoke-lambda.py` | Passed, 38 files formatted |
| `.venv/bin/python -m pip check` | No broken requirements |
| `.venv/bin/python scripts/export-openapi.py --check frontend/openapi.json` | Backend OpenAPI matches frontend contract |
| `npm --prefix frontend run check-contract` | OpenAPI and generated TypeScript match |
| `docker build -f backend/Dockerfile.lambda -t labpass-lambda:m4b backend` | Built final local image `0437b86630a5` |
| `docker build -t labpass-api:m4b backend` | Built final local image `4ecb8d194692` |
| `docker exec -i labpass-m4b-lambda-final python < scripts/smoke-lambda.py` | `Lambda offline smoke passed`; direct handler plus actual runtime-emulator requests, CA parsing, non-root execution |
| `docker exec labpass-m4b-lambda-final python -m pip check` | No broken requirements |
| Public RDS bundle download, SHA-256 and OpenSSL certificate inspection | Downloaded from official HTTPS trust store; checksum/provenance in `backend/certs/README.md`; no private keys |
| `git diff --check` and selected source/secret review | Passed before staging; only public CA/test identifiers are included |

Lambda verification used no published ports, `--network none`, a read-only root
filesystem, a writable `/tmp` mount and UID/GID 10001.

## Tested behavior and limits

AWS tests prohibit SDK HTTP requests and use actual boto3 request/response shape
validation. The database transactions are real PostgreSQL, including publication
bookkeeping, mixed batches of 3 and 10, cancellation, duplicate suppression,
SES rejection, missing acceptance ID and successful acceptance followed by a
failed completion commit. The latter leaves a live `sending` claim and failed
SQS record, demonstrating the remaining duplicate-email window after expiry.

Cloud credential refresh and TLS connection parameters are verified offline;
actual secret rotation, RDS certificate handshakes/failover, network failures,
IAM authorization, real SQS event mapping/deletion/redrive and SES delivery are
not verified. Public HTTPS/browser flows were not rerun because their code and
contract are unchanged. Local Mailpit/ElasticMQ smoke evidence remains in
[Milestone 4](milestone-4.md); it was not rerun against these newly built images.

Concurrency/pool limits, restricted worker DB roles, service/engine regional
availability, log/queue/DLQ/backlog alarms, SES identity/sandbox/bounce controls,
image digest/base/hash policy and AWS API secret bootstrap still require the
infrastructure/delivery milestones. Time checks reduce risk; they cannot guarantee
completion within the available time during a slow dependency or hard timeout.
Exactly-once email is not promised. Workload Terraform and CI remain pending.

## Run locally and next step

Run `bash scripts/test-local.sh -q`; expect 135 passing backend tests. For the
Lambda build/emulator commands, see [Run offline](aws-workers.md#run-offline).
Local UI and Mailpit usage follow the README.

Workload integration requires runtime roles, RDS/secrets, Lambda/SES and
frontend/API infrastructure. CI/CD requires GitHub Actions OIDC, immutable images,
single migrations and release smoke checks. Official references are linked in the
[worker contract](aws-workers.md).
