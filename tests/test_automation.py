"""The files that make GitHub work for the project: Dependabot and the workflow that publishes.

Neither can be tried before it is on the default branch (and publishing, not before PyPI trusts the
workflow), so these tests read what each one says and check it against the project: that Dependabot
watches what the project uses and groups the development tools and nothing that users install,
and that the workflow runs only by hand, only on the tag of the declared version and gives PyPI
its identity in the one job that uploads.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.markdown import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
DEPENDABOT = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
PUBLISH_FILE = ROOT / ".github" / "workflows" / "publish.yml"
PUBLISH = yaml.safe_load(PUBLISH_FILE.read_text(encoding="utf-8"))
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


# ------------------------------------------------------------------------------ the publisher


def test_the_workflow_that_publishes_runs_only_when_someone_starts_it() -> None:
    triggers = PUBLISH["on"] if "on" in PUBLISH else PUBLISH[True]  # YAML 1.1: on is True
    assert set(triggers) == {"workflow_dispatch"}


def test_only_the_job_that_uploads_can_ask_pypi_for_an_identity() -> None:
    jobs = PUBLISH["jobs"]
    assert PUBLISH["permissions"] == {"contents": "read"}
    assert "permissions" not in jobs["build"]
    assert jobs["publish"]["permissions"] == {"id-token": "write"}
    assert set(jobs) == {"build", "publish"}


def test_the_upload_waits_for_the_build_and_names_the_project_it_publishes() -> None:
    publish = PUBLISH["jobs"]["publish"]
    assert publish["needs"] == "build"
    assert publish["environment"]["name"] == "pypi"
    name = PYPROJECT["project"]["name"]
    assert publish["environment"]["url"] == f"https://pypi.org/p/{name}"


def test_the_upload_uses_trusted_publishing_and_no_secret() -> None:
    text = PUBLISH_FILE.read_text(encoding="utf-8")
    assert "uv publish --trusted-publishing always" in text
    assert "secrets." not in text


def test_the_build_checks_the_files_the_way_pypi_will_show_them() -> None:
    runs = [step["run"] for step in PUBLISH["jobs"]["build"]["steps"] if "run" in step]
    assert "uv build" in runs
    assert "uvx twine check --strict dist/*" in runs


def tag_check() -> str:
    [script] = [
        step["run"]
        for step in PUBLISH["jobs"]["build"]["steps"]
        if "run" in step and "GITHUB_REF_TYPE" in step["run"]
    ]
    return str(script)


@pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("python3") is None,
    reason="the step is a bash script that calls python3",
)
@pytest.mark.parametrize(
    ("ref_type", "ref_name", "passes"),
    [
        ("tag", "v1.2.3", True),
        ("tag", "v1.2.4", False),
        ("tag", "1.2.3", False),
        ("branch", "v1.2.3", False),
        ("branch", "main", False),
    ],
)
def test_the_build_stops_unless_it_runs_on_the_tag_of_the_declared_version(
    tmp_path: Path, ref_type: str, ref_name: str, passes: bool
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    result = subprocess.run(
        ["bash", "-e", "-c", tag_check()],
        cwd=tmp_path,
        env={
            "PATH": str(Path(shutil.which("python3") or "").parent) + ":/usr/bin:/bin",
            "GITHUB_REF_TYPE": ref_type,
            "GITHUB_REF_NAME": ref_name,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if not passes:
        assert "::error::Run this workflow on the tag v1.2.3" in result.stdout
