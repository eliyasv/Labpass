# Milestone 3: local React frontend

Completed 13 October 2026 (Asia/Kolkata). This milestone connects the existing
booking API to a working browser UI. No AWS infrastructure was provisioned.

## What changed and why

React/TypeScript/Vite now provides registration, login/logout, session restoration,
workshop browsing/search, live-on-refresh availability, reservations, booking
history, confirmed cancellation, and admin workshop creation/capacity management.
The responsive UI uses actual server data and existing title/capacity fields;
dates and cancellation deadlines remain deferred. Confirmation email delivery
is not implemented yet.

A non-root Nginx container serves static assets and proxies `/api/*` at the same
browser address. The existing default URL and smoke script stay on port 8000;
the API and DB are internal services. Cookie/Origin/CSRF rules stay intact, with
no CORS relaxation or Origin rewriting. Compose orders DB readiness, one-shot
migrations, API readiness and web readiness.

The browser keeps CSRF state in memory and pending booking UUIDs in tab session
storage, scoped by user/workshop. Response loss keeps the key for manual retry,
including after reload. Successful booking or confirmed cancellation ends the
attempt. A new reservation gets a new key. Auth changes clear previous history
and invalidate stale fetch results. Requests time out after 15 seconds; the client
and Nginx do not automatically retry mutations.

