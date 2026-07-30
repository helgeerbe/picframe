# Developer Workflow

This document describes the Picframe development workflow: branching,
pull requests, CI gates, releases, and changelog automation.

## Branch Model

| Branch | Purpose | Protection |
|--------|---------|-----------|
| `dev`  | Staging / integration. All feature and fix PRs target this branch. | PR + CI required |
| `main` | Release-only. Updated only by merging `dev → main`. | PR + CI required, no direct push |
| `v2-dev` | Transition branch during Picframe 2.0 modernization. PRs may target this branch until `dev` is fully active. | PR + CI required |
| Feature/fix branches | Short-lived, named `feat/<ticket>-<slug>`, `fix/<ticket>-<slug>`, etc. | Merged to `dev` or `v2-dev` via PR |

### Transition

During the next-gen transition, `v2-dev` is the active development branch.
PRs may target either `dev` or `v2-dev`. Once the transition is complete,
`v2-dev` merges to `dev` via PR and `dev` becomes the sole staging branch.

## Pull Requests

### Title — Conventional Commits

Every PR title must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<optional scope>): <description>
```

**Allowed types:**

| Type | Use for |
|------|---------|
| `feat` | New features |
| `fix` | Bug fixes |
| `docs` | Documentation |
| `refactor` | Code restructuring without behavior change |
| `perf` | Performance improvements |
| `test` | Test additions or changes |
| `build` | Build system, dependencies |
| `ci` | CI/CD changes |
| `chore` | Miscellaneous maintenance |
| `revert` | Reverting previous changes |

For breaking changes, append `!` after the type/scope:

```
feat(api)!: drop legacy config endpoint
```

The CI `pr-title` job validates this automatically using
[`amannn/action-semantic-pull-request`](https://github.com/amannn/action-semantic-pull-request).

### Ticket Linking

The PR body must reference the tracking ticket using one of:

- `Closes #123` — closes the issue on merge
- `Fixes #123` — closes the issue on merge (synonym)
- `Refs #123` — references the issue without closing

The PR template includes a `Ticket` section for this.

### Definition of Done

Every PR must satisfy the Definition of Done checklist in the PR template:

- Tests passing (`pytest`)
- Type checks passing (`mypy`)
- Lint/format passing (`ruff`)
- Frontend rebuilt and committed (if frontend changed)
- Documentation updated
- No regressions
- Memory Bank updated (if architecture changed)

## CI Pipeline

The CI workflow (`.github/workflows/ci.yml`) runs on every PR targeting `dev`
or `v2-dev`. It consists of four jobs:

### 1. `pr-title` — Conventional Commit Validation

Validates the PR title matches Conventional Commit format.

### 2. `lint-type-test` — Python Quality Gates

```bash
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src/picframe
pytest test/
```

### 3. `frontend-drift` — Frontend Bundle Consistency

```bash
cd frontend && npm ci && npm run build
git diff --exit-code src/picframe/html
```

Fails if the committed `src/picframe/html` doesn't match a fresh build.
This prevents merging stale frontend bundles.

### 4. `package-build` — Python Package Build

```bash
pip install build twine
python -m build
twine check --strict dist/*
```

Verifies the package builds and has valid metadata.

## Releases

### Process

Releases are fully automated via `.github/workflows/release.yml`:

1. A PR merges `dev → main`.
2. The release workflow triggers on `push` to `main`.
3. It determines a calendar-version tag: `YYYY.MM.DD`.
4. If that tag already exists, it appends `.postN` (e.g., `2026.07.30.post1`).
5. It builds the package and publishes to PyPI (trusted publishing).
6. It generates release notes from PR titles using
   [`mikepenz/release-changelog-builder-action`](https://github.com/mikepenz/release-changelog-builder-action).
7. It creates a GitHub Release with the tag, notes, and artifacts.

### Calendar Versioning

Tags use the format `YYYY.MM.DD` (e.g., `2026.07.30`). Multiple releases on
the same day use `.postN` suffixes (`2026.07.30.post1`).

### Changelog Categories

Release notes are generated from PR titles, categorized by Conventional
Commit type:

| PR Title Prefix | Release Category |
|----------------|------------------|
| `<type>!:` | ⚡ Breaking Changes |
| `feat:` | 🚀 Features |
| `fix:` | 🐛 Fixes |
| `docs:` | 📚 Documentation |
| `refactor:` | ♻️ Refactoring |
| `perf:` | ⚡ Performance |
| `test:`, `build:`, `ci:`, `chore:`, `revert:` | 🛠 Under the hood |

Configuration: `.github/workflows/config/release-notes-config.json`.

## Local Verification

Before opening a PR, run the same checks locally:

```bash
# Python quality gates
pip install -e ".[dev]"
ruff check .
ruff format --check .
mypy src/picframe
pytest test/

# Frontend build
cd frontend
npm ci
npm run build
cd ..

# Package build dry-run
python -m build
twine check --strict dist/*
```

## Required Branch Protection Rules

The following GitHub branch protection rules must be configured for `dev`
and `main`:

- **Require a pull request before merging**
- **Require status checks to pass:**
  - `PR Title (Conventional Commit)`
  - `Ruff · Mypy · Pytest`
  - `Frontend bundle drift`
  - `Python package build`
- **Require branches to be up to date before merging**
- **Restrict pushes that create matching branches** (for `main`)

These are configured in **Settings → Branches → Branch protection rules**
on GitHub, not in the repository itself.
<!-- CI test -->