## Ticket

Closes #[Issue Number]

> **Linking:** Use `Closes #123`, `Fixes #123`, or `Refs #123` to link the
> tracking ticket. Every PR must reference a ticket.

## Description of Changes

Briefly describe the changes introduced by this PR.

*Note: If this PR is part of the Picframe 2.0 modernization, ensure the linked
issue is labeled with `next gen`.*

## PR Title

PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<optional scope>): <description>
```

Allowed types: `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`,
`ci`, `chore`, `revert`.

Append `!` after the type/scope for breaking changes:
`feat(api)!: drop legacy config endpoint`

The PR title is the canonical source for the generated changelog.

## Definition of Done (Mandatory)

All items must be checked before this PR can be merged.

- [ ] Tests are written/updated and passing (`pytest`).
- [ ] Code is fully type-annotated and passes `mypy`.
- [ ] Linting and formatting (`ruff`) pass.
- [ ] Frontend linting and formatting pass: `cd frontend && yarn lint && yarn format:check`.
- [ ] Frontend changes (if any) are rebuilt: `yarn build` committed in
      `src/picframe/html`.
- [ ] Inline documentation and module descriptions are updated.
- [ ] No performance or security regressions introduced.
- [ ] Memory Bank updated (if architectural or context changes occurred).