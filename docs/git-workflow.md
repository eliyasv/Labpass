# Contribution workflow

## Changes and verification

Use short, specific commits describing one coherent change. Include required
schema/configuration, tests, dependency locks and documentation. Prefer
`feat(scope): ...`, `fix(scope): ...`, `test(scope): ...` and `docs: ...` titles.
Use a separate fix commit when review or verification finds an issue. Keep the
report/checklist current and state any remaining verification limits.

Before committing, inspect the selected files and staged diff, verify that no
secrets/artifacts entered the index, and run checks appropriate to the change.
Backend changes need the real PostgreSQL suite; frontend changes need
type/build/contract checks and affected browser flows. Terraform changes need
formatting, validation and infrastructure tests. Database transaction tests use
real PostgreSQL; AWS adapter and infrastructure tests use mocks for offline checks.

```bash
git status --short
git diff
git diff --cached --stat
git diff --cached --check
git log --oneline --decorate
```

Both Python lockfiles, `frontend/package-lock.json`, the exported OpenAPI schema
and generated TypeScript declarations belong in Git. `.env`, dotenv variants,
AWS credential folders, private keys, virtual environments, dependency installs,
builds, browser results and local data artifacts are excluded. `.env.example`
contains only development example values and is tracked. Pattern checks help
detect accidental secrets but do not prove their absence.

The Terraform provider lockfile also belongs in Git. Terraform state, saved plans,
local variable files and provider installations are excluded. Current development
targets `dev`; GitHub Actions and branch protection remain pending.
