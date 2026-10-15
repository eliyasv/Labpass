# Milestone 5B: database and runtime access

Verified offline on 14 October 2026. AWS provisioning, deployed permissions and
RDS TLS handshakes remain unverified.

## Implementation

| Component | Configuration |
| --- | --- |
| RDS | Private PostgreSQL 18.6, Single-AZ `db.t4g.micro`, encrypted 20 GiB gp3, seven-day backups and final snapshot |
| Database networking | Two isolated subnets; TCP 5432 from five workload groups; no database egress rules |
| Credentials | RDS-managed master; four role secrets initialized by SDK bootstrap outside Terraform |
| IAM | Separate secret reads, bootstrap secret writes and relay/consumer SQS permissions |
| Database roles | Restricted API/relay/consumer grants; migration schema owner; PUBLIC privileges revoked |
| API | Opt-in cloud configuration, HTTPS cookies, role validation, five-minute credential cache and five-connection pool |
| Bootstrap | PostgreSQL session advisory lock; repeatable credential/role setup, Alembic upgrade and table grants |

Runtime pools require hostname/CA verification. Expired API pools are retired
before refresh; SDK failure produces a sanitized 503 with a five-second refresh
backoff. Worker entry points reject another component's database credentials.

The database orderability lookup checks the selected version/class during a real
plan. Offline tests replace the provider; they do not establish region availability.

## Verification

| Command/check | Result |
| --- | --- |
| `bash scripts/test-local.sh -q` | **178 passed** against PostgreSQL 18; includes 43 new database/access tests |
| `.venv/bin/python -m pytest -q scripts/tests` | **9 passed** |
| `.venv/bin/ruff check backend scripts` | Passed |
| `.venv/bin/ruff format --check backend scripts` | Passed, 49 files |
| `.venv/bin/python -m pip check` | No broken requirements |
| `.venv/bin/python scripts/export-openapi.py --check frontend/openapi.json` | Contract unchanged |
| Terraform formatting, provider validation and mocked tests | **7 passed**, including private RDS, secret scopes and invalid engine/class inputs |
| API and Lambda image builds | Passed |
| Offline Lambda runtime smoke | Imports, handler and runtime emulator passed with networking disabled |
| Backend image bootstrap CLI | Entry point and arguments available without network access |

Privilege tests use fresh PostgreSQL databases and a non-superuser bootstrap
operator with CREATEROLE. Real runtime connections exercise authentication,
booking/retry/cancellation, publication and duplicate suppression. Runtime roles
are denied DDL, truncation, migration-table access and worker inventory writes.
A grant-failure injection verifies a subsequent bootstrap completes setup.
Secrets Manager responses are stubbed; SDK network requests are forbidden.

## Remaining integration

Bootstrap/compute hosts, ALB, frontend hosting, deployment workflows, SES/logging/
ECR/SSM permissions and Lambda VPC attachment remain pending. Role-secret rotation,
RDS restore/failover, database connection limits and actual IAM/network behavior
have not been verified in AWS.

Configuration and commands: [Database runtime](database-runtime.md) and
[Terraform](../infra/README.md).
