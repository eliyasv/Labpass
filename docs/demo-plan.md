# Temporary AWS demo

Region: `us-east-1`. Spending target: **at most $10 total**, for a one-time demo,
screenshots and teardown. The domain `labpass.shop` is already owned. Use
`demo.labpass.shop` for the frontend and `origin.demo.labpass.shop` for the ALB;
check existing DNS records before creating either. DNS hosting/delegation still
needs confirmation before certificate/record automation.

The initial estimate assumes **two hours of provisioned resources**, including
setup, testing and teardown. This is a planning assumption, not a confirmed
duration. Delays in certificate validation, troubleshooting or deletion extend
the billable session. No credits or Free Tier eligibility are assumed.

## Deployment choices

| Component | Demo choice | Trade-off |
| --- | --- | --- |
| Network | Two AZs, private application subnets and isolated DB subnets | Retains the target layout |
| Egress | One zonal NAT gateway plus an S3 gateway endpoint | Both AZs depend on one AZ's egress; cross-AZ traffic can be billed |
| Backend | Initially plan two x86_64 `t3.small` instances, one per AZ | More memory than micro instances; exact AMI/image/bootstrap checks remain pending |
| Database | Plan Single-AZ PostgreSQL on `db.t3.micro`, 20 GiB gp3 | No DB failover; engine/class availability and connection budget need an actual regional check |
| Frontend/API | Private S3/OAC, CloudFront, public ALB restricted to origin traffic | Existing domain supports public HTTPS with ACM; certificates/forwarding need validation |
| Confirmations | Standard SQS/DLQ, Lambda, SES | Use bounded concurrency and verified sandbox recipients for the demonstration |
| Operations | Short log retention, selected alarms and billing notifications | Billing notifications are delayed; they do not enforce a spending ceiling |

Only networking, ECR and queues are implemented in the current Terraform
foundation. Other rows are choices for the remaining code, not deployed resources.
Workload-specific security groups/IAM must precede any deployment.

