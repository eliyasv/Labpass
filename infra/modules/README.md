# Terraform modules

`infra/foundation/modules.tf` composes five local child modules. The foundation
owns the AWS provider, account guard, default tags, backend, shared ECR
repositories and SQS/DLQ. The delivery bootstrap retains separate state ownership.

## Interfaces

| Module | Resources | Integration inputs | Outputs |
| --- | --- | --- | --- |
| `network` | VPC, subnets, routes, NAT, S3 endpoint and empty default security group | Region and name prefix | `network`: VPC, availability zones and subnet IDs |
| `database` | RDS, secret containers, client groups, runtime roles and EC2 profiles | VPC/database subnets, queue ARN and database settings | `database`, `client_security_group_ids`, `runtime_roles`, `instance_profiles` |
| `application` | HTTPS ALB, API/relay ASGs, four launch templates, logging and host policies | Hosting configuration, network, database/access metadata, API repository, queue ARN, listener certificate and origin tokens | `application_hosting`, `alb_origin`, `listener_certificate_arn` |
| `frontend` | Private S3/OAC, CloudFront, Route 53 records and ACM certificates | Frontend configuration, ALB DNS/zone metadata and origin token | `frontend_delivery`, `certificates` |
| `confirmations` | Lambda/version/alias, SQS mapping, SES/DKIM, logging and worker policies | Worker configuration, application subnets, consumer role/group, database endpoint and consumer-secret ARN, Lambda repository and queue settings | `confirmation_worker` |

All inputs have explicit Terraform types. Set the root `application`, `frontend`
or `confirmation_worker` input to `null` to disable that workload; its public
root output is then null. Root input names and output shapes are unchanged.

Child modules inherit the root provider. They contain no provider configuration
or backend and require Terraform `>= 1.15.0, < 2.0.0` and AWS provider
`>= 6.68.0, < 7.0.0`.
The foundation pins the exact provider version and checksums. Local module source
paths are versioned with the repository.

## Dependency boundaries

Network outputs include route, association and endpoint dependencies. Database
access outputs include security-group rule and IAM policy dependencies before
workloads use them.

The application receives host role IDs/names and security groups for API, relay,
bootstrap and migration. Its bootstrap host requires the master-secret ARN and
all four role-secret ARNs. The confirmation worker receives only its consumer
secret ARN and database connection metadata.

The frontend's `certificates` output depends only on certificate issuance. The
application uses its origin certificate, then exports ALB metadata after listener
rules exist. Frontend origin DNS and CloudFront consume that metadata. These
resource-level dependencies allow TLS and ALB integration without a module-level
dependency cycle. Standalone application hosting accepts an external certificate.
The root selects that certificate or the frontend-issued origin certificate and
passes it through the application's single `listener_certificate_arn` input.

## Offline verification

Run the [two-root checks](../README.md#offline-checks). Foundation tests cover
individual modules and the combined application, frontend and confirmation
workloads using a mocked AWS provider. No AWS credentials are required.
