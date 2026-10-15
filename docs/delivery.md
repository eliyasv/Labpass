# CI/CD and release security

## Continuous integration

`.github/workflows/ci.yml` runs for pull requests and pushes to `dev`, manual
invocations and the reusable release check. All CI jobs use read-only repository
permissions and receive no AWS credentials or deployment secrets.

| Gate | Checks |
| --- | --- |
| Secrets | Gitleaks scans Git history and Git-visible files; ignored local credentials are excluded |
| Python | Ruff, Bandit, hash-verified dependency installation and pip-audit for runtime/development/security-tool locks |
| JavaScript | Lockfile installation with lifecycle scripts disabled, npm audit at high severity, contract/format/build checks |
| Infrastructure | Terraform formatting, schema validation, module/composition tests and Trivy configuration checks with all optional workloads enabled by fictional scan inputs |
| Images | API and Lambda builds for Linux amd64, Trivy vulnerability/secret scans and CycloneDX SBOMs |
| Integration | Full PostgreSQL suite inside the API runtime's test target, script regressions, Chromium against Compose and an isolated Lambda runtime smoke |
| Required status | `ci-gate` fails when any required job fails, is cancelled or is skipped |

External actions use full commit SHAs. Scanner downloads use checked-in SHA-256
pins. Python locks contain package hashes; release base images use digests.
Dependabot covers actions, Python, npm, Docker and Terraform.

The API uses Python 3.14 on Alpine 3.24 with hash-verified binary wheels. Its `test`
target extends the production runtime with development tools; `release` is the
default target and excludes them. PostgreSQL tests exercise the same musl-based
application libraries shipped to EC2.

