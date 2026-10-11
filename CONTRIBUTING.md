# Contributing to RippleRack

Thanks for your interest in RippleRack! This guide covers how to set up the
project, the conventions we follow and how to propose changes.

## Development setup

RippleRack requires Python 3.11+ and uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/IzanVil/RippleRack.git
cd RippleRack
uv sync
```

## Running the checks

All three must pass before you open a pull request (CI runs them on Python
3.11, 3.12 and 3.13):

```bash
uv run pytest
uv run ruff check .
uv run mypy src tests
```

Format your code with `uv run ruff format .` (CI verifies it with
`uv run ruff format --check .`).

The JSON output is a documented contract (see [docs/output-formats.md](docs/output-formats.md))
pinned by the files in `tests/golden/`. If you change it on purpose, regenerate them
with `RIPPLERACK_UPDATE_GOLDEN=1 uv run pytest`, review the diff carefully and update
the documentation.

## Commit convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short imperative summary>
```

| type       | use for                                        |
|------------|------------------------------------------------|
| `feat`     | a new user-facing feature                      |
| `fix`      | a bug fix                                      |
| `docs`     | documentation only                             |
| `test`     | adding or fixing tests                         |
| `refactor` | code change that neither fixes a bug nor adds a feature |
| `ci`       | CI configuration and workflows                 |
| `chore`    | tooling, dependencies and other maintenance    |

Keep the summary under ~72 characters and add a body when the *why* is not
obvious.

**Commits must not carry attribution trailers or signatures.** Do not add
`Co-authored-by:` lines, `Generated with Claude Code` or similar notes, or any
other AI-tool signature. Commits are attributed solely to the human author.

## Code style

- **Strict typing**: the project is checked with `mypy --strict`. Annotate every
  function, including tests.
- **Docstrings** on all public modules, classes and functions. Say what and why,
  not how.
- **English names** for identifiers, comments, messages and docs.
- Follow the existing structure: models in `models.py`, graph logic in
  `graph.py`, and so on. See the module table in the [README](README.md#how-it-works).
- Add or update tests for any behaviour change. New schema rules belong in
  `tests/test_semver.py` and new impact rules in `tests/test_impact.py`.
- Avoid new dependencies unless they are clearly justified.

## Proposing changes

1. Fork the repository.
2. Create a descriptively named branch from `main`, e.g. `feat/diff-two-datacenters`
   or `fix/cycle-detection-message`.
3. Make your change in small, conventional commits and make sure the checks pass.
4. Open a pull request against `main`. Describe what changed and why, and link
   the related issue if there is one.
5. Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.

## Reporting bugs and requesting features

Use [GitHub issues](https://github.com/IzanVil/RippleRack/issues).

**Bugs**: include the RippleRack version (`ripplerack --version`), your Python
version and OS, the smallest YAML file that reproduces the problem, the exact
command you ran, and the expected vs. actual output.

**Features**: describe the problem you want to solve before the solution, and
include a small example of the YAML or command you would like to write. Open an
issue to discuss larger changes before starting work on them.
