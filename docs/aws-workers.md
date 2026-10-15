# AWS worker contract for Terraform

Cloud worker code and packaging are verified offline. AWS workload deployment
remains pending. Local Compose uses ElasticMQ and Mailpit without AWS credentials.

## Entry points and configuration

Lambda image: build `backend/Dockerfile.lambda` with the `backend` context;
handler `labpass.lambda_handler.lambda_handler`. The official
[Python 3.14 Lambda image](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html)
includes the runtime interface client/emulator. The image installs the project's
existing Python lock into `/var/task` so the tested SDK overrides the bundled SDK.
Only x86_64 has been built/tested. Deployment requires an immutable image digest.
Local base tags are mutable; Python locks lack artifact hashes.

Relay: use the backend image with command `python -m labpass.aws_relay`.
`--once` processes at most five due outbox events and returns a failure exit code
if processing raises. `--validate` checks configuration and the CA file without
creating SDK clients or contacting AWS. SIGTERM/SIGINT finish the current batch
then dispose the pool. Backlog/last-success monitoring and service supervision
remain pending.

Required non-secret runtime settings:

| Variable | Contract |
| --- | --- |
| `LABPASS_AWS_ENABLED` | Exactly `true`; absent by default in local Compose |
| `AWS_REGION` | Explicit commercial AWS region; service/engine availability must be checked before Terraform selects it |
| `LABPASS_QUEUE_ARN` | Standard SQS ARN, same region/account as the secret; FIFO is rejected |
| `LABPASS_DB_SECRET_ARN` | Full Secrets Manager ARN, including generated suffix |
| `LABPASS_DB_HOST` | Actual RDS hostname in the selected region; no URL, CNAME, localhost or query parameters |
| `LABPASS_DB_NAME` | Database identifier |
| `LABPASS_DB_CA_FILE` | Absolute readable PEM CA bundle path; Lambda defaults to `/var/task/certs/rds-global-bundle.pem`; relay uses `/app/certs/rds-global-bundle.pem` |
| `LABPASS_SES_FROM` | Required by Lambda; normalized address belonging to the verified SES identity. Relay does not require it |
| `LABPASS_DB_PORT` | Optional, default `5432` |

