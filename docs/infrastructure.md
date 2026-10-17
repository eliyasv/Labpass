# Infrastructure design

Terraform defines networking, repositories, queues, private RDS, runtime access,
application hosting, frontend delivery and confirmation workloads in `us-east-1`.
The foundation composes five local modules: network, database, application,
frontend and confirmations. Shared ECR repositories and SQS queues remain in
the root. Provider configuration and state ownership remain at the root.
[Module interfaces](../infra/modules/README.md).

## Network boundaries

A `10.42.0.0/16` VPC spans two standard availability zones discovered in the
target account. Each zone has separate public, application and database subnets.

| Subnets | CIDRs | Routing |
| --- | --- | --- |
| Public | `10.42.0.0/24`, `10.42.1.0/24` | Internet gateway |
| Application | `10.42.10.0/24`, `10.42.11.0/24` | Shared zonal NAT; S3 gateway endpoint |
| Database | `10.42.20.0/24`, `10.42.21.0/24` | Local VPC route only |

Automatic public IP assignment is disabled on all subnets. The default security
group has no ingress or egress rules. Separate API, relay, consumer, migration
and bootstrap groups permit PostgreSQL access to the database group and HTTPS
egress. When hosting is enabled, the API accepts port 8000 only from the ALB
group; the ALB accepts HTTPS only from CloudFront origin-facing addresses.
API forwarding additionally requires the configured origin-verification token.

The NAT gateway resides in the first public subnet. Both application zones use
it, creating a shared egress dependency and potential cross-AZ transfer costs.
A NAT gateway per AZ would remove that shared egress dependency. RDS availability
is separate from subnet placement; two database subnets alone do not provide
database failover.

The S3 gateway endpoint is attached to both application route tables. It provides
a route for same-region S3 access, including ECR image layers. Other service and
bootstrap traffic uses the NAT path. IAM and service policies still control access.
See [ECR VPC connectivity](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html)
and [NAT availability](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-basics.html).

## Availability and scaling

| Component | Configured deployment | Limit |
| --- | --- | --- |
| ALB | Public subnets in two AZs | Application health still depends on its targets and database |
| API | Two private EC2 instances across two AZs; ASG permits 2–4 while running | No traffic-driven scaling policy |
| Relay | One private EC2 instance; separate ASG permits 1–2 while running | Baseline has no second active relay |
| Database | Single-AZ RDS; subnet group spans two AZs | No standby or automatic Multi-AZ failover |
| Egress | One zonal NAT shared by application subnets | Both application AZs depend on one AZ for NAT traffic |
| Lambda | VPC-connected through both application subnets; bounded SQS concurrency | Database and egress dependencies remain |

The API tier is Multi-AZ, with Single-AZ database and NAT dependencies. ASGs
provide instance replacement and rolling refreshes; no traffic-driven scaling
policy is configured.

## Image repositories

Separate ECR repositories hold API/relay and Lambda images. Configuration enables
immutable tags, AES256 encryption and scan-on-push. Releases reference image
digests rather than mutable tags. `force_delete=true` currently permits repository
removal when images are present. Artifact retention policy remains pending.

## Confirmation queues

| Setting | Source queue | Dead-letter queue |
| --- | --- | --- |
| Type | Standard SQS | Standard SQS |
| Retention | 4 days | 14 days |
| Visibility | 360 seconds | Service default |
| Encryption | SQS-managed | SQS-managed |
| Redrive | After 5 receives | Accepts only this source queue |

The source visibility matches the worker contract for a 60-second Lambda
timeout. Longer DLQ retention preserves failed messages for investigation.
Relay/consumer SQS permissions and the optional Lambda event-source mapping are
defined. The mapping targets a published-version alias, starts disabled and uses
partial batch failures with bounded SQS concurrency. Function-level reserved
concurrency is optional. See
[the AWS worker contract](aws-workers.md#sqs-lambda-and-email-settings).

## Configuration and state

Terraform requires a target account ID and enforces it through the AWS provider's
`allowed_account_ids` setting. Region validation restricts this configuration to
`us-east-1`. Resource names and tags identify the stack and its ownership.

Terraform 1.15.x and AWS provider 6.68.0 are pinned. The provider lockfile records
signed package checksums. State, plans, provider binaries and local variable
files are excluded from Git. The foundation uses a partial S3 backend; the separate
delivery bootstrap defines encrypted, versioned state storage with scoped access
and S3 locking. The bootstrap's own local state must be preserved separately.
Initialization and migration: [CI/CD and release security](delivery.md).

## Database and runtime access

RDS uses PostgreSQL 18.6, `db.t4g.micro`, Single-AZ placement and encrypted 20 GiB
gp3 storage. The orderability data source checks version/class support during a
real plan. Backups retain seven days, deletion protection defaults to enabled and
removal requires a final snapshot. PostgreSQL enforces TLS and SCRAM passwords.

The master password is RDS-managed. Terraform creates four runtime secret
containers; SDK bootstrap initializes credentials and restricted database roles.
Runtime IAM roles read their own secret. The bootstrap role alone reads the
master secret and writes role secrets. See [Database runtime](database-runtime.md)
for privileges, configuration and commands.

## Workload integration

Hosting uses separate API/relay ASGs and explicit operator launch templates with
SSM, ECR and CloudWatch logging access. Configuration and limits:
[Application hosting](application-hosting.md).

Frontend delivery uses private versioned S3 with SigV4 OAC, CloudFront, separate
public/origin ACM certificates and Route 53 records in an existing authoritative
public zone. HTML/API caching is disabled; versioned assets may cache for one
year. The ALB token supports overlap during rotation and is stored in Terraform
state. Configuration: [Frontend delivery](frontend-delivery.md).

Lambda runs in the private application subnets with the consumer role/group and
existing NAT path. SES uses a domain identity, DKIM records in an existing public
zone, suppression and configuration-set delivery metrics. Mapping activation
requires verified SES/DKIM; database bootstrap and account/recipient checks remain
operator prerequisites. See [Confirmation worker deployment](confirmation-worker.md).

Hosted-zone ownership and registrar delegation are prerequisites for each
deployment; the delivery root can own the hosted zone, while registrar settings
are managed separately.
See [Terraform commands](../infra/README.md) and
[deployment and test results](verification.md).
