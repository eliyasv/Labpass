# Application hosting

## Configuration

Hosting is disabled when `application = null`. Supply actual deployment values
to enable the ALB, launch templates and Auto Scaling Groups:

| `application` field | Requirement |
| --- | --- |
| `ami_id` | Amazon-owned AL2023 standard AMI, kernel 6.1, x86_64, EBS/HVM |
| `image_digest` | `sha256:` followed by 64 hexadecimal characters; image published to the API ECR repository |
| `public_origin` | HTTPS browser origin without a path or credentials |
| `origin_certificate_arn` | Existing matching regional ACM certificate for standalone hosting; omit when `frontend` provisions it |
| `api_desired_capacity` | Default `0`; running fleet permits `2`–`4` instances |
| `relay_desired_capacity` | Default `0`; running fleet permits `1`–`2` instances |

The AMI ID and image digest are explicit inputs. Launch templates use numeric
versions. Changing the template starts a rolling refresh; successful Terraform
execution alone does not establish that the refresh completed.

Hosting also requires the sensitive `origin_verify_token` input. Frontend
integration, certificate/DNS inputs and token rotation:
[Frontend delivery](frontend-delivery.md).

## Traffic and instance boundaries

The internet-facing ALB occupies both public subnets. Its security group permits
only HTTPS from the AWS-managed CloudFront origin-facing prefix list. The HTTPS
listener forwards `/api` and `/api/*` to port 8000 only with the matching origin
token and returns 404 for other requests. The API
security group accepts port 8000 only from the ALB group.

The prefix list identifies CloudFront traffic across distributions. The additional
origin token restricts forwarding to requests configured by this deployment.
Optional frontend integration defines CloudFront behaviours, origin DNS and
certificate provisioning.

| Component | Runtime and access |
| --- | --- |
| API | Private two-AZ ASG; ALB readiness checks at `/api/health/ready`; 600-second health grace period |
| Relay | Separate private ASG and IAM role; EC2 health checks; no published container port |
| Bootstrap | Launch template only; explicit operator job with master-secret access |
| Migration | Launch template only; explicit operator job with the migration secret |

Instances use `t3.micro` with Standard CPU credits, encrypted 20 GiB gp3 root
volumes, no public IP or SSH key, and IMDSv2 with hop limit 2 for container access.
API and relay profiles retain their separate database and SQS scopes. The private
NAT/S3 paths provide package, ECR, secret, SSM and logging access.

The API refresh requests 100% minimum and 150% maximum healthy capacity; relay
refresh requests 100%/200%. Temporary replacement instances require additional
compute and database connection capacity. Metric-driven scaling policies remain
pending. API two-AZ placement does not remove the shared NAT or Single-AZ RDS
failure points.

## Startup and logs

User data enables SSM, installs Docker and writes root-only configuration containing
image references, endpoint metadata and secret ARNs. Credential values are loaded
by the application SDK. ECR login uses the instance role and a temporary Docker
configuration under `/run`, removed after successful or failed pulls.

Systemd supervises API/relay containers and retries failures after ten seconds.
Containers run as UID/GID 10001 with a read-only root, a 64 MiB `/tmp`, dropped
capabilities, no privilege escalation, a 256-process limit and 512 MiB memory.
Systemd stops them with a 30-second Docker grace period.

The Docker `awslogs` driver writes to `/labpass/<name_prefix>/<component>` with
seven-day retention. Each role can pull only the API/relay repository and write
its own log group. `ecr:GetAuthorizationToken` uses `Resource="*"` because that
action does not support repository-level resource permissions. SSM uses
`AmazonSSMManagedInstanceCore`.

Relay configuration requires database and SQS settings; SES sender configuration
is required only by the Lambda consumer. Relay process/EC2 health does not measure
publication success. Outbox backlog and last-success alarms remain pending.

## Bootstrap and migration jobs

Keep both desired capacities at zero until database bootstrap succeeds. Endpoint,
subnet, template ID/version and log-group metadata are available through:

```bash
terraform -chdir=infra/foundation output -json application_hosting
terraform -chdir=infra/foundation output -json network
```

Launch an operator instance from the bootstrap or migration template in an
application subnet. On that instance through SSM, run the matching command:

```bash
sudo /usr/local/sbin/labpass-service bootstrap pull
sudo /usr/local/sbin/labpass-service bootstrap job
```

For subsequent releases, use the migration template:

```bash
sudo /usr/local/sbin/labpass-service migration pull
sudo /usr/local/sbin/labpass-service migration job
```

The jobs do not run automatically during instance startup. Bootstrap creates
credentials/roles, upgrades the schema and grants runtime access. The migration
job upgrades the schema and reapplies table grants. Serialize release jobs and
complete migrations before starting API/relay capacity or replacing their image.
Database details: [Database runtime](database-runtime.md).

## Inspection

On an API or relay instance through SSM:

```bash
sudo systemctl status labpass@api.service
sudo journalctl -u labpass@api.service -n 50 --no-pager
sudo docker ps
```

Use `labpass@relay.service` for the relay. Host startup output is in
`/var/log/cloud-init-output.log`; container output is in the component log group.
From an authenticated CLI, using the target-group ARN from the hosting output:

```bash
aws elbv2 describe-target-health --region us-east-1 \
  --target-group-arn "${LABPASS_API_TARGET_GROUP_ARN:?Set the hosting output target-group ARN}"
```

AWS boot/package retrieval, SSM registration, ECR/logging authorization, ALB TLS,
target registration, scaling and refresh behaviour remain unverified. Offline
verification is recorded in [Milestone 5C](milestone-5c.md).

References: [ALB origin restriction](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/restrict-access-to-load-balancer.html),
[AL2023 IMDSv2](https://docs.aws.amazon.com/linux/al2023/ug/imdsv2.html),
[Docker CloudWatch logging](https://docs.docker.com/engine/logging/drivers/awslogs/),
[Instance refresh](https://docs.aws.amazon.com/autoscaling/ec2/userguide/instance-refresh-overview.html).
