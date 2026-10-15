# Database runtime

## RDS configuration

| Setting | Value |
| --- | --- |
| Engine | PostgreSQL 18.6; target-region orderability lookup |
| Instance | `db.t4g.micro`, Single-AZ |
| Storage | 20 GiB gp3, encrypted |
| Network | Isolated database subnets; no public endpoint |
| TLS | `rds.force_ssl=1`; clients use `sslmode=verify-full` and the public RDS CA bundle |
| Authentication | SCRAM; RDS-managed master password |
| Backups | Seven-day retention; final snapshot enabled |
| Deletion protection | Enabled by default |

Database ingress permits TCP 5432 from the API, relay, consumer, migration and
bootstrap security groups. Client groups permit PostgreSQL to the database group
and HTTPS egress through the application subnets' NAT route.

The database is an AZ failure point. Two database subnets support placement;
the configured instance has no standby. Restore and failover have not been tested.

References: [RDS password management](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-secrets-manager.html),
[PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

## Credentials and access

Terraform creates four empty Secrets Manager secrets. The bootstrap command
generates their initial credentials through the SDK. Passwords are absent from
Terraform inputs, state and outputs. Runtime IAM roles read only their own secret;
the bootstrap role can read the master secret and read/write the four role secrets.

| Database role | Privileges |
| --- | --- |
| `labpass_api` | Auth and booking table reads/writes; outbox SELECT/INSERT; delivery SELECT for readiness |
| `labpass_relay` | Outbox SELECT/UPDATE |
| `labpass_consumer` | Users/bookings/outbox SELECT; delivery SELECT/INSERT/UPDATE |
| `labpass_migration` | `public` schema ownership, migrations and table grants |

Runtime roles have no schema creation, table ownership, truncation or migration
permissions. Workers have no inventory writes. PUBLIC database/schema privileges
are revoked. Table privileges are explicit in `backend/labpass/database_roles.py`;
new tables require corresponding grant changes.

## Runtime configuration

| Variable | Value |
| --- | --- |
| `LABPASS_AWS_ENABLED` | `true` |
| `AWS_REGION` | `us-east-1` |
| `LABPASS_DB_HOST` | RDS address from the `database` Terraform output |
| `LABPASS_DB_NAME` | `labpass` |
| `LABPASS_DB_PORT` | `5432` |
| `LABPASS_DB_CA_FILE` | `/app/certs/rds-global-bundle.pem` in the backend image |
| `LABPASS_DB_SECRET_ARN` | Role-specific secret ARN; bootstrap uses the master ARN |
| `APP_ORIGIN` | Configured HTTPS browser origin; required for API/admin commands |
| `LABPASS_COOKIE_SECURE` | `true` for the cloud API |

Cloud API configuration rejects `DATABASE_URL`. API, relay and consumer entry
points reject secrets containing another component's database username. API
configuration has no queue or SES dependency.

The API serializes credential refresh across threads and caches credentials for
five minutes. Refresh disposes the expired pool before fetching `AWSCURRENT`;
SDK failure returns a sanitized 503 and suppresses further secret calls for five
seconds. Checked-out connections may finish work after their pool is retired.
The API pool permits five connections per process with no overflow. Worker pools
permit one; deployment concurrency must fit the database connection limit.

Role-secret rotation scheduling and deployed rotation checks remain pending.

## Bootstrap and migrations

Requires an authenticated bootstrap role and a host with database connectivity.
Obtain endpoint and ARN metadata from the Terraform outputs:

```bash
terraform -chdir=infra/foundation output -json database
terraform -chdir=infra/foundation output -json runtime_access
```

Set the runtime variables above and `LABPASS_DB_SECRET_ARN` to the master ARN.
Set `LABPASS_API_SECRET_ARN`, `LABPASS_RELAY_SECRET_ARN`,
`LABPASS_CONSUMER_SECRET_ARN` and `LABPASS_MIGRATION_SECRET_ARN` to the four
role-secret ARNs from `database.secret_arns`. From `backend/`:

```bash
python -m labpass.bootstrap_database \
  --api-secret-arn "$LABPASS_API_SECRET_ARN" \
  --relay-secret-arn "$LABPASS_RELAY_SECRET_ARN" \
  --consumer-secret-arn "$LABPASS_CONSUMER_SECRET_ARN" \
  --migration-secret-arn "$LABPASS_MIGRATION_SECRET_ARN"
```

Append `--validate` for configuration-only checks without AWS/database calls.
Bootstrap holds a PostgreSQL session advisory lock across credential setup,
role creation and migrations. It commits roles before connecting as the migration
user, then upgrades to Alembic head and applies table grants in one transaction.
Existing secret credentials are reused; rerunning completes interrupted setup.
Privileged existing roles, unexpected usernames and cross-account/duplicate
role-secret ARNs are rejected.

Secrets Manager and PostgreSQL have separate commits. A failed bootstrap can
leave initialized secrets or committed roles; it does not indicate readiness.
Operator launch templates and host commands are documented in
[Application hosting](application-hosting.md#bootstrap-and-migration-jobs).

For subsequent migrations, use the migration IAM role and set
`LABPASS_DB_SECRET_ARN` to its secret:

```bash
python -m labpass.migrate
```

Expected outputs: `Database roles, migrations and grants applied` for bootstrap;
`Database migrations applied` for subsequent migrations. Runtime services never
run migrations at startup. Serialize deployment migration jobs.

Verification: [Database and host boundaries](verification.md#database-and-host-boundaries).
