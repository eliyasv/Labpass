# LabPass

An AWS portfolio project for reserving free seats in cloud and DevOps workshops.
Milestones 1–3 implement the booking backend, real authentication, PostgreSQL
migrations and React frontend. Milestone 4 adds a verified local queue/email
pipeline. Milestone 4B adds cloud SQS/SES adapters, a Lambda handler and worker
secret/TLS configuration, verified offline. AWS deployment remains a later authorized step.

Python 3.14 and PostgreSQL 18 are the supported local versions for this milestone.
`test.py` was present before implementation; its IDE tab is currently open but the
file is absent from disk. This milestone did not create or remove it. The baseline
commits group repository setup, backend, frontend/local stack and documentation.
Current development uses `dev`, tracking `origin/dev`.
See [Git workflow](docs/git-workflow.md) for the baseline and future commit strategy.

## Cloud worker preparation

The AWS relay and Lambda consumer reuse the durable PostgreSQL claims from the
local pipeline. They load worker credentials from Secrets Manager, require
verified RDS TLS, and keep failures retryable without changing seat inventory.
The default local stack continues to capture mail in Mailpit.

Run `bash scripts/test-local.sh -q` for real PostgreSQL tests with stubbed AWS
responses. The [AWS worker contract](docs/aws-workers.md) includes the offline
Lambda image/emulator smoke, runtime settings, IAM scopes, private network paths
and release order. See [Milestone 4B evidence](docs/milestone-4b.md).

## Run with Docker Compose

Requires Docker Engine and the Docker Compose plugin. Run from this directory:

In the current workspace, Compose was absent. Verification used the checked
official binary at `/tmp/labpass-compose/docker-compose`; until you install the
plugin, substitute that executable for `docker compose` in the commands below.
The temporary binary is not part of the project or guaranteed to survive a reboot.

```bash
[ -f .env ] || cp .env.example .env
docker compose config --quiet
docker compose up --build --wait --wait-timeout 120
docker compose exec api python -m labpass.seed
curl --fail http://127.0.0.1:8000/api/health/ready
python3 scripts/smoke-local.py
```

Compose runs one migration container before starting the API. It never runs
migrations in each API worker. `--wait` waits for the API health check: a container
reported as "Started" may still be starting Uvicorn. The smoke script also waits
up to 30 seconds for readiness, retrying connection errors and HTTP 503 before
creating any test data. Other HTTP errors and invalid responses fail immediately;
authentication and booking requests are not automatically retried.
The database and API have no published host ports. The `web` container serves
the frontend and proxies `/api/*` at `127.0.0.1:8000` by default.
Open LabPass: <http://127.0.0.1:8000/>. Swagger: <http://127.0.0.1:8000/docs>.
`LABPASS_PORT` in `.env` selects the loopback port and allowed browser Origin.
If you choose another port, also export that value when running the smoke script.

Mailpit captures local confirmation emails at <http://127.0.0.1:8025/>.
`LABPASS_MAIL_PORT` selects its loopback UI port. SMTP and the SQS-compatible
ElasticMQ queue are internal services; no real AWS credentials or outbound mail
are used. The relay/consumer start automatically after migration `0003`.

## Local confirmations and worker checks

Reserve a seat in the frontend and keep it active until its email appears in
Mailpit, usually within a few seconds. Its subject is **Your LabPass reservation**
and the body includes the booking reference. A booking cancelled before the
worker checks it is marked `skipped`; cancellation during sending can still
produce the historical reservation email. Failed email delivery never cancels
a booking or changes inventory.

For an automated check, run from the repository root:

```bash
docker compose exec -T consumer python < scripts/smoke-background.py
docker compose exec -T relay python -m labpass.background status
docker compose logs --tail=30 relay consumer
docker compose exec api alembic check
```

The background smoke creates generated credentials, reserves an available seat,
waits for publication and capture, resends the same event to test duplicate
suppression, then cancels and logs out. Expect `Background smoke passed`.
The status command prints counts only. A quiet backlog has `outbox_pending: 0`
and `outbox_failed: 0`; delivery totals include `sent` and possibly `skipped`.

Relays lock one due event per transaction with `SKIP LOCKED`, publish its stable
ID, then record success. Up to five publication attempts are committed with
exponential backoff; exhausted events remain in PostgreSQL for inspection.
Consumers use durable 90-second leases and owner tokens. Successful duplicates
are acknowledged without resending. Queue visibility is 120 seconds; ambiguous
failures wait long enough for the lease to expire. Poison/terminal failures use
a shorter delay and reach the DLQ after five receives. Queue, mailbox and DB
state use retained named volumes.

An email accepted just before a crash or failed database update can be sent
again after recovery. Stable Message-ID is a diagnostic, not an exactly-once
guarantee. Manual recovery can also resend an email with an uncertain outcome.
For recovery, inspect the failed event/lease and use the CLI:

