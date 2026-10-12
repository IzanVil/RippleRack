## What and why

<!-- What does this change, and why? Link the issue: "Closes #123". -->

## How it was checked

- [ ] `uv run pytest`
- [ ] `uv run ruff check .` and `uv run ruff format --check .`
- [ ] `uv run mypy src tests`

## Checklist

- [ ] Tests added or updated for any change in behaviour
- [ ] Docs updated (README, `docs/`) and `CHANGELOG.md` under `[Unreleased]` for user-visible changes
- [ ] If the JSON output changed: golden files regenerated on purpose (`RIPPLERACK_UPDATE_GOLDEN=1`), `docs/output-formats.md` updated and, for breaking changes, `schemaVersion` bumped and the changelog entry marked **BREAKING**
- [ ] Commits follow Conventional Commits and carry no attribution trailers (see CONTRIBUTING.md)
- [ ] No new dependencies, or the reason is explained above
