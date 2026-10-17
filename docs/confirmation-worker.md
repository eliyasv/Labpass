# Confirmation worker deployment

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

## Lambda and queue contract

| Setting | Value |
| --- | --- |
| Packaging | Container image digest, x86_64, explicit existing Python handler |
| Release | Published numeric version behind the `live` alias; SQS targets the alias |
| Runtime limits | 60-second timeout, 512 MiB memory, 512 MiB `/tmp` |
| Network | Two private application subnets, consumer security group, no inbound listener |
| Database | Consumer secret ARN, verified RDS TLS and one pooled connection per execution environment |
| SQS | Batch size 1, zero batching window, `ReportBatchItemFailures` |
| Retry bounds | Source visibility 360 seconds; redrive after five receives; DLQ retains fourteen days |
| Logs | `/aws/lambda/<name_prefix>-confirmations`, seven-day retention |

The function's environment contains endpoint metadata, sender address and the
consumer secret ARN. Lambda supplies AWS region and temporary credentials;
Terraform does not set reserved AWS credential/region environment variables.
Database passwords remain in Secrets Manager. Private HTTPS calls to Secrets
Manager and SES use the existing NAT path. The handler's source validation,
delivery claims and partial failures are documented in [AWS workers](aws-workers.md).

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

## SES identity and feedback

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
Service acceptance is not mailbox delivery; SES acceptance followed by a failed
database completion can still produce a duplicate on retry.

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