Official references used: [Vite requirements](https://vite.dev/guide/),
[Vite proxy configuration](https://vite.dev/config/server-options),
[React effect cleanup](https://react.dev/reference/react/useEffect),
[OpenAPI TypeScript generation](https://openapi-ts.dev/node),
[Nginx forwarding/retry semantics](https://nginx.org/en/docs/http/ngx_http_proxy_module.html),
and [Playwright browsers](https://playwright.dev/docs/browsers).

## Files changed

- `frontend/package.json`, `package-lock.json`, `tsconfig.json`, `vite.config.ts`:
  exact dependencies, build/type/format checks and local dev configuration.
- `frontend/index.html`, `public/favicon.svg`, `src/main.tsx`, `src/App.tsx`,
  `src/styles.css`: responsive UI, safe text rendering, labeled forms and flows.
- `frontend/src/api.ts`, `src/booking-attempts.ts`: typed requests, error/request
  references, cookies/CSRF and retry-key lifecycle.
- `frontend/openapi.json`, `src/generated/api.ts`, `scripts/check-contract.mjs`,
  root `scripts/export-openapi.py`: backend contract export, generated types and
  drift verification without reading secrets or connecting to a database.
- `frontend/playwright.config.ts`, `tests/fixtures.ts`, `tests/booking.spec.ts`:
  isolated real-PostgreSQL browser tests and generated test/admin accounts.
- `frontend/Dockerfile`, `nginx.conf`, `.dockerignore`, `.prettierignore`, root
  `compose.yaml`, `.gitignore`: production build, non-root serving, proxy/health
  configuration, security headers and local artifact exclusions.
- `README.md`, `docs/architecture.md`, `docs/checklist.md`, this report:
  operation, decisions, evidence and outstanding work.

Backend application code, schema/migrations, existing tests and `test.py` were
unchanged. Git metadata remains unusable; no commit or PR was created.

## Separate review findings and fixes

Reviewed the changed source/configuration, generated contract and lock agreement,
then traced register/login/reload, reserve/retry/cancel/rebook, logout, role
visibility, capacity changes and proxy forwarding end to end.

| Severity | Finding | Fix and evidence |
| --- | --- | --- |
| High | Publishing UI on a different origin would conflict with the existing cookie/Origin contract | Serve UI/API through the same loopback web port; real browser writes, wrong-Origin rejection and legacy HTTP smoke passed |
| High | A lost-response key could survive recovered-booking cancellation, making a later reservation replay the cancelled booking | Retire that pending key after confirmed cancellation; regression verifies the next reservation uses a different key and succeeds |
| Medium | Full inventory or an incomplete history page could disable recovery of an already-committed pending booking | Keep the pending-key retry available despite a full snapshot; test commits on PostgreSQL, drops the response, hides one UI history row and successfully retries with the original key |
| Medium | Delayed session/data fetches could overwrite newer account state | Abort/ignore stale effect results and invalidate data updates on identity changes; session restoration and account switching exercised |
| Medium | Nginx could retain an obsolete API container address after recreation | Resolve the upstream via Docker DNS with a 10-second cache; startup/forwarding verified, forced IP-change recovery not injected |
| Build | Latest TypeScript 7 conflicted with the generator's declared TypeScript 5 peer range | Pin TypeScript 5.9.3; install, dependency inspection, contract generation and strict compile passed without peer overrides |

Additional checks covered password/CSRF storage, request metadata, role enforcement
on the server, escaped workshop titles, input bounds, no permissive CORS,
non-root Nginx/pid/temp permissions, health dependencies, URI/Origin preservation,
API no-store headers and safe Docker contexts. Generated schemas/types are
checked against the actual application contract. No database migration was needed.

## Commands actually executed and results

| Command/check | Observed result |
| --- | --- |
| Official documentation and npm version/engine/peer inspection | Selected compatible current packages; discovered generator/TypeScript peer conflict |
| `npm install --cache /tmp/labpass-npm-cache --fetch-retries=0` after correction | 60 packages added, 61 audited, 0 reported vulnerabilities at install time; lockfile created |
| `.venv/bin/python scripts/export-openapi.py frontend/openapi.json`; `npm run generate` | Export/generation succeeded without a DB connection |
| `npm run check-contract` | Backend snapshot and generated TypeScript match |
| `npm run typecheck`; `npm run build` | Strict compile and production bundle succeeded on host; final JS 239.19 kB, gzip 74.55 kB |
| `npm run format:check`; `npm ls --all --depth=0` | Formatting passed; expected exact direct versions installed, no peer errors |
| `ruff check backend scripts`; `ruff format --check backend scripts` | All checks passed; 25 Python files formatted |
| `.venv/bin/python -m pytest -q scripts/tests` | 9 startup regression tests passed |
| `PLAYWRIGHT_BROWSERS_PATH=/tmp/labpass-playwright npx playwright install chromium --only-shell` | Download succeeded after sandbox network retry; Ubuntu fallback browser used on this OS |
| Compose `-p labpass-m3-verification up --build --wait --wait-timeout 90`, port 8002 | Images built; real PostgreSQL, API and web healthy; migration exited 0 |
| Browser suite before review fixes | 6 passed in 11.5s |
| Expanded final browser suite | **8 passed in 15.2s**, no automatic test retries |
| Default Compose `up --build --wait --wait-timeout 90`, seed, existing HTTP smoke | Started on port 8000; seed and full register/login/book/retry/history/cancel/logout smoke passed through Nginx |
| Web `id`; `nginx -t`; API `alembic check` | UID/GID 101; Nginx config valid; no new upgrade operations detected |
| Headless Chromium on default stack | Frontend HTTP 200, CSP present, Swagger HTTP 200, no page runtime errors or 390px horizontal overflow; desktop/mobile screenshots captured and visually inspected |
| Verification Compose `stop`, then default Compose `ps -a` | Isolated test services stopped with their data retained; default DB/API/web remain healthy and migration exited 0 |

The browser suite uses the production frontend container and real API/database.
Fault injection drops committed HTTP responses or changes only a displayed
history page; it does not replace PostgreSQL or simulate transaction concurrency.
Tests cover cookie flags/HttpOnly visibility, CSRF and wrong-Origin denial,
regular-user admin denial, full inventory, capacity rejection below reservations,
safe HTML-like title rendering, session reload, cancellation/rebooking and logout.
The prior 63-test native backend suite was not rerun: backend/schema code is
unchanged; new integration evidence is the real browser and existing HTTP smoke.

## Untested behavior and remaining risks

- Firefox, WebKit, public HTTPS/Secure cookies, full accessibility audit and
  assistive-technology behavior are not verified. Desktop/390px Chromium was used.
- Pages use offsets; concurrent inserts can shift page boundaries. Search applies
  to loaded workshops. Full multi-page datasets were not tested; browser fixtures
  currently assume their workshops fit in the first 50 rows. Refresh resets lists
  to their first page, and older active bookings may lack a card indicator.
- Storage-disabled reload loses pending keys; in-memory retries still work.
  Cross-tab login/session changes may require a refresh to restore matching CSRF.
- Generated types are compile-time checks rather than runtime JSON validators.
  A malformed backend response is not fully schema-validated in the browser.
- Registration/admin creation do not have booking-style idempotency. Check the
  resulting account/list before repeating an uncertain creation. No automatic
  retries were added for these operations.
- Forced backend IP changes, sustained outages, browser tab crashes and real
  network loss during PostgreSQL COMMIT were not injected. The fault tests drop
  the response only after the server confirms a real commit.
- Native Vite hot reload was configured and compiled, but its complete auth flow
  was not tested; the production Nginx path was tested instead.
- Login throttling, email verification/recovery, scheduled session cleanup,
  restricted DB roles, immutable base image digests, delivery/operations work
  and actual confirmation emails remain outstanding. No production-readiness claim.

## Run and inspect locally

The default project is running at <http://127.0.0.1:8000/>. Create an account,
sign in, reserve the seeded workshop, inspect My bookings, cancel it and sign out.
Administrator provisioning and repeatable browser-test commands are in
[README](../README.md). Use the temporary Compose binary if the plugin is absent.

```bash
/tmp/labpass-compose/docker-compose up --build --wait --wait-timeout 90
/tmp/labpass-compose/docker-compose exec api python -m labpass.seed
python3 scripts/smoke-local.py
/tmp/labpass-compose/docker-compose ps -a
/tmp/labpass-compose/docker-compose logs api web migrate
```

Only the web container publishes port 8000. Existing `/api/*` and `/docs` URLs
remain usable. Local screenshots are `/tmp/labpass-desktop.png` and
`/tmp/labpass-mobile.png`; they are verification artifacts, not source dependencies.

## Next implementation step

Implement the transactional outbox relay and duplicate-safe confirmation
processing. Start with local publication/consumer failure tests, competing relay
instances, stable event IDs and delivery claims. Then prepare AWS SQS/Lambda/SES
integration. Email failure must not reverse bookings; document the SES-success /
recording-failure window without promising exactly-once delivery. Paid AWS
resources and deployment continue to require explicit authorization.
