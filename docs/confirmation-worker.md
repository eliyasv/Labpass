# Confirmation processing

The EC2 relay publishes committed booking events to SQS. Lambda consumes those
events and sends confirmation emails through SES. Local Compose substitutes
ElasticMQ and Mailpit. [Booking-to-email sequence](architecture.md#booking-and-confirmation-flow).

- [Worker responsibilities](#worker-responsibilities)
- [Terraform inputs](#inputs)
- [Entry points and runtime configuration](#entry-points-and-configuration)
- [Queue timing and Lambda limits](#sqs-lambda-and-email-settings)
- [IAM and connectivity](#iam-boundaries)
- [SES setup](#ses-identity-and-feedback)
- [Activation and inspection](#activation-and-inspection)
- [Offline verification](#run-offline)

## Worker responsibilities

| Worker | Input | Action | Completion state |
| --- | --- | --- | --- |
| EC2 relay | Due outbox row in PostgreSQL | Publish event ID/type to SQS | Update the outbox publication state |
| Lambda consumer | SQS record delivered by the event-source mapping | Read booking data, claim delivery and send through SES | Record `sent`/`skipped`, or report failure for retry |

The relay does not send email; the consumer does not reserve seats. The outbox
keeps publication work in the same commit as the booking. The delivery claim
coordinates senders when messages are retried or duplicated. These are separate
database records because publishing an event and sending an email are separate
operations.

## Inputs

Terraform enables the workload when `confirmation_worker` is supplied. It uses
the foundation's Lambda ECR repository, source queue/DLQ, private subnets, RDS,
consumer security group, execution role and consumer database secret.

| Field | Requirement |
| --- | --- |
| `image_digest` | Immutable `sha256:` digest of the x86_64 image built from `backend/Dockerfile.lambda` and published to the Lambda repository |
| `email_domain` | Lowercase domain for a new SES identity in `us-east-1` |
| `sender_email` | Normalized lowercase address in that exact domain; alphanumeric local-part groups separated by `.`, `_`, `+` or `-` |
| `hosted_zone_id` | Existing authoritative public Route 53 zone containing the email domain |
| `max_concurrency` | Integer `2`–`10`; default `2`, limits SQS invocations and sets function reserved concurrency when enabled |
| `reserve_concurrency` | Default `true`; set `false` to use shared account concurrency while retaining the SQS mapping limit |
| `verified_recipient_emails` | Default empty set; exact individually verified SES recipient addresses needed for identity authorization during sandbox testing |
| `mapping_enabled` | Default `false`; enable only after database bootstrap, SES/DKIM verification and account/recipient checks |

Setting `confirmation_worker = null` omits Lambda, its additional permissions,
SES identity/configuration, DKIM records, event metrics and log group. Existing
foundation queues, database and runtime roles retain their separate ownership.
Public-zone delegation and ownership of any existing SES identity/DNS records
must be resolved before applying; existing resources are not adopted or
overwritten automatically.

## Entry points and configuration

Lambda image: build `backend/Dockerfile.lambda` with the `backend` context;
handler `labpass.lambda_handler.lambda_handler`. The image installs hash-verified
project dependencies into `/var/task`, overriding the bundled SDK. Release bases
use pinned digests. Only x86_64 has been built/tested. The `release` target uses
the AWS Runtime API; `local` adds the emulator for offline verification.

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

**Queue visibility** is the time SQS hides a received message before it becomes
eligible for retry. A **delivery lease** is the separate PostgreSQL ownership
period for one sender. The Lambda timeout limits invocation lifetime. The values
below give a timed-out invocation's claim time to expire before the queue retries.

Required workload configuration:

| Setting | Value / reason |
| --- | --- |
| Packaging | x86_64 container image digest; published numeric version behind the `live` alias |
| Memory and storage | 512 MiB memory and 512 MiB `/tmp` |
| Network | Two private application subnets, consumer security group, no inbound listener |
| Logs | `/aws/lambda/<name_prefix>-confirmations`, seven-day retention |
| Lambda timeout | `60` seconds; handler refuses to start a record with more than 60 seconds remaining |
| Delivery lease | `120` seconds, longer than an admitted invocation can remain alive |
| Record admission | At least `30000` ms remaining, checked again after secret retrieval |
| Source queue | Visibility 360 seconds; retention four days |
| Event-source response | `ReportBatchItemFailures` |
| Batch size/window | Start at `1` / `0` seconds; mixed batches up to `10` are covered by handler tests |
| DLQ | Redrive after five receives; retention fourteen days. A depth alarm remains unimplemented |
| Concurrency | Bound mapping maximum concurrency within the RDS connection limit; function reserved concurrency is optional |

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

The function's environment contains endpoint metadata, sender address and the
consumer secret ARN. Lambda supplies AWS region and temporary credentials;
Terraform does not set reserved AWS credential/region environment variables.
Database passwords remain in Secrets Manager. Private HTTPS calls to Secrets
Manager and SES use the existing NAT path.

With `reserve_concurrency = true`, reserved concurrency bounds active invocations
across function versions. With `false`, the SQS mapping still limits this queue's
invocations, but the function shares regional concurrency with other functions.
Direct invocations and other event sources are outside the mapping's limit.
Idle execution environments can retain database connections, including during alias
updates; the concurrency setting is not a global database-connection limit.
Check RDS connection headroom and available regional concurrency before activation
or increasing concurrency. Reserved concurrency requires leaving 100 executions
unreserved; shared concurrency does not require a reservation. Retain image digests
referenced by deployed versions so Lambda can retrieve them after inactivity.

## IAM boundaries

The consumer role reads only its database secret and the source queue. Additional
permissions allow writes to its pre-created log group and `ses:SendEmail` on the
selected domain identity/configuration set, restricted by an exact
`ses:FromAddress` condition.

SES can also authorize against an individually verified recipient identity.
`verified_recipient_emails` adds only those identity ARNs in the deployment account
and region. The same sender-address condition applies to every allowed identity;
recipient identities cannot be used as alternative senders. Keep recipient values
in private Terraform inputs. This list grants identity access; it does not verify
recipients or restrict all destinations to the list.

Lambda's required EC2 interface actions use `Resource="*"`. A conditional deny
on `lambda:SourceFunctionArn` prevents function code from using those actions
while preserving Lambda service ENI management. The ECR repository policy grants
the Lambda service image reads only for this function's unqualified/qualified
ARNs. Deployment-role ECR/IAM permissions remain separate from runtime access.

References: [Lambda VPC permissions](https://docs.aws.amazon.com/lambda/latest/dg/configuration-vpc.html),
[Lambda image retrieval](https://docs.aws.amazon.com/lambda/latest/dg/images-create.html),
[SES authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sesv2.html).

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

## SES identity and feedback

SES uses `sesv2.send_email` with a single recipient and plain UTF-8 subject/body.
A nonempty `MessageId` records service acceptance, not mailbox delivery.
Rejection/unknown acceptance retains a retryable delivery; cancelled bookings
observed before claiming are skipped. SES acceptance followed by DB completion
failure can send a duplicate after lease expiry.
See [SES SendEmail](https://docs.aws.amazon.com/boto3/latest/reference/services/sesv2/client/send_email.html).

Terraform creates an SES domain identity with 2048-bit Easy DKIM and publishes
its three CNAME records in Route 53. The identity uses the confirmation
configuration set by default, so the existing SDK sender requires no change.
Configuration-set suppression covers bounces and complaints.

SES publishes send, delivery, bounce, complaint, rejection and delivery-delay
events to CloudWatch using the `ses:configuration-set` dimension. This keeps
metric cardinality tied to the configuration set; recipient addresses and message
IDs are not dimensions. Event-publishing metrics are billable. Alert actions and
application-level feedback processing remain pending.

The configuration uses SES's default MAIL FROM domain. Existing SPF, custom
MAIL FROM and DMARC policies are not changed. Review domain policy and deployed
DKIM alignment before public email use. SES sandbox restrictions, sending access,
quotas and recipient verification are account-level deployment requirements.

References: [SES identities](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html),
[CloudWatch event publishing](https://docs.aws.amazon.com/ses/latest/dg/event-publishing-add-event-destination-cloudwatch.html),
[configuration-set suppression](https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list-config-level.html).

## Activation and inspection

1. Publish the tested image and supply its digest; keep the mapping disabled.
2. Complete [database bootstrap and migrations](database-runtime.md#bootstrap-and-migrations).
3. Verify public DKIM records, SES identity/DKIM status, sandbox recipients and
   quotas. Terraform blocks mapping enablement if SES verification or DKIM is pending.
4. Enable `mapping_enabled` through Terraform, then exercise a real booking,
   confirmation, duplicate delivery and retry/DLQ recovery.

Terraform cannot infer database bootstrap success, mailbox delivery or production
sending access from SES domain verification. These remain explicit deployment
checks. Polling can be stopped by applying `mapping_enabled = false`; already
running invocations may finish. Coordinate image/alias releases with compatible
schema migrations and serialize releases.

```bash
terraform -chdir=infra/foundation output -json confirmation_worker
aws sesv2 get-email-identity --region us-east-1 \
  --email-identity "${LABPASS_SES_DOMAIN:?Set the configured email domain}"
aws sesv2 get-account --region us-east-1
aws lambda get-event-source-mapping --region us-east-1 \
  --uuid "${LABPASS_CONFIRMATION_MAPPING_UUID:?Set the worker output mapping UUID}"
```

[Infrastructure tests](verification.md#infrastructure-and-release-checks) ·
[Deployment evidence and coverage](verification.md).

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
or insufficient invocation time returns retryable IDs. This smoke does not
exercise AWS services. The unit suite uses real PostgreSQL and boto3 Stubber with
SDK network requests forbidden; test-only resource identifiers are fictional.
Separate [live evidence](verification.md#live-aws-verification) covers the
successful deployed booking/email path.
