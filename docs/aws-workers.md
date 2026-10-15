# AWS worker runtime contract

Cloud worker code and packaging are verified offline. AWS workload deployment
remains pending. Local Compose uses ElasticMQ and Mailpit without AWS credentials.

## Entry points and configuration

Lambda image: build `backend/Dockerfile.lambda` with the `backend` context;
handler `labpass.lambda_handler.lambda_handler`. The image installs hash-verified
project dependencies into `/var/task`, overriding the bundled SDK. Release bases
use pinned digests. Only x86_64 has been built/tested. The `release` target uses
the AWS Runtime API; `local` adds the emulator for offline verification.
Deployment inputs and image/version wiring:
[Confirmation worker deployment](confirmation-worker.md#inputs).

Relay: use the backend image with command `python -m labpass.aws_relay`.
`--once` processes at most five due outbox events and returns a failure exit code
if processing raises. `--validate` checks configuration and the CA file without
creating SDK clients or contacting AWS. SIGTERM/SIGINT finish the current batch
then dispose the pool. EC2 hosting supplies systemd supervision;
backlog/last-success monitoring remains pending.

Common endpoint, database, secret and CA settings:
[Database runtime](database-runtime.md#runtime-configuration).
Worker-specific settings:

| Variable | Contract |
| --- | --- |
| `LABPASS_AWS_ENABLED` | Exactly `true`; local Compose uses ElasticMQ/Mailpit without AWS credentials |
| `AWS_REGION` | Explicit commercial AWS region; Lambda supplies it in deployment |
| `LABPASS_QUEUE_ARN` | Standard SQS ARN in the same region/account as the secret; FIFO is rejected |
| `LABPASS_DB_HOST` | Actual RDS hostname; no URL, CNAME, localhost or query parameters |
| `LABPASS_DB_SECRET_ARN` | Full role-specific ARN, including the generated suffix |
| `LABPASS_DB_CA_FILE` | Absolute readable PEM bundle; Lambda defaults to `/var/task/certs/rds-global-bundle.pem` |
| `LABPASS_SES_FROM` | Required by Lambda; normalized sender in the SES domain. Relay does not require it |

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

Worker database connections use `sslmode=verify-full`, the checked-in public
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

## Permissions and connectivity

Runtime secret/database grants: [Database runtime](database-runtime.md#credentials-and-access).
Relay ECR, SSM and logging: [Application hosting](application-hosting.md).
Consumer queue, SES, logging, ENI and image permissions:
[Confirmation worker deployment](confirmation-worker.md#iam-boundaries).
SES IAM actions use the `ses` prefix although the SDK client is `sesv2`.

Private Lambda reaches RDS through its consumer security group and AWS HTTPS APIs
through the configured NAT route. EC2 also uses ECR API/DKR, the S3 layer path,
SSM, logs and package repositories. Network boundaries:
[Infrastructure](infrastructure.md#network-boundaries).

SES API and SMTP endpoints are distinct; this sender uses HTTPS. An SMTP-only
endpoint cannot serve it. A VPC-attached Lambda in a public subnet does not gain
internet access merely from subnet placement. See
[Lambda VPC networking](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html)
and [SES endpoints](https://docs.aws.amazon.com/ses/latest/dg/send-email-set-up-vpc-endpoints.html).

Initial activation: [Confirmation worker deployment](confirmation-worker.md#activation-and-inspection).
The implemented GitHub Actions workflow updates existing workloads using OIDC,
scanned image artifacts, a controlled migration and serialized rollout. Setup and
live execution requirements: [Delivery](delivery.md).

## Run offline

From the repository root:

```bash
bash scripts/test-local.sh -q
docker build --target local -f backend/Dockerfile.lambda -t labpass-lambda:local backend
docker run --rm -d --network none --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m --user 10001:10001 \
  --name labpass-lambda-verification labpass-lambda:local
docker exec -i labpass-lambda-verification python < scripts/smoke-lambda.py
docker stop labpass-lambda-verification
```

Expected output: `Lambda offline smoke passed`. Dependency consistency is checked
during the image build before pip and ensurepip are removed. The `local` target
adds the emulator for isolated tests; the default `release` target excludes it.
The smoke checks direct handler behavior and actual runtime-emulator invocations,
using only container loopback. Empty batches succeed; missing cloud configuration
or insufficient invocation time returns retryable IDs. AWS integration remains
unverified. The suite uses real PostgreSQL and boto3 Stubber
with SDK network requests forbidden. Test-only resource identifiers are fictional.
