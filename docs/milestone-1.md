# Milestone 1 report

Historical verification record. Development identity was replaced by authenticated
sessions in [Milestone 2](milestone-2.md). Current setup: [README](../README.md).

Verified on 13 October 2026 against local PostgreSQL and container services.

## Implementation

FastAPI provides workshop browsing, seat availability, booking/history,
cancellation, and admin creation/capacity updates. PostgreSQL owns inventory.
User/workshop row locks serialize competing mutations; a partial unique index
prevents duplicate active bookings. A canonical payload and `(user, key)` record
make successful requests safe to retry. Inventory, booking, idempotency record
and outbox event commit in one transaction before the success response.

At this stage, the outbox stored pending events without a relay or email sender.
Identity used an opt-in development header.

## Files added

- Root: `.gitignore`, `.env.example`, `compose.yaml`, `README.md`.
- Backend configuration: `Dockerfile`, `.dockerignore`, `pyproject.toml`,
  `alembic.ini`, `requirements.in`, `requirements.lock`, `requirements-dev.in`,
  `requirements-dev.lock` under `backend/`.
- `backend/labpass/`: `__init__.py`, `config.py`, `db.py`, `models.py`, `rules.py`,
  `services.py`, `schemas.py`, `app.py`, `main.py`, `seed.py`.
- `backend/migrations/`: `env.py`, `script.py.mako`,
  `versions/0001_initial_booking_inventory_and_outbox.py`.
- `backend/tests/`: `conftest.py`, `test_rules.py`, `test_config.py`,
  `test_bookings.py`, `test_api.py`, `test_migrations.py`.
- `scripts/`: `test-local.sh`, `smoke-local.py`.
- `docs/`: `architecture.md`, `checklist.md`, this report.

## Review findings

| Severity | Finding | Resolution |
| --- | --- | --- |
| Medium | Unexpected SQLAlchemy exceptions could reach server traceback logging with SQL parameters | Added sanitized database-error handling and pool/operational 503 handling; regression tests verify error responses, rollback and absence of sensitive SQL/parameter text |
| Low | Installed Starlette deprecated the original HTTPX test client | Switched the dev lock to the supported `httpx2` dependency; HTTP tests passed without the warning |
| Low | Generated migration formatting failed lint | Reformatted and split the constraint string; lint and migration round trip pass |
| Low | Development tooling's initial lock omitted packaging dependencies treated specially by pip-tools | Regenerated with `--allow-unsafe` to pin pip/setuptools too; installed versions match the pins |

Stage limitations: development identity permits impersonation; Compose uses a
development DB superuser; inventory equality depends on mutation services;
locks lack artifact hashes; base image tags are mutable. Email delivery,
authentication, frontend and AWS integration were not implemented at this stage.

## Verification

The installed versions used include Python 3.14.7, PostgreSQL 18.6, Docker 29.9.0,
Compose 5.6.0, FastAPI 0.143.0, SQLAlchemy 2.0.54, Alembic 1.20.0,
psycopg 3.3.6, Pydantic 2.14.1 and pytest 9.1.1. Other resolved versions are in
the lockfiles.

| Command/check | Observed result |
| --- | --- |
| `python3 -m venv .venv`, pip-tools installation, `pip-compile`, locked package installation | Completed; exact runtime and development lockfiles generated |
| `alembic revision --autogenerate --rev-id 0001` against the isolated PostgreSQL cluster | Generated and froze the initial migration |
| `bash scripts/test-local.sh -q` | **25 passed in 1.20s**, no warnings; temporary server stopped |
| `ruff check backend scripts/smoke-local.py --fix`, formatter, `ruff format --check` | Lint passed; all 19 Python files formatted |
| `python -m pip check` | No broken requirements found |
| `bash -n scripts/test-local.sh` | Exit 0 |
| Compose `config --quiet` with the local password supplied | Exit 0 |
| Compose `-p labpass-m1-verification up --build -d` | Images built; DB healthy; migration exited 0; API started |
| Compose `ps -a` | API and DB healthy; API bound to `127.0.0.1:8000`; migration exited 0 |
| Compose `exec -T api python -m labpass.seed`, executed twice | Both succeeded; fixtures remain idempotent |
| Compose `exec -T api alembic check` | No new upgrade operations detected |
| Compose `exec -T api id` | Runtime UID/GID 10001, not root |
| `.venv/bin/python scripts/smoke-local.py` against the actual container HTTP port | Readiness, availability, booking/retry, history and repeated cancellation passed |
| Container `psql` inventory/outbox inspection after smoke | Capacity 20, reserved 0, active bookings 0, pending events 1 |
| Container log inspection | Same booking/event IDs correlate across retries with separate request IDs; cancellations log booking IDs |
| Compose `stop`, `ps -a`, shutdown logs; native `pg_ctl ... -m fast -w stop` | API and DB exited 0; Uvicorn completed shutdown; native server stopped; all data retained |

The 100-user test checks out 100 live PostgreSQL connections before a barrier,
holds inventory in another transaction, and requires PostgreSQL to report all
100 workers waiting on locks before release. It then verifies exactly 20
successful bookings, 80 `workshop_full` conflicts, 20 events and 20 keys, with
counter/count agreement. API throughput was not measured.

Other tests cover same-key retries, different-key duplicate bookings, scoped keys
and payload mismatch across workshops, cancellation retries, cancellation/booking
and capacity races, DB unique/bounds constraints, missing workshops, outbox
persistence failure, injected pre-commit failures, strict HTTP input validation,
development identity/ownership/admin checks, structured logging, and migration
upgrade/downgrade/upgrade. Injected failure hooks simulate application/database
errors while transactions execute against real PostgreSQL; they do not replace
the database with mocks.

Migration metadata checks have Alembic's normal detection limits and do not
validate every possible check constraint change. Constraint behavior is also
tested directly. Physical network loss during COMMIT was not injected; the
pre-commit failure test and post-success retry tests cover related paths only.

## Untested behavior and remaining risks

Real registration/login, session security, authenticated ownership denial,
frontend smoke tests, competing outbox relays, SQS duplicates/publication failure,
SES sends, Lambda/DLQ recovery, AWS network/TLS/secrets paths, Terraform/provider
validation, GitHub Actions/OIDC, release ordering/rollback and backup restoration
were outside this verification stage.
The DB race tests do not measure API throughput, process crashes, failover or
recovery under network partitions. Native and container databases were checked;
no alternate Python/PostgreSQL version matrix was tested.

## Local commands

Compose startup: [README](../README.md#run-locally).
SQL/log inspection and native tests: [Development](development.md).
API routes: <http://127.0.0.1:8000/docs>.
