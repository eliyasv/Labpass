# Milestone 2: authentication

Implemented and verified on 13 October 2026. This report covers
local authentication and its integration with inventory; it does not certify
public deployment readiness.

## Implementation

Replaced development identity with registration, login, current-session lookup
and logout. Passwords use Argon2id. PostgreSQL stores session-token digests and
an eight-hour expiry; the raw token lives only in an HttpOnly cookie. This makes
session state shared across API instances and allows logout revocation without
an additional service. Public registration cannot create an administrator.
A separate operator CLI creates a new admin with an interactively entered password.

Writes require the configured Origin; authenticated writes also require a CSRF
token. Login and `/api/auth/me` return the CSRF value so the upcoming frontend
can restore its state after a reload. API responses are marked `no-store`.
The original booking transaction/lock order, idempotency keys, cancellation and
outbox behavior remain in place, with authenticated user IDs supplied by sessions.

Migration `0002` adds credentials, sessions and case-insensitive email uniqueness.
It preserves existing users, bookings, inventory, idempotency records and events.
Existing fixture accounts retain null passwords and remain unable to log in;
legacy activation/recovery is not implemented. The seed creates only a workshop.

## Files changed

Added:

- `backend/labpass/auth.py`: hashing, credential checks, token digests, CSRF,
  session lookup/creation/rotation/revocation.
- `backend/labpass/create_admin.py`: explicit operator role provisioning.
- `backend/migrations/versions/0002_authentication.py`: additive auth migration.
- `backend/tests/test_auth.py`: credentials, session, CSRF, ownership and failure tests.
- `docs/milestone-2.md`: this report.

Updated:

- `backend/labpass/app.py`, `config.py`, `models.py`, `schemas.py`, `seed.py`.
- `backend/requirements.in`, `requirements.lock`; regenerated development lock
  resolution remains compatible with its existing pinned versions.
- `backend/tests/conftest.py`, `test_api.py`, `test_config.py`, `test_migrations.py`.
- `compose.yaml`, `.env.example`, `scripts/smoke-local.py`.
- `README.md`, `docs/architecture.md`, `docs/checklist.md`, and a historical-note
  addition to `docs/milestone-1.md`.

The initial migration and booking service were preserved.

## Review findings

Reviewed every changed file and traced registration/conflicts, login/rehash,
session rotation, booking ownership, admin checks, expiry/logout, failure before
commit, migrations with legacy data, and container startup. Library APIs were
checked against installed versions, official documentation and actual execution.
Sources and design trade-offs are linked in [architecture.md](architecture.md).

| Severity | Finding | Fix and verification |
| --- | --- | --- |
| Medium | Default request validation could include submitted passwords in error JSON | Removed submitted inputs/context from validation responses; SecretStr handles normal model representation; tests verify password absence in responses and logs |
| Medium | Readiness checked only the workshop schema and could pass before auth migration | Added credential/session schema queries; tests verify readiness fails on `0001` and recovers after `0002` |
| Low | Malformed Origin ports/hosts could pass basic URL checks | Parse/validate host and port at configuration time; reject insecure public-host cookies and non-HTTPS Secure-cookie configuration |
| Low | Initial case-conflict test rolled fixture creation back alongside migration, weakening its evidence | Commit a conflicting legacy dataset first, then verify a failed upgrade preserves both users and revision `0001`; restore only the isolated test schema afterward |
| Low | Existing documentation and HTTP helpers still used development identity | Updated routes, fixtures, smoke test, README and checklist to the cookie/Origin/CSRF contract; header-spoofing tests verify it cannot authenticate or elevate roles |

The CSRF derivation uses the standard-library HMAC API with a per-session secret,
and comparisons use `compare_digest`. Argon2 work is bounded to two concurrent
tasks per process. These controls do not replace attempt-rate throttling or make
the application safe against every browser/credential attack. No unresolved
finding blocks the documented local milestone; deployment hardening remains
explicitly incomplete below.

## Verification

New runtime dependencies are locked to argon2-cffi 25.1.0 and email-validator
2.3.0, with resolved transitive versions. Python 3.14.7, PostgreSQL 18.6,
FastAPI 0.143.0, SQLAlchemy 2.0.54 and Alembic 1.20.0 were used.