Do not supply a database URL/password in cloud environment variables. The worker
reads `AWSCURRENT` using
[Secrets Manager GetSecretValue](https://docs.aws.amazon.com/boto3/latest/reference/services/secretsmanager/client/get_secret_value.html).
The secret's JSON must contain nonempty string fields `username` and `password`.
Additional fields are ignored; hostname/database/TLS come from deployment
configuration. Use separate restricted relay and consumer database credentials;
relay and Lambda entry points require `labpass_relay` and `labpass_consumer`
respectively. Master/API/migration credentials are rejected.

The cache lasts five minutes. Refresh disposes the old pool before fetching a new
secret; failure cannot fall back to expired cached credentials. Lambda checks the
cache once per invocation, so an already running invocation can retain its
credentials until completion. Rotation can temporarily fail a connection;
retry recovers after refresh. Live rotation remains an AWS staging check.

All cloud database connections use `sslmode=verify-full`, the checked-in public
RDS trust bundle, READ COMMITTED, pre-ping and one pooled connection with no
overflow. PostgreSQL connection/pool/lock/statement waits are bounded. SQL
parameters and upstream SDK exception text are omitted from application logs.
See [RDS PostgreSQL TLS](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html).

AWS SDK clients use the normal credential provider chain, supplied by execution
roles in deployment, with no code-defined keys. Environment/shared configuration
endpoint overrides are ignored. Connect/read timeouts are 2/5 seconds; SDK retry
count is one total attempt, leaving retry accounting to PostgreSQL and SQS.
Only explicit cloud mode can use real AWS endpoints. Offline adapter tests use
stubbed SDK responses and require no AWS credentials. See
[Boto3 role credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).

## SQS, Lambda and email settings

Required workload configuration:

| Setting | Value / reason |
| --- | --- |
| Lambda timeout | `60` seconds; handler refuses to start a record with more than 60 seconds remaining |
| Delivery lease | `120` seconds, longer than an admitted invocation can remain alive |
| Record admission | At least `30000` ms remaining, checked again after secret retrieval |
| Source visibility | At least `360` seconds for a 60-second function with zero batching window |
| Event-source response | `ReportBatchItemFailures` |
| Batch size/window | Start at `1` / `0` seconds; mixed batches up to `10` are covered by handler tests |
| DLQ redrive | `maxReceiveCount` at least `5`; retention longer than source retention, alarm on depth |
| Concurrency | Set reserved concurrency and mapping maximum concurrency within the RDS connection limit before enabling the mapping |

AWS recommends source visibility of six times the function timeout, adding the
batching window when enabled. A DB lease uses the database clock and does not
extend SQS visibility. If an invocation runs out of time, its claim eventually
expires; the later SQS retry can reclaim it. Admission checks reduce timeout
risk but cannot guarantee completion during a network failure. Measure real
latency before increasing batch size. See
[SQS mapping configuration](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html).

The handler checks the configured source ARN, uses the authoritative event in
PostgreSQL and returns only failed/deferred message IDs. Bad invocation shapes
fail the entire batch. Initialization failures are attempted once per batch;
records remain retryable, with no raw event/body/exception logging. A successful
response lets the event-source mapping acknowledge successful records; the handler
does not call `DeleteMessage`. Enable the response type or failed records can be
acknowledged as success. See
[partial batch responses](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-errorhandling.html).

SES uses `sesv2.send_email` with a single recipient and plain UTF-8 subject/body.
A nonempty `MessageId` records service acceptance, not mailbox delivery.
Rejection/unknown acceptance retains a retryable delivery; cancelled bookings
observed before claiming are skipped. SES acceptance followed by DB completion
failure can send a duplicate after lease expiry.
See [SES SendEmail](https://docs.aws.amazon.com/boto3/latest/reference/services/sesv2/client/send_email.html).
Identity/DKIM verification, sandbox recipient restrictions, quotas, bounce and
complaint handling remain required deployment/operations work.

## IAM and database access

Policies require resource ARNs from Terraform resources and outputs.
Terraform defines role-specific secret access and source-queue permissions.
Database bootstrap installs the table grants. Optional EC2 hosting adds ECR,
SSM and component log access. Lambda SES/logging/VPC permissions remain pending.
See [Database runtime](database-runtime.md) and [Application hosting](application-hosting.md).

| Principal | Minimum intended permissions |
| --- | --- |
| EC2 relay role | `sqs:SendMessage` on the source queue; `secretsmanager:GetSecretValue` on its relay secret; logs to its configured log group |
| Lambda execution role | `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on the source queue; `secretsmanager:GetSecretValue` on its consumer secret; `ses:SendEmail` on the verified identity with `ses:FromAddress` restricted to `LABPASS_SES_FROM`; logs to its configured log group |
| Secret/queue KMS permissions | For customer-managed keys, restrict decrypt permissions to required keys/services/contexts; SQS publishers need `kms:Decrypt` and `kms:GenerateDataKey` on the queue key, consumers need `kms:Decrypt` |
| Lambda VPC attachment | Required ENI management permissions; review AWS's separation of Lambda service ENI operations from function-code privileges |
| Relay database role | SELECT/UPDATE outbox; database CONNECT/schema USAGE, no ownership or DDL |
| Consumer database role | SELECT outbox/bookings/users; SELECT/INSERT/UPDATE delivery claims; database CONNECT/schema USAGE, no workshop/inventory writes or DDL |
| Migration role | Separate controlled schema/role privileges; neither worker migrates on startup |

SES permissions use the `ses` IAM prefix even though the SDK client is `sesv2`.
See [SES IAM conditions](https://docs.aws.amazon.com/ses/latest/dg/control-user-access.html),
[Lambda SQS permissions](https://docs.aws.amazon.com/lambda/latest/dg/services-sqs-configure.html),
[encrypted SQS permissions](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-key-management.html)
and [Lambda VPC permissions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html).

## Private connectivity and release order

Lambda attaches to private subnets to reach RDS on PostgreSQL's configured port.
RDS security groups admit only the API/relay/consumer/migration/bootstrap groups.
For SDK HTTPS calls, provide either an explicit NAT route or interface endpoints
with private DNS and port-443 security-group access for Secrets Manager and the
required queue/SES paths. SES's documented **API** endpoint is distinct from its
SMTP endpoint; this sender uses HTTPS, so an SMTP-only endpoint cannot serve it.
Verify API endpoint availability in the chosen region before committing to an
endpoint-only design. A public subnet alone does not give VPC-attached Lambda
internet access. See
[Lambda VPC networking](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
and [SES endpoints](https://docs.aws.amazon.com/ses/latest/dg/send-email-set-up-vpc-endpoints.html).

EC2 also needs explicit ECR API/DKR and S3 layer retrieval, SSM, logs and bootstrap
paths. Lambda image retrieval is performed by the Lambda service with appropriate
ECR repository permissions. Terraform defines a zonal NAT, an S3 gateway endpoint
and Single-AZ RDS. EC2 launch templates use these paths for SDK calls, package
installation and ECR retrieval. AWS network/permission checks remain unverified.

Planned release: OIDC-authenticated CI builds and tests immutable images; a
controlled job runs additive migrations once; configure roles/secrets/TLS;
deploy API/relay and Lambda versions; then enable the source mapping and run a
real end-to-end smoke. Serialize releases so an older job cannot overwrite a
newer deployment. Workload Terraform and GitHub Actions remain pending.
The cloud API loads its own database secret at runtime. Bootstrap and controlled
migration commands are documented in [Database runtime](database-runtime.md).

## Run offline

From the repository root:

```bash
bash scripts/test-local.sh -q
docker build -f backend/Dockerfile.lambda -t labpass-lambda:m4b backend
docker run -d --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m --user 10001:10001 \
  --name labpass-m4b-lambda-verification labpass-lambda:m4b
docker exec -i labpass-m4b-lambda-verification python < scripts/smoke-lambda.py
docker exec labpass-m4b-lambda-verification python -m pip check
docker stop labpass-m4b-lambda-verification
```

Expected output: `Lambda offline smoke passed` and `No broken requirements found`.
The smoke checks direct handler behavior and actual runtime-emulator invocations,
using only container loopback. Empty batches succeed; missing cloud configuration
or insufficient invocation time returns retryable IDs. AWS integration remains
unverified. The suite uses real PostgreSQL and boto3 Stubber
with SDK network requests forbidden. Test-only resource identifiers are fictional.

The container is retained after stopping. Restart the same image with
`docker start labpass-m4b-lambda-verification`. After rebuilding, use a fresh
container name to test the new image.