```bash
docker compose exec relay python -m labpass.background retry-outbox --help
docker compose exec consumer python -m labpass.background retry-delivery --help
docker compose exec consumer python -m labpass.background replay-dlq
```

`retry-outbox` and `retry-delivery` require `--event-id` with an actual inspected
UUID. The former resets only failed unpublished events. The latter resets only
failed deliveries or expired leases, then `replay-dlq` returns up to ten queued
records. Sent records and live leases cannot be reset. Repair poison events
before replay; do not repeatedly replay malformed data. Publication failures
stay in the DB rather than a queue DLQ because the queue may be unreachable.

Worker failure/concurrency tests are part of `bash scripts/test-local.sh -q` and
use real PostgreSQL. SDK parameter tests use botocore Stubber; transaction tests
do not mock the database. To exercise actual poison redrive, use an isolated
Compose project, following [milestone-4.md](docs/milestone-4.md).

An existing running milestone-1 image continues to serve its old API until
`docker compose up --build --wait --wait-timeout 60` rebuilds/recreates it and applies migration `0002`.
Milestone 2 originally used a separate project on port 8001. Milestone 3 browser
tests use a separate project on port 8002, with their own retained database.

## Use the frontend

Open exactly <http://127.0.0.1:8000/> (or your configured port). Use **Create account**,
then sign in. Choose **Reserve a seat**, see it under **My bookings**, and use
**Cancel booking** followed by confirmation to release it. Refreshing the page
restores your session. Sign out revokes it. Availability is a snapshot; the server
decides whether a seat can be reserved.

The frontend sends same-origin `/api` requests with the HttpOnly cookie and keeps
the CSRF token in memory. Pending booking keys are kept in tab session storage,
scoped by user and workshop, so a lost response can be retried with the same key.
No credentials or session/CSRF tokens are stored in browser storage. If browser
storage is disabled, retry keys survive only while the page stays open.

Workshop browsing/history load 50 rows at a time; use **Load more workshops** or
**Load older bookings** for further pages. Search filters workshops already
loaded. A booking older than the loaded history may not be marked on its card;
the backend still rejects a duplicate reservation. Workshop dates and cancellation
deadlines remain deferred. Local confirmations are captured in Mailpit; internet
email delivery through AWS SES remains deferred.

Admin accounts see **Manage workshops**, with workshop creation and capacity
updates. Create an administrator using the operator CLI below; public registration
creates regular accounts. Capacity cannot fall below existing reservations.

## Frontend development and checks

Requires Node.js 20.19+ in the 20.x line, or 22.12+ (Node 22 is used in Docker).
Versions and integrity hashes are pinned in `frontend/package-lock.json`.

```bash
cd frontend
npm ci
npm run check-contract
npm run build
npm run format:check
```

The contract check needs the backend dependencies installed in the root `.venv`.
`LABPASS_PYTHON` can select another installed Python interpreter. To update a
changed backend contract, run from the repository root:

```bash
.venv/bin/python scripts/export-openapi.py frontend/openapi.json
npm --prefix frontend run generate
npm --prefix frontend run check-contract
```

For hot reload, stop Compose first to free port 8000. Run the native backend
described below with `APP_ORIGIN=http://127.0.0.1:5173` and
`LABPASS_COOKIE_SECURE=false` on port 8000, then run `npm run dev` from `frontend/`.
Open <http://127.0.0.1:5173/>. Vite proxies `/api` without rewriting Origin; the
backend must allow this exact browser origin. Normal Compose usage needs no
Node installation or dev server. `npm run preview` previews static assets only;
use Compose to exercise the complete production build with its API proxy.

### Browser tests with real PostgreSQL

Run from the repository root. Tests require Docker access and create generated
accounts, admin fixtures, workshops, bookings and outbox rows in the isolated
project. They refuse to provision admins in the default `labpass` project. Data
is retained after stopping; no volume deletion is performed.

```bash
LABPASS_PORT=8002 docker compose -p labpass-m3-verification up --build --wait --wait-timeout 90
cd frontend
PLAYWRIGHT_BROWSERS_PATH=/tmp/labpass-playwright npx playwright install chromium --only-shell
PLAYWRIGHT_BROWSERS_PATH=/tmp/labpass-playwright \
  LABPASS_E2E_URL=http://127.0.0.1:8002 \
  LABPASS_TEST_API_CONTAINER=labpass-m3-verification-api-1 npm test
cd ..
LABPASS_PORT=8002 docker compose -p labpass-m3-verification stop
```

