# Contribution workflow

## Changes and verification

Commit format: `feat(scope): ...`, `fix(scope): ...`, `test(scope): ...` or
`docs: ...`. Each commit contains one coherent change with its required schema,
configuration, tests, dependency locks and documentation.

| Changed component | Checks |
| --- | --- |
| Backend | Real PostgreSQL suite and Python lint/format checks |
| Frontend | Type, build and contract checks; affected browser flows |
| Terraform | Formatting, validation and infrastructure tests |

Commands: [Development](development.md) and [Terraform](../infra/README.md#offline-checks).
Database transaction tests use real PostgreSQL. AWS adapter and infrastructure
tests use mocks for offline checks.

Inspect changed and staged files for secrets, generated artifacts and whitespace errors:

```bash
git status --short
git diff
git diff --cached --stat
git diff --cached --check
git log --oneline --decorate
```

## Tracked and excluded files

Both Python lockfiles, `frontend/package-lock.json`, the exported OpenAPI schema
and generated TypeScript declarations belong in Git. `.env`, dotenv variants,
AWS credential folders, private keys, virtual environments, dependency installs,
builds, browser results and local data artifacts are excluded. `.env.example`
contains only development example values and is tracked.

The Terraform provider lockfile also belongs in Git. Terraform state, saved plans,
local variable files and provider installations are excluded.

## Branch and automation

Development branch: `dev`. GitHub Actions and branch protection remain pending.