| Command/check | Observed result |
| --- | --- |
| `pip-compile --strip-extras` for runtime, `--allow-unsafe` for dev, then locked pip installation | Resolution and installation completed successfully |
| Schema/app import probe using installed packages | Registration schema normalized a `.test` email; app routes constructed successfully |
| Final `bash scripts/test-local.sh -q` after configuration and migration-failure checks | **63 passed in 3.21s**, no warnings; temporary PostgreSQL server stopped |
| `ruff check backend scripts/smoke-local.py`; `ruff format --check` | All checks passed; 23 Python files formatted |
| Host and container `python -m pip check` | No broken requirements found |
| `bash -n scripts/test-local.sh` | Exit 0 |
| Same Compose build/start with `LABPASS_PORT=8001` | Completed; DB/API healthy, migration exited 0, loopback port 8001 published |
| Container `python -m labpass.seed`, `alembic current`, `alembic check` | Seed succeeded; revision `0002 (head)`; no new upgrade operations detected |
| `LABPASS_PORT=8001 .venv/bin/python scripts/smoke-local.py` | Real register/login/me/booking/retry/history/cancel/logout flow passed, including 401 after logout; repeated on final image |
| Container persisted-state inspection after first auth smoke | Revision 0002; 2 preserved passwordless users; 1 new password user; 0 sessions; 0 active bookings; 2 retained outbox events |
| Container `python -m labpass.create_admin --help` | CLI entry point imported and displayed supported options; provisioning function tested with real PostgreSQL |
| Container `id` | UID/GID 10001, non-root runtime |
| Verification Compose `stop` | Verification API/migration/DB stopped; data retained; existing `labpass` stack left running |

Verification reused the isolated project's retained milestone-1 database, then
tested the actual container HTTP port. The native suite creates randomly named
schemas on a temporary real PostgreSQL server. Its 100-worker test still requires
all 100 live requests to overlap as observed database lock waiters and verifies
20 bookings for 20 seats. Authentication tests exercise actual Argon2 hashing and
real database sessions; no SQLite or mock transaction store was substituted.

Additional tests verify salted hashes and rehashing, generic credential errors,
null-password account denial, concurrent/case-only registration conflicts,
expiry, cookie flags, revoked-cookie replay, rotation of CSRF/session tokens,
session use across two app instances, role changes read from DB, cross-user
history/cancellation denial, rejected role injection, missing/hostile Origin,
missing/incorrect CSRF, and login/logout commit failure behavior. Failure hooks
inject pre-commit exceptions while the transactions themselves use PostgreSQL.

## Untested behavior and remaining risks

- Browser automation and real public HTTPS/cookie behavior are not yet tested.
  The Secure-cookie test uses HTTPS URLs through the in-process test client.
- Origin/CSRF checks and bounded Argon2 concurrency are implemented; distributed
  credential-attempt throttling and registration abuse controls are not.
- Email syntax is validated, including local `.test` fixtures, but ownership and
  deliverability are not. Registration conflicts reveal that an email exists.
- Password recovery/legacy credential activation and scheduled cleanup of
  never-revisited expired sessions remain future work. There is no idle timeout;
  sessions have an absolute eight-hour lifetime.
- Authentication finishes before the booking transaction begins. A request
  already authenticated when logout commits may finish; later requests are denied.
- Physical network loss during COMMIT, process crashes and database failover
  were not injected. A lost login response can leave an unused session until expiry.
- The interactive hidden-input admin prompt was not exercised through a human
  terminal; CLI imports/options and the real-DB provisioning function were tested.
- Local DB superuser use, mutable base image tags, artifact hashes, AWS network
  paths, CI/CD, email processing, k6 measurements and restore verification remain
  outstanding. No AWS deployment or paid provisioning ran.

## Run and inspect locally

Follow the current [README](../README.md) to rebuild/start your local stack,
seed its workshop, register/login in Swagger, pass the CSRF header and create an
operator admin. `docker compose up --build --wait --wait-timeout 120` applies
the code and migrations and waits for API health. Legacy fixture accounts cannot
log in; credential activation is not implemented. API inspection uses
`/api/auth/me`, `/api/bookings`, and Swagger; avoid printing password hashes or
session cookies into logs. Native checks run with `bash scripts/test-local.sh -q`.

## Startup race follow-up

An immediate readiness request after container startup could fail with
`ConnectionResetError`, because Compose's "Started" status can precede
application readiness.

The smoke script now polls only the readiness GET for up to 30 seconds, with
two-second maximum request timeouts and a bounded interval. It retries connection
failures and HTTP 503, fails immediately on other HTTP errors or invalid health
responses, and reports the endpoint and log command on timeout. Authentication
and booking mutations retain their original request behavior. Startup uses
[`--wait`](https://docs.docker.com/reference/cli/docker/compose/up/).

Verification: `pytest -q scripts/tests` passed **9 tests** covering transient
failures, bounded deadlines, unexpected status/payload handling and HTTP error
propagation/response closure. `ruff check backend scripts` and
`ruff format --check backend scripts` passed (24 files). A separate review checked
the retry scope, exception ordering (`HTTPError` before `URLError`), response
closure, deadline calculations and docs against the executable commands.

On the local stack, `docker restart labpass-api-1` immediately
followed by the full HTTP smoke passed registration through logout. Compose
`up --wait --wait-timeout 60` also succeeded with the one-shot migration service:
DB/API healthy and migration exited 0. Backend code/schema did not change;
the earlier 63-test PostgreSQL
suite was not rerun for this script/documentation fix.

Next: React/TypeScript/Vite frontend for registration/login, workshop availability,
booking/history/cancellation and admin management, using the documented cookie
and CSRF contract, followed by frontend/backend agreement checks and browser smoke tests.
