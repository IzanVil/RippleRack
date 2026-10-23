"""The Python versions the project names: those it declares, those CI runs, those the text says.

They are written in five places, and a version added to one and forgotten in another would make
the package page claim a version that nothing tests, or the CI test a version that nobody
declares. These tests keep the five lists equal.
"""

from __future__ import annotations

import re
import tomllib

import yaml

from tests.markdown import ROOT

PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONTRIBUTING = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

VERSION = re.compile(r"3\.\d+")
CLASSIFIER = re.compile(r"Programming Language :: Python :: (3\.\d+)")


def ordered(versions: list[str]) -> list[str]:
    return sorted(versions, key=lambda version: int(version.split(".")[1]))


def declared() -> list[str]:
    found = [m.group(1) for c in PYPROJECT["classifiers"] if (m := CLASSIFIER.fullmatch(c))]
    return ordered(found)


def test_the_package_declares_every_version_from_the_first_it_requires() -> None:
    versions = declared()
    assert len(versions) >= 4
    assert PYPROJECT["requires-python"] == f">={versions[0]}"
    minors = [int(version.split(".")[1]) for version in versions]
    assert minors == list(range(minors[0], minors[-1] + 1)), "a version is missing in between"


def test_ci_runs_exactly_the_versions_the_package_declares() -> None:
    matrix = CI["jobs"]["check"]["strategy"]["matrix"]["python-version"]
    assert ordered(matrix) == declared()


def test_the_badge_of_the_readme_names_the_declared_versions() -> None:
    [badge] = re.findall(r"img\.shields\.io/badge/python-([^)]*)\)", README)
    assert ordered(VERSION.findall(badge)) == declared()


def test_the_development_section_of_the_readme_names_the_declared_versions() -> None:
    [sentence] = re.findall(r"CI runs all of the above on Python ([^\n]*)\.", README)
    assert ordered(VERSION.findall(sentence)) == declared()


def test_the_contributing_guide_names_the_declared_versions() -> None:
    flat = " ".join(CONTRIBUTING.split())
    [sentence] = re.findall(r"CI runs them on Python ([^)]*)\)", flat)
    assert ordered(VERSION.findall(sentence)) == declared()
