# Delivery bootstrap

Terraform root for GitHub OIDC release access and remote foundation state.
Region: `us-east-1`. Requires Terraform 1.15.x and AWS provider 6.68.0.

| Resource | Configuration |
| --- | --- |
| OIDC provider | GitHub Actions; existing same-account provider can be reused |
| Publish role | Exact repository/environment trust; image pushes to the two foundation ECR repositories |
| Plan role | Foundation metadata reads, state reads/locking and private versioned plan writes; secret values denied |
| Apply role | State writes, approved runtime updates, frontend object writes and restricted migration execution; secret values denied |
| State bucket | Private, versioned, AES256 encrypted, TLS required, ACLs disabled, destruction protected |
| Plan retention | Current/noncurrent objects under `plans/` expire after seven days; state versions are retained |
| SSM document | Validated image digest, host lock, fixed migration helper commands |

## Inputs

| Variable | Purpose |
| --- | --- |
| `aws_account_id` | Required actual target account; provider guard |
| `github_repository` | Required exact owner/repository |
| `github_owner_id`, `github_repository_id` | Required immutable numeric IDs |
| `oidc_subject_format` | `immutable` by default; use the repository's actual `immutable` or `legacy` configuration |
| `existing_oidc_provider_arn` | Optional same-account GitHub provider ARN |
| `workload_name_prefix` | Foundation name prefix; default `labpass-demo` |
| `runtime_launch_template_ids` | Actual `api`, `relay`, `bootstrap`, `migration` IDs; empty grants no template writes |
| `migration_instance_id` | Dedicated private running operator instance; null grants no SSM command execution |

The `delivery` output contains role ARNs, exact trusted subjects, backend bucket/key
and migration document name. Initial infrastructure provisioning uses operator
credentials; these roles support updates to existing application workloads.

## Offline verification

```bash
terraform -chdir=infra/delivery init -backend=false -input=false -lockfile=readonly
terraform -chdir=infra/delivery fmt -check -recursive
terraform -chdir=infra/delivery validate
terraform -chdir=infra/delivery test
```

Tests use a mocked provider and require no AWS credentials. The bootstrap root
uses local state; preserve it outside Git in restricted storage. Its state owns
the remote bucket and must remain separate from foundation state.

Provisioning order, GitHub settings, secret handling, plan review and release
failure handling: [CI/CD and release security](../../docs/delivery.md).
