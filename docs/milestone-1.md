# Milestone 1 report

Historical report. Milestone 2 has replaced development identity with authenticated
sessions; use the current [README](../README.md) and [milestone-2 report](milestone-2.md).

Verified on 13 October 2026 against local PostgreSQL and container services.

## Implementation

Built a FastAPI API for workshop browsing, seat availability, booking/history,
cancellation, and admin creation/capacity updates. PostgreSQL owns inventory.
User/workshop row locks serialize competing mutations; a partial unique index
prevents duplicate active bookings. A canonical payload and `(user, key)` record
make successful requests safe to retry. Inventory, booking, idempotency record
and outbox event commit in one transaction before the success response.

The outbox is durable pending work; there is no relay or email sender yet.
Identity uses an opt-in development header so booking correctness can be built
before authenticated sessions were introduced in Milestone 2.

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

Reviewed every changed file after implementation and traced create/retry,
cancel/rebook, capacity change, migration/container startup and failure paths.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Medium | Unexpected SQLAlchemy exceptions could reach server traceback logging with SQL parameters | Added sanitized database-error handling and pool/operational 503 handling; regression tests verify error responses, rollback and absence of sensitive SQL/parameter text |
| Low | Installed Starlette deprecated the original HTTPX test client | Checked installed source, switched the dev lock to its supported `httpx2` dependency, reran HTTP tests without the warning |
| Low | Generated migration formatting failed lint | Reformatted and split the constraint string; lint and migration round trip pass |
| Low | Development tooling's initial lock omitted packaging dependencies treated specially by pip-tools | Regenerated with `--allow-unsafe` to pin pip/setuptools too; installed versions match the pins |

Scope limitations, tracked in the checklist: development identity permits
impersonation; Compose shares a development DB superuser; inventory equality
depends on mutation services; locks lack artifact hashes; base image tags are
mutable; no email delivery, real auth, frontend or AWS path exists yet. These
are explicit local-milestone limits, not findings cleared for public deployment.

Review checked parameterized ORM queries, strict capacities and bounded keys,
extra-field rejection, ownership/admin filters, lock order, rollback and commit
timing, database constraints/indexes/FKs, migration/model agreement, build context,
exec-form startup, non-root user, health checks, migration ordering, native test
cleanup and documentation. Terraform, browser rendering and deployment review
are deferred because their implementations do not exist. A review and passing
checks do not prove the absence of defects.

## Verification

The installed versions used include Python 3.14.7, PostgreSQL 18.6, Docker 29.9.0,
Compose 5.6.0, FastAPI 0.143.0, SQLAlchemy 2.0.54, Alembic 1.20.0,
psycopg 3.3.6, Pydantic 2.14.1 and pytest 9.1.1. Other resolved versions are in
the lockfiles. Package installation, actual imports and test execution verified
compatibility in this environment.

| Command/check | Observed result |
| --- | --- |
| `python3 -m venv .venv`, pip-tools installation, `pip-compile`, locked package installation | Completed; exact runtime and development lockfiles generated |
| `alembic revision --autogenerate --rev-id 0001` against the isolated PostgreSQL cluster | Generated the initial migration, then reviewed/froze it |
| Final `bash scripts/test-local.sh -q` after review regression tests | **25 passed in 1.20s**, no warnings; temporary server stopped |
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
counter/count agreement. This is genuine database overlap, not a mock or an
HTTP throughput claim.

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

## Run, inspect, and next step

Follow [README.md](../README.md) for Compose startup, demo commands, SQL/log
inspection and the native test runner. Inspect API routes at
<http://127.0.0.1:8000/docs> after startup. The initial development identity has
been replaced by the authenticated sessions described in Milestone 2.

The next milestone is registration/login and replacing development identity with
real authenticated sessions and role checks, followed by authentication and
cross-user security tests, migrations, container checks and another review pass.
The complete phased plan and cost/failure decisions are in
[architecture.md](architecture.md) and [checklist.md](checklist.md).
