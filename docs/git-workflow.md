# Git workflow

The first local commits were prepared on 14 October 2026 (Asia/Calcutta), after
milestones 1–3 and the local part of milestone 4 were implemented and verified.
There were no earlier commits or saved historical source snapshots. This history
captures the current working baseline; it does not recreate earlier milestone
states or backdate commits. Historical milestone reports retain the evidence and
Git limitations recorded at the time of their original verification.

## Baseline commit groups

| Commit | Scope |
| --- | --- |
| `chore(repo): add ignores and local environment examples` | Ignore secrets/local artifacts and track the development environment example |
| `feat(backend): add booking API, authentication and delivery workers` | FastAPI, inventory guarantees, auth, migrations, worker logic, tests, Python locks and verification scripts |
| `feat(web): add React frontend and local Compose stack` | React UI, generated API contract/types, npm lock, browser tests, web image/proxy, Compose and local queue configuration |
| `docs: record milestones and local development workflow` | Architecture, operation, milestone reports, checklist and this workflow |

The backend commit includes the final integrated state from milestones 1, 2 and
the local worker portion of 4, because those changes share models, migrations,
dependencies and readiness checks. Frontend and Compose follow that backend.
The resulting history records logical changes without introducing artificial
intermediate versions that were never saved or verified.

## Future milestone commits

Continue with small commits describing one coherent change. Include its required
schema/configuration, tests, dependency locks and documentation. Prefer
`feat(scope): ...`, `fix(scope): ...`, `test(scope): ...` and `docs: ...` titles.
Use a separate fix commit when review or verification finds an issue. Keep the
report/checklist current and state any remaining verification limits. Avoid
rewriting published history unless deliberately agreed.

Before committing, inspect the selected files and staged diff, verify that no
secrets/artifacts entered the index, and run checks appropriate to the change.
Use explicit paths for staging. Backend changes need the real PostgreSQL suite;
frontend changes need type/build/contract checks and affected browser flows.
Do not substitute mocked transactions for PostgreSQL verification.

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

## Current branch and GitHub publication

No repository creation, remote addition or push was performed as part of
establishing the baseline. The workspace now has an `origin` remote and uses
`dev`, tracking `origin/dev`; subsequent milestone commits stay on `dev`.
Use `git remote -v` to inspect remotes and `git branch --show-current` to inspect
the current branch. Push only when publication is requested.

Planned delivery flow: feature changes merge into `dev` after CI; promote reviewed
changes to `main` for an approved AWS release. GitHub Actions will use OIDC, run
migrations once and deploy immutable image digests. Workflows and branch
protection remain future implementation/configuration steps.
