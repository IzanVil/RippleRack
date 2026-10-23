"""The files that make GitHub work for the project: Dependabot and the workflow that publishes.

Neither can be tried before it is on the default branch, so these tests read what each one says and
check it against the project: that it watches what the project uses, and that the group of
development tools holds those tools and nothing that users install.
"""

from __future__ import annotations

import re
import tomllib
from fnmatch import fnmatchcase
from typing import Any

import yaml

from tests.markdown import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
DEPENDABOT = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def names(requirements: list[str]) -> set[str]:
    found = (NAME.match(requirement) for requirement in requirements)
    return {match.group(0).lower() for match in found if match}


def updates() -> dict[str, dict[str, Any]]:
    return {update["package-ecosystem"]: update for update in DEPENDABOT["updates"]}


def test_dependabot_watches_what_the_project_uses() -> None:
    assert DEPENDABOT["version"] == 2
    assert set(updates()) == {"uv", "github-actions"}
    assert (ROOT / "uv.lock").is_file()
    assert any((ROOT / ".github" / "workflows").glob("*.yml"))


def test_dependabot_looks_at_the_root_where_those_files_are() -> None:
    assert all(update["directory"] == "/" for update in updates().values())
    assert (ROOT / "pyproject.toml").is_file()


def test_dependabot_runs_weekly_and_writes_conventional_commits() -> None:
    for update in updates().values():
        assert update["schedule"]["interval"] == "weekly"
        assert update["commit-message"]["prefix"] == "chore"


def test_the_group_of_development_tools_holds_them_and_nothing_users_install() -> None:
    [group] = updates()["uv"]["groups"].values()
    patterns = group["patterns"]

    def grouped(name: str) -> bool:
        return any(fnmatchcase(name, pattern) for pattern in patterns)

    development = names(PYPROJECT["dependency-groups"]["dev"])
    installed = names(PYPROJECT["project"]["dependencies"])
    assert development
    assert installed
    assert all(grouped(name) for name in development), sorted(
        name for name in development if not grouped(name)
    )
    assert not any(grouped(name) for name in installed), sorted(filter(grouped, installed))
