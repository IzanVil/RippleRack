# Contributing to RippleRack

Thanks for your interest in RippleRack! This guide covers how to set up the
project, the conventions we follow and how to propose changes. By taking part you agree to
follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

RippleRack requires Python 3.11+ and uses [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/IzanVil/RippleRack.git
cd RippleRack
uv sync
```

## Running the checks

All four must pass before you open a pull request (CI runs them on Python
3.11, 3.12, 3.13 and 3.14):

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

`uv run ruff format .` fixes formatting problems for you. `ruff check` also refuses a function
with too many branches, returns or statements (the limits are in `pyproject.toml`): split it
into functions that each do one thing.

The JSON output is a documented contract (see [docs/output-formats.md](docs/output-formats.md))
pinned by the files in `tests/golden/`. If you change it on purpose, regenerate them
with `RIPPLERACK_UPDATE_GOLDEN=1 uv run pytest`, review the diff carefully and update
the documentation.

The screenshots in the README are drawn from the real output of the commands by
`docs/images/generate.py`, and a test fails when one is out of date. If you change what a
command prints, run `uv run python docs/images/generate.py` and commit the images.

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
4. Open a pull request against `main`. The pull request template lists what to check;
   describe what changed and why, and link the related issue if there is one.
5. Update [CHANGELOG.md](CHANGELOG.md) under `[Unreleased]` for user-visible changes.

## Reporting bugs and requesting features

Use [GitHub issues](https://github.com/IzanVil/RippleRack/issues); the templates ask for
the details described below. Security problems are the exception: do not open a public
issue, follow [SECURITY.md](SECURITY.md).

**Bugs**: include the RippleRack version (`ripplerack --version`), your Python
version and OS, the smallest YAML file that reproduces the problem, the exact
command you ran, and the expected vs. actual output.

**Features**: describe the problem you want to solve before the solution, and
include a small example of the YAML or command you would like to write. Open an
issue to discuss larger changes before starting work on them.

## Releasing

This section is for maintainers. A release is a version bump, a changelog section, a tag and an
upload. Making the tag or a GitHub release publishes nothing: the upload is always started by
hand, and no token is stored, because each index trusts the workflow (see the comment at the top
of [`publish.yml`](.github/workflows/publish.yml)).

1. Bump `version` in `pyproject.toml` and run `uv lock`. The diff of `uv.lock` must show only
   that version.
2. Name the new version where the documentation shows it: the three `"version"` examples in
   [docs/output-formats.md](docs/output-formats.md) and the `@vX.Y.Z` of the action in
   [docs/ci.md](docs/ci.md), [action/README.md](action/README.md) and
   [examples/ci/ripplerack.yml](examples/ci/ripplerack.yml).
3. Cut the changelog: move what is under `[Unreleased]` into a new `[X.Y.Z] - date` section and
   leave `[Unreleased]` empty.
4. Run the four checks on every Python version CI runs.
5. Tag the commit that cuts the changelog (`git tag -a vX.Y.Z -m "RippleRack X.Y.Z"`), push
   `main` and the tag, and create a GitHub release with the notes of that changelog section. While
   the project is in alpha, mark it as a pre-release.
6. Open Actions > Publish to PyPI > Run workflow. In "Use workflow from" open the Tag tab and
   choose `vX.Y.Z`: on a branch the run stops, by design. Choose the `testpypi` environment first,
   look at the page on TestPyPI and install the package in a clean virtual environment with
   `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ ripplerack==X.Y.Z`.
   Then run it again with the `pypi` environment, which is the default.
7. Check the page on PyPI and `pip install ripplerack==X.Y.Z` in a clean environment.

An index does not accept a file again once it has one with that name, so a mistake that reaches
it means a new version.
