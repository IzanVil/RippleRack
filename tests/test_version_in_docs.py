"""The version of the package, where the documentation writes it down.

The guide and the template of the action tell users to pin the release (``@v0.2.4``), and the
examples of the JSON output carry ``tool.version``. Those places are edited by hand at each
release, and one forgotten leaves a guide that pins an old release or output that claims one.
These tests make the version of ``pyproject.toml`` the only one the documentation names.
"""

from __future__ import annotations

import re
import tomllib

import pytest

from tests.markdown import ROOT

VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
PINS = ["docs/ci.md", "action/README.md", "examples/ci/ripplerack.yml"]
TAG = re.compile(r"\bv\d+\.\d+\.\d+\b")
TOOL_VERSION = re.compile(r'"tool": \{ "name": "ripplerack", "version": "([^"]+)" \}')


@pytest.mark.parametrize("path", PINS)
def test_the_files_that_pin_the_release_name_the_current_one(path: str) -> None:
    tags = TAG.findall((ROOT / path).read_text(encoding="utf-8"))
    assert tags, f"{path} no longer names a release"
    assert set(tags) == {f"v{VERSION}"}, f"{path} pins {sorted(set(tags))}, not v{VERSION}"


def test_the_examples_of_the_json_output_carry_the_current_version() -> None:
    versions = TOOL_VERSION.findall((ROOT / "docs" / "output-formats.md").read_text("utf-8"))
    assert versions, "docs/output-formats.md no longer shows tool.version"
    assert set(versions) == {VERSION}, f"it shows {sorted(set(versions))}, not {VERSION}"