The single NAT's connectivity covers ECR API/DKR, SSM, Secrets Manager, logs,
SQS/SES APIs and OS bootstrap/package retrieval. The S3 gateway endpoint avoids
NAT processing for same-region S3 traffic, including ECR image layers. Database
subnets have no internet or NAT route. Gateway access still requires appropriate
IAM and endpoint/bucket policies. See
[ECR connectivity](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html)
and [NAT/S3 gateway pricing](https://aws.amazon.com/vpc/pricing/).

## Cost comparison

Checked 14 October 2026 against official AWS pricing/documentation. Amounts are
USD list-price estimates, before tax, with low demonstration traffic.

| Egress option | Approximate fixed cost for two hours | Availability |
| --- | --- | --- |
| One zonal NAT + one public IPv4 | $0.10 | Shared AZ dependency; selected for this demo |
| Two zonal NATs + two public IPv4s | $0.20 | Egress in each AZ |
| Regional NAT active in two AZs + two public IPv4s | About $0.20 at the same per-AZ rate | Regional NAT is billed per active AZ, not as one flat gateway |
| Eight interface services in two AZs | About $0.32 at $0.01 per endpoint ENI-hour | Private service paths; general package/bootstrap access still needs a solution |

The interface comparison is illustrative: ECR API/DKR, SSM/SSM messages,
Secrets Manager, logs, SQS and SES API. The exact endpoint set and regional support
must be checked before choosing an endpoint-only design. Hourly comparisons
exclude traffic, cross-AZ transfer and any additional bootstrap resources.
Sources: [us-east-1 NAT/public IPv4 example](https://aws.amazon.com/blogs/networking-and-content-delivery/identify-and-optimize-public-ipv4-address-usage-on-aws/),
[current VPC/regional NAT pricing](https://aws.amazon.com/vpc/pricing/),
[PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/).

For RDS `db.t3.micro`, AWS's public `us-east-1` price list published on
6 October 2026 lists Single-AZ PostgreSQL at $0.018/hour and Multi-AZ at
$0.036/hour. Two hours of instance time is approximately $0.036 or $0.072,
respectively, with storage/other charges additional. Single-AZ is selected for
the temporary demonstration; a two-AZ backend does not make this database highly
available. Source: [AWS RDS regional price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonRDS/current/us-east-1/index.json)
and [RDS pricing](https://aws.amazon.com/rds/postgresql/pricing/).

## Full-demo estimate

| Main fixed charge | Rate used | Two hours |
| --- | --- | --- |
| Two `t3.small` instances | 2 × $0.0208/hour | $0.0832 |
| Single-AZ `db.t3.micro` | $0.018/hour | $0.0360 |
| One NAT gateway | $0.045/hour | $0.0900 |
| One NAT public IPv4 | $0.005/hour | $0.0100 |
| One ALB | $0.0225/hour, excluding LCU usage | $0.0450 |
| Two baseline ALB public IPv4s | 2 × $0.005/hour | $0.0200 |
| **Subtotal for these fixed components** | | **$0.2842** |

EC2 rates use [AWS's us-east-1 T3 table](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/right-size-selection.html).
ALB rates use [ELB pricing](https://aws.amazon.com/elasticloadbalancing/pricing/);
public address/NAT rates use the sources above. ALB can allocate additional
addresses with scaling. A later resource change or longer session changes this
estimate; it is not a full AWS Pricing Calculator quote.

Additional charges include EC2/RDS/ECR/S3 storage, ALB LCUs, NAT/CloudFront/network
traffic, burstable CPU credits, requests, Lambda compute, Secrets Manager, logs,
alarms and DNS. The RDS
price list shows gp3 PostgreSQL storage at $0.115/GB-month, prorated. New Route 53
hosted zones normally cost $0.50/month without monthly proration; do not assume a
short-demo exception applies. Reusing an existing zone avoids creating another.
Standard non-exportable public ACM certificates used with AWS integrations have
no additional certificate charge. Sources: [Route 53 pricing](https://aws.amazon.com/route53/pricing/),
[ACM pricing](https://aws.amazon.com/certificate-manager/pricing/),
[Secrets Manager pricing](https://aws.amazon.com/secrets-manager/pricing/).

Set aside **$3 for the initial short demo**, leaving $7 of the requested $10
as margin for setup/deletion delays, traffic and tax. This is a planning allowance,
not a guaranteed final bill or automatic limit. Recalculate against the complete
Terraform plan before approving provisioning. Do not leave this architecture
running for a month: NAT and ALB alone exceed the total budget.

## Screenshots and teardown

Capture the application booking/cancellation/admin flow, received test email,
the cloud architecture, private instance/subnet placement, healthy ALB targets,
RDS network settings, worker logs and queue/DLQ configuration. Mask account IDs,
recipient addresses and any credentials/tokens before sharing screenshots.

After reviewing the complete stack, the authorized demo should:

1. Deploy immutable images and static assets; run migrations once.
2. Run the end-to-end smoke and collect screenshots/results.
3. Review the destroy plan and remove the dedicated demo workloads, then foundation.
4. Check for leftover instances, EBS volumes, NAT/EIPs, ALB, RDS databases/snapshots,
   ECR images, S3 objects/buckets, queues, logs, secrets and demo DNS records.
5. Retain the owned domain and any pre-existing hosted zone/shared records.
6. Keep state until cleanup is verified; check billing again after usage reporting catches up.

Stopping instances or RDS alone does not remove storage charges. The remaining
workload code/runbook must make demo snapshot and data-removal behavior explicit.
No restore test or cloud recovery guarantee has been established. CloudFront
disabling/deletion and DNS cleanup can take time, so teardown is part of the
session, not an instantaneous final action.

AWS Budgets notifications can arrive after usage has already exceeded a threshold;
they are an aid to monitoring, not a $10 spending lock. See
[AWS Budgets reporting delay](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html).
No provision, deployment or destruction has been performed by this preparation.
