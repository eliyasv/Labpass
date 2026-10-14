# Development and local operations

Use the [README](../README.md#run-locally) to start the complete application with
Docker Compose. This guide covers development outside the containers, API usage,
checks and background-worker recovery. Run commands from the repository root
unless a section changes directories.

## Configuration

`.env.example` provides local Compose settings. Keep `.env` outside Git and choose
your own database password. `LABPASS_PORT` selects the application port and
allowed browser Origin; `LABPASS_MAIL_PORT` selects Mailpit's browser port.
If you change the application port, also export `LABPASS_PORT` when running
`scripts/smoke-local.py`.

Compose publishes the frontend and Mailpit on loopback. PostgreSQL, the API,
queue and SMTP have no published host ports. Migrations finish before the API
starts; `docker compose up --wait` waits for service health checks. The HTTP
smoke also waits up to 30 seconds for API readiness.

Native API configuration requires `DATABASE_URL` and `APP_ORIGIN`. Secure cookies
default to true and require HTTPS. `LABPASS_COOKIE_SECURE=false` is permitted only
for loopback development. Local Compose uses that HTTP exception explicitly.

## Native backend

Install Python 3.14 and PostgreSQL 18 first, then install the locked dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-dev.lock
.venv/bin/python -m pip check
```

Set `DATABASE_URL` to your development PostgreSQL database,
`APP_ORIGIN=http://127.0.0.1:8000` and `LABPASS_COOKIE_SECURE=false`. From `backend/`,
using the activated virtual environment:

```bash
alembic upgrade head
python -m labpass.seed
uvicorn labpass.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The native API does not serve the frontend. Use Swagger for API requests, or
start the Vite development server with the matching Origin described below.
Local queue/email workers are easiest to run through Compose.

## Backend checks

Run the database tests as a regular user with `initdb`, `pg_ctl` and `createdb`
on your PATH; PostgreSQL refuses to initialize a cluster as root.

```bash
.venv/bin/ruff check backend scripts/smoke-local.py scripts/smoke-lambda.py
.venv/bin/ruff format --check backend scripts/smoke-local.py scripts/smoke-lambda.py
.venv/bin/python -m pytest -q scripts/tests
bash scripts/test-local.sh -q
```

The runner creates a fresh PostgreSQL cluster under `/tmp`, uses a Unix socket
without a TCP listener, and permits 160 connections for the concurrency tests.
It stops the server on exit, retains the files and prints their location.
Tests apply real Alembic migrations and create/remove their own randomly named
schema. AWS SDK tests use isolated dummy credentials and stubbed responses.

To use an existing dedicated test database, set `TEST_DATABASE_URL` to its actual
`postgresql+psycopg` connection URL, then run:

```bash
cd backend
../.venv/bin/python -m pytest -q
```

That database must allow schema creation and at least 105 simultaneous client
connections plus server headroom.

## Frontend development

Use Node.js 20.19+ in the 20.x line, or 22.12+. From the repository root:

```bash
npm --prefix frontend ci
npm --prefix frontend run check-contract
npm --prefix frontend run build
npm --prefix frontend run format:check
```

The contract check uses the backend dependencies in `.venv`. Set `LABPASS_PYTHON`
to another installed interpreter if needed. After changing the API contract:

```bash
.venv/bin/python scripts/export-openapi.py frontend/openapi.json
npm --prefix frontend run generate
npm --prefix frontend run check-contract
```

For hot reload, stop Compose to free port 8000. Run the native backend with
`APP_ORIGIN=http://127.0.0.1:5173` and `LABPASS_COOKIE_SECURE=false`, then:

```bash
npm --prefix frontend run dev
```

Open <http://127.0.0.1:5173/>. Vite proxies `/api` to the native backend and
preserves Origin. `npm run preview` serves static assets only; use Compose for
the complete frontend/API stack.

## Browser tests

Browser tests use an isolated Compose project with a real API and PostgreSQL.
They create generated accounts, workshops, bookings and an administrator.
The fixture setup refuses to create admins in the default `labpass` project.

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

Data is retained after stopping. Repeated runs accumulate fixtures; choose a
fresh project name with a `labpass-m3-verification-` prefix when needed and update
the test container name. Browser fixtures must fit within the first 50 workshop
rows. Chromium is the tested browser; operating-system libraries may be
required. See [Playwright browser installation](https://playwright.dev/docs/browsers).

## API requests and booking retries

Swagger is available at <http://127.0.0.1:8000/docs> for the default Compose port.
The seed creates workshop `00000000-0000-0000-0000-000000000020`.

1. Register through `POST /api/auth/register` with an email and a 12–128 character password.
2. Log in through `POST /api/auth/login`. Keep the session cookie and returned `csrf_token`.
3. Reserve through `POST /api/bookings`, supplying the workshop ID, a new
   `Idempotency-Key` and `X-CSRF-Token`.
4. Inspect `GET /api/bookings` and cancel using the returned booking ID.
5. Log out through `POST /api/auth/logout` with the CSRF header.

Browser writes supply Origin automatically. Native clients must send the exact
configured Origin, retain cookies and include the CSRF header on authenticated
writes. `GET /api/auth/me` restores current user/session details and the CSRF token.
Sessions expire after eight hours. Public registration always creates regular users.

Booking keys accept 8–128 letters, digits, `.`, `_`, `:` or `-` and are scoped to
the user. An identical successful retry returns the original booking ID. Reusing
the key for another workshop returns 409. After cancellation, retrying that key
returns the cancelled booking; use a new key to reserve again. Repeated
cancellation does not release another seat.

The frontend retains pending booking keys in tab session storage. It keeps CSRF
state in memory and authentication in an HttpOnly cookie. Workshop/history lists
load 50 rows at a time; search filters loaded workshops. The backend enforces
uniqueness even when an older booking is outside the loaded history.

## Inspect the stack

```bash
curl --fail http://127.0.0.1:8000/api/health/ready
docker compose logs --tail=30 api migrate relay consumer
docker compose exec api alembic current
docker compose exec api alembic check
docker compose exec -T relay python -m labpass.background status
docker compose exec db psql -U labpass -d labpass -c \
  'SELECT id, title, capacity, reserved, capacity - reserved AS available FROM workshops;'
```

A healthy readiness endpoint returns `{"status":"ok"}`. A quiet worker backlog
has `outbox_pending: 0` and `outbox_failed: 0`. Delivery counts can include `sent`
and `skipped`. Mailpit at <http://127.0.0.1:8025/> shows captured confirmations.

```bash
python3 scripts/smoke-local.py
docker compose exec -T consumer python < scripts/smoke-background.py
```

The HTTP smoke creates an account and booking, then cancels and logs out.
The background smoke reserves a seat, waits for publication/email capture,
replays the event to check duplicate suppression, then cancels and logs out.
Generated fixture rows are retained.

## Worker recovery

Relays publish stable event IDs from the transactional outbox. Failed publication
backs off and stops after five committed attempts; failures stay in PostgreSQL.
Consumers use durable delivery leases and owner tokens. Sent/skipped duplicates
are acknowledged without resending. Local queue visibility is 120 seconds and
the delivery lease is 90 seconds; the queue redrives failed messages to the DLQ
after five receives.

A cancellation observed before claiming suppresses the email. Cancellation
during sending can still produce a confirmation. Mail acceptance followed by
a failed completion update leaves an uncertain outcome and can duplicate email
after lease expiry. Delivery failure never cancels a booking or changes inventory.

Inspect the failed event and claim before resetting it:

```bash
docker compose exec relay python -m labpass.background retry-outbox --help
docker compose exec consumer python -m labpass.background retry-delivery --help
docker compose exec consumer python -m labpass.background replay-dlq
```

Both reset commands require `--event-id` with the inspected event's UUID.
`retry-outbox` resets only failed unpublished events. `retry-delivery` resets
failed deliveries or expired leases; sent records and live leases are refused.
`replay-dlq` returns up to ten queued records. Repair malformed events before
replay. Manual recovery can resend mail whose previous acceptance is uncertain.

For an isolated poison-message/redrive exercise, see
[the background pipeline report](milestone-4.md). Cloud runtime configuration,
permissions and the offline Lambda smoke are in [AWS workers](aws-workers.md).

## Dependency updates

Python locks pin versions for CPython 3.14 on Linux; they do not yet include
artifact hashes. Local container base tags are mutable. The npm lock includes
package integrity hashes. Review dependency updates and rerun affected checks:

```bash
.venv/bin/pip-compile --upgrade --strip-extras -o backend/requirements.lock backend/requirements.in
.venv/bin/pip-compile --upgrade --strip-extras --allow-unsafe -o backend/requirements-dev.lock backend/requirements-dev.in
.venv/bin/python -m pip install -r backend/requirements.lock -r backend/requirements-dev.lock
```

Cloud delivery will deploy immutable application image digests. Schema changes
are controlled by Alembic; review migration/data rollback limits in the
[architecture guide](architecture.md) before changing stored data.