Tests assume their generated workshops fit in the first 50 rows. Repeated runs
retain rows; use a new project with a `labpass-m3-verification-` prefix when you
want a fresh test database, updating the test container name. Chromium is the
currently tested browser. Your OS may need Playwright's documented system
libraries. See [Playwright browser installation](https://playwright.dev/docs/browsers).

## Register, log in and book

`X-User-ID` and `LABPASS_DEV_IDENTITY` are removed. Protected routes require a
database-backed cookie session. Passwords use Argon2id, and registration always
creates regular users. No default account password exists in Git or the image.
The seed now creates only a workshop, with ID
`00000000-0000-0000-0000-000000000020`.

Use Swagger at exactly `http://127.0.0.1:8000/docs` for the default Compose port:

1. Call `POST /api/auth/register` with your email and a chosen 12–128 character password.
2. Call `POST /api/auth/login` with those credentials. The browser stores an
   HttpOnly session cookie; copy `csrf_token` from the JSON response.
3. Call `POST /api/bookings` with the seeded workshop ID, a new `Idempotency-Key`
   of 8–128 permitted characters, and `X-CSRF-Token` from login.
4. Inspect `GET /api/bookings`, then use the returned booking ID for cancellation.
5. Use `POST /api/auth/logout` with the CSRF header to revoke the current session.

Browser writes send the Origin header automatically. Native HTTP clients must
send `Origin: http://127.0.0.1:8000` themselves, retain the session cookie and
include `X-CSRF-Token` on authenticated writes. `GET /api/auth/me` returns current
user details, expiry and the CSRF token after a page reload. Raw session tokens
are never returned in JSON. Every API response uses `Cache-Control: no-store`.

Sessions expire after eight hours. Login rotates the current cookie/session;
logout is idempotent and revokes that session, including replay of its old cookie.
Requests already authenticated at logout time may finish. Other device sessions
remain active. The smoke script uses generated, unprinted credentials, creates a
regular test account and booking, then cancels and logs out. Its rows are retained.

Local Compose explicitly allows non-Secure cookies on loopback HTTP. Native
configuration requires `DATABASE_URL` and `APP_ORIGIN`; Secure cookies default to
true and require HTTPS. Set `LABPASS_COOKIE_SECURE=false` only for loopback
development. Configuration rejects that exception for a public hostname.

Repeat a booking request with the same key: it returns the same booking ID without consuming
another seat. Reusing the key for another workshop returns HTTP 409. Retrying
after cancellation returns the original booking in its current cancelled state;
use a new key to reserve again. Only successful bookings consume keys; failed
attempts can be retried after availability changes. Keys are retained indefinitely
in this milestone and scoped across booking requests for the same user.

Cancelling again changes no inventory. All identities and role decisions come
from the session and DB user, never a supplied user/admin header or request body.

## Create a local administrator

The operator CLI prompts for a password and confirmation without echoing either:

```bash
docker compose exec api python -m labpass.create_admin --email operator@example.test
```

Use an unused email. The command refuses to promote or reset an existing account.
Log in normally with the new credentials to use admin routes. Public registration
cannot set roles. Passwords never appear in CLI arguments or environment variables.

Migration `0002` preserves existing users/bookings, but old fixture accounts have
no passwords and cannot log in. Legacy credential activation/recovery is deferred;
use a new operator account. Case-only email collisions abort the migration for
manual resolution rather than merging accounts. Its downgrade removes passwords
and sessions, so it is not a safe deployment rollback.

Inspect the state and structured logs:

```bash
docker compose logs api migrate
docker compose exec db psql -U labpass -d labpass -c \
  'SELECT id, title, capacity, reserved, capacity - reserved AS available FROM workshops;'
docker compose exec db psql -U labpass -d labpass -c \
  'SELECT id, booking_id, event_type, created_at, published_at FROM outbox_events;'
docker compose exec api alembic current
docker compose exec api alembic check
docker compose stop
```

Pending events should drain while the relay/consumer run. Inspect worker health,
retry times and failed rows if they persist. Logs include request, booking and event IDs, without
logging identity headers, request bodies, email addresses, or SQL parameters.

## Install and test without Docker

Install Python 3.14 and PostgreSQL 18 binaries (`initdb`, `pg_ctl`, `createdb`) first.
Run as a regular user: PostgreSQL refuses `initdb` as root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-dev.lock
.venv/bin/python -m pip check
.venv/bin/ruff check backend scripts/smoke-local.py
.venv/bin/ruff format --check backend scripts/smoke-local.py
.venv/bin/python -m pytest -q scripts/tests
bash scripts/test-local.sh -q
```

The script creates a fresh PostgreSQL cluster under `/tmp`, uses a Unix socket
with no TCP listener, permits 160 connections for the 100-user test, then stops
the server on exit. It preserves the temporary files and reports their location.
Tests create and remove only their own randomly named schema, apply real Alembic
migrations, and fail if PostgreSQL is absent. No SQLite or database mocks are used.

To use an existing **dedicated test** PostgreSQL server instead, export
`TEST_DATABASE_URL` with a real `postgresql+psycopg` connection URL, then run:

```bash
cd backend
../.venv/bin/python -m pytest -q
```

The URL must allow schema creation and at least 105 simultaneous client
connections plus server headroom. Tests never read AWS credentials.
For a native development API, set `DATABASE_URL` to your PostgreSQL database
and `APP_ORIGIN=http://127.0.0.1:8000`, `LABPASS_COOKIE_SECURE=false`, then from `backend/`
run `alembic upgrade head`,
`python -m labpass.seed`, and `uvicorn labpass.main:app --host 127.0.0.1 --port 8000 --no-access-log`
using the installed virtual environment. No database URL is assumed or embedded.

## Repository and phases

```text
backend/
  labpass/              API, validation, booking service, models, configuration
                        outbox relay, delivery leases, local SQS/SMTP adapters
  migrations/           versioned PostgreSQL schema
  tests/                rules, auth/CSRF, HTTP, concurrency, rollback, migrations
  requirements*.in      declared dependency ranges
  requirements*.lock    exact resolved direct and transitive versions
  Dockerfile
frontend/
  src/                  React UI, API client, retry keys and generated API types
  tests/                browser tests against a real isolated backend/database
  openapi.json          exported backend contract
  package-lock.json     exact versions and npm integrity hashes
  Dockerfile            build static frontend; serve with non-root Nginx
  nginx.conf            same-origin API proxy and frontend security headers
compose.yaml            local database, migration step, API and web frontend
                        local queue, email capture, relay and consumer
local/elasticmq.conf    persistent local queue and DLQ configuration
scripts/export-openapi.py export/check contract without connecting to a database
scripts/smoke-background.py end-to-end publication/capture/duplicate smoke
scripts/check-background-dlq.py opt-in poison-message test for isolated stacks
scripts/test-local.sh   isolated real-PostgreSQL test runner
scripts/smoke-local.py   real auth and booking HTTP smoke against the seeded API
scripts/tests/          smoke startup retry and timeout regression tests
docs/architecture.md    decisions, failure scenarios, AWS target and trade-offs
docs/checklist.md       completed work, pending scope and risks
docs/milestone-1.md     review and verification evidence
docs/milestone-2.md     authentication review and verification evidence
docs/milestone-3.md     frontend review and browser verification evidence
docs/milestone-4.md     local background pipeline, failure tests and remaining AWS work
```

Workers share booking models under `backend/labpass`; Lambda has its own Dockerfile.
Future directories will be introduced when they contain working code: `infra/`
(Terraform), `.github/workflows/` (GitHub Actions), and `load-tests/` (k6).

1. Local booking API, migrations, correctness tests, containers.
2. Registration/login, password hashing, authenticated sessions, real roles and ownership tests (done).
3. React workshop browsing, booking/history/cancellation, admin flow and smoke tests (done).
4. Coordinated outbox relays, local SQS/SMTP, duplicate handling and failure tests
   (done locally); cloud relay/Lambda/SES adapters and secret/TLS preparation are
   verified offline. AWS resources, roles, mapping and deployment remain pending.
5. Reviewable AWS Terraform, networking/cost choices, IAM/OIDC, TLS, secrets and alarms.
6. Authorized deployment, immutable artifacts, controlled migrations, load testing,
   release smoke tests and verified backup restoration.

See [architecture](docs/architecture.md), [checklist](docs/checklist.md), and
[milestone report](docs/milestone-1.md). No paid infrastructure is provisioned.

Before public deployment, add distributed login/registration attempt controls,
email ownership verification/recovery, scheduled expired-session cleanup and
restricted database roles. The two-task Argon2 semaphore bounds resource use
per process; it does not enforce a request rate. Registration conflicts expose
whether an email is already registered. Chromium browser automation is verified;
public HTTPS behavior, failover and physical network failure during commit remain unverified. See the
[authentication milestone report](docs/milestone-2.md). No AWS deployment ran.

## Dependency updates

Locks pin versions for CPython 3.14 on Linux. They are version locks, without
artifact hashes; base container tags are also mutable in local development.
Regenerate deliberately, review changes, and rerun the checks before accepting an update:

```bash
.venv/bin/pip-compile --upgrade --strip-extras -o backend/requirements.lock backend/requirements.in
.venv/bin/pip-compile --upgrade --strip-extras --allow-unsafe -o backend/requirements-dev.lock backend/requirements-dev.in
.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-dev.lock
```

AWS deployment will pin built image digests. Dependency hashes and base image
digest pinning remain delivery hardening tasks before publishing artifacts.