Lambda retains the AWS Python 3.14 base and updates packages from the pinned
`AL2023_RELEASE` repository version before installation. Review this pin together
with base-image updates. Both release images run dependency checks during the
build, then remove pip and ensurepip. Lambda's emulator is available only in the
`local` test target; production uses the AWS-provided Runtime API. CI builds and
exports `release` explicitly and checks that installation tools and the emulator
are absent. See [AL2023 versioned updates](https://docs.aws.amazon.com/linux/al2023/ug/deterministic-upgrades-usage.html)
and [Lambda container runtimes](https://docs.aws.amazon.com/lambda/latest/dg/python-image.html).

Trivy blocks high/critical findings, including unfixed image vulnerabilities.
SBOMs are retained even when an image scan fails; failed images are not exported
as release artifacts. Configuration exceptions in `security/trivy-exceptions.yaml` identify exact files,
technical reasons and expiry dates. Security tests reject expired or unscoped
exceptions. No image vulnerability exceptions are configured. Gitleaks exceptions
match public managed-policy IDs, a local fixture name and one historical
documentation phrase.

Configure a repository ruleset for `dev` requiring `ci-gate`, pull-request review
and CODEOWNERS approval for workflow, security, infrastructure and authentication
changes. The checked-in files do not configure GitHub rulesets or environments.

## Release boundaries

`.github/workflows/release.yml` is manually dispatched from the current `dev`
commit. It updates an **already provisioned** foundation; initial infrastructure,
database bootstrap, DNS delegation, SES activation and operator-instance creation
are separate procedures. The complete foundation must already use S3 state, with
at least two API instances and one relay instance.

| Stage | Permission and behaviour |
| --- | --- |
| Preflight | Checks the current commit and existing environment reviewer/branch rules before any AWS job |
| Verify | Runs the complete CI workflow again for the release commit |
| Publish | Loads the scanned image artifacts from this run, pushes immutable ECR tags and records registry digests; no rebuild |
| Plan | Refreshes state and saves a runtime-only Terraform update plan in private versioned S3 |
| Apply | Verifies the exact plan/manifest versions and hashes, runs one migration command, applies the saved plan and waits for rollout |
| Frontend | Publishes content-addressed assets, other static files and `index.html` last; retains old assets |
| Smoke | Checks readiness through the public CloudFront HTTPS URL |

Releases are serialized. Each stage checks that the commit remains the `dev`
head. Start a new workflow run after a failure; individual job reruns are rejected.
Manual infrastructure/state changes must be coordinated with releases. S3 locking
protects each Terraform operation; it does not reserve infrastructure throughout
the approval interval. Terraform rejects a saved plan if its state has changed.

The plan allowlist rejects creation, replacement, deletion, IAM changes and
database/network/frontend configuration changes. It permits existing launch-template
runtime payloads, ASG template versions, Lambda image/version fields and the live
alias version. Other changes require a separate operator plan.

Allowed resource addresses are scoped to
`module.application.aws_launch_template.runtime` (the `api`, `relay`, `bootstrap`
and `migration` keys), `module.application.aws_autoscaling_group.api[0]`,
`module.application.aws_autoscaling_group.relay[0]`,
`module.confirmations.aws_lambda_function.confirmations[0]` and
`module.confirmations.aws_lambda_alias.confirmations[0]`. The guard checks exact
addresses and allowed fields. It rejects state-address moves even when their
resource action is `no-op`.

The migration SSM document accepts only a SHA-256 image digest and runs on the
configured private migration host, after checking its component tag and instance
profile. A host lock prevents concurrent executions. Failed migrations stop the
release before runtime rollout. Schemas must remain compatible with the old fleet
during rolling updates; there is no automatic database rollback.

Fleet verification checks numeric launch-template versions, instance health and
refresh completion. API health includes ALB checks; relay health is EC2 health.
Lambda's live alias must be active. An end-to-end booking/email check remains
required to verify relay processing, SES permissions and mailbox delivery.

## AWS bootstrap

`infra/delivery` defines three OIDC roles, a restricted migration document and
private versioned state storage. See [delivery inputs](../infra/delivery/README.md).
Use authenticated operator credentials to review and provision this root.

The bootstrap root retains local state. Preserve that state outside Git in
restricted storage; it owns the remote bucket and delivery roles. The foundation
uses a partial S3 backend with `use_lockfile=true`, without a DynamoDB table.

After the bucket exists, initialize the foundation with actual backend settings:

```bash
terraform -chdir=infra/foundation init \
  -backend-config="bucket=${STATE_BUCKET:?Set the delivery state bucket}" \
  -backend-config=key=foundation/terraform.tfstate \
  -backend-config=region=us-east-1 \
  -backend-config=encrypt=true \
  -backend-config=use_lockfile=true
```

For an existing local foundation state, back it up and use `init -migrate-state`
with these settings, then verify the remote state before removing local copies.
Do not use `-reconfigure` to migrate an existing state.

Publish the initial images and provision/bootstrap the workloads using the
[application hosting](application-hosting.md), [frontend delivery](frontend-delivery.md)
and [confirmation deployment](confirmation-worker.md) procedures. Then update
`infra/delivery` with all four actual launch-template IDs and the running migration
instance ID. Empty IDs grant neither template writes nor migration execution.

OIDC trust uses an exact audience, repository subject and environment. Determine
the repository's actual subject configuration with:

```bash
gh api "repos/${GITHUB_REPOSITORY:?Set owner/repository}/actions/oidc/customization/sub"
gh api "repos/$GITHUB_REPOSITORY" --jq '{repository_id: .id, owner_id: .owner.id}'
```

Set `oidc_subject_format` to the reported immutable or legacy format. Immutable
subjects include numeric owner/repository IDs; existing custom subject templates
must match the supported repository/environment shape before using these roles.
Reuse an existing account-wide GitHub OIDC provider through
`existing_oidc_provider_arn`. See [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).

## GitHub configuration

Create `labpass-publish`, `labpass-plan` and `labpass-apply` environments with:

- Required reviewers.
- Selected deployment branches: one rule for the exact branch `dev`; no tag rules.
- Administrative bypass disabled where supported by the repository's plan.

Reviewer protections depend on repository visibility and GitHub plan support.
Preflight fails if the required protection rules are missing. It uses the
workflow token with Actions read permission; no personal access token is required.
See [environment protection](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

Set repository variables shared by the release jobs:

| Variable | Value |
| --- | --- |
| `AWS_ACCOUNT_ID` | Actual 12-digit target account |
| `WORKLOAD_NAME_PREFIX` | Foundation `name_prefix` |
| `AWS_PUBLISH_ROLE_ARN` | Delivery `publish` role ARN |
| `AWS_PLAN_ROLE_ARN` | Delivery `plan` role ARN |
| `AWS_APPLY_ROLE_ARN` | Delivery `apply` role ARN |
| `STATE_BUCKET` | Delivery state bucket |
| `MIGRATION_INSTANCE_ID` | Dedicated private operator instance ID |
| `FOUNDATION_TFVARS_JSON` | Complete non-secret foundation configuration, including existing application/frontend/worker settings and desired capacities |

The release replaces only the two image digests in `FOUNDATION_TFVARS_JSON`.
Other inputs must match the deployed configuration, including explicit defaults
where they were changed. Store no passwords or origin tokens in this variable.

Set `ORIGIN_VERIFY_TOKEN` as an environment secret in **both** `labpass-plan` and
`labpass-apply`, matching the deployed token. If rotation overlap is active,
set the same optional `ORIGIN_VERIFY_PREVIOUS_TOKEN` in both environments.
The manifest binds configuration and tokens between plan and apply; differing
values stop the release. No long-lived AWS access keys are required.

## State, plan review and failure handling

The state bucket uses S3-managed AES256 encryption, TLS-only access, versioning,
disabled ACLs and blocked public access. Plan objects and their noncurrent
versions expire after seven days. State versions have no expiry policy.
Terraform prevents accidental bucket destruction.

Database password values remain outside Terraform. The origin token is present
in state and saved plans despite its sensitive input flag. Plans and JSON output
must stay in restricted storage; the workflow uploads neither to GitHub artifacts.
Only image/SBOM/frontend artifacts are retained there, for three days.

The plan job summary lists changed runtime resource addresses. Before approving
`labpass-apply`, an authorized operator can inspect the full private plan using
the `plan` job's run ID and S3 version ID:

```bash
umask 077
labpass_review_dir=$(mktemp -d /tmp/labpass-review.XXXXXX)
aws s3api get-object --bucket "${STATE_BUCKET:?}" \
  --key "plans/${RELEASE_RUN_ID:?}/plan" \
  --version-id "${PLAN_VERSION:?}" "$labpass_review_dir/release.tfplan"
terraform -chdir=infra/foundation show "$labpass_review_dir/release.tfplan"
```

Do not attach this plan to a PR or paste its full output into build logs. After
review, remove the local copy from restricted storage.

Planning cannot write foundation state or read secret values from Secrets Manager.
Applying can update existing runtime resources, publish frontend objects and run
the restricted migration document; it cannot provision infrastructure or manage
IAM. Provider metadata reads cover the foundation and require several service-wide
read actions. Validate effective permissions in the target account before release.

If migration, Terraform, refresh or smoke verification fails, inspect SSM,
Terraform state, ASGs, the Lambda alias and CloudWatch logs before another run.
A failure can leave a partially updated runtime. Image rollback alone does not
undo schema/data changes; no automatic rollback is attempted.
