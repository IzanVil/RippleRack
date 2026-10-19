"""``docs/ci.md`` and the workflow to copy must describe what the action really is and does.

The tables of inputs and outputs are read from the guide and compared with ``action/action.yml``,
the example of the comment is compared with what the command prints for the example files, the
workflow to copy is checked against the inputs the action has, and the version of the action that
the files name is the same everywhere, so that a release changes it in one command.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from ripplerack.cli import app
from tests.helpers import EXAMPLES
from tests.markdown import anchors, links, table_under, unwrap

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "ci.md"
TEXT = GUIDE.read_text(encoding="utf-8")
ACTION = ROOT / "action" / "action.yml"
TEMPLATE = ROOT / "examples" / "ci" / "ripplerack.yml"
FILES_THAT_NAME_THE_ACTION = [
    GUIDE,
    TEMPLATE,
    ROOT / "action" / "README.md",
]
REFERENCES = [
    ROOT / "README.md",
    ROOT / "docs" / "output-formats.md",
    ROOT / "docs" / "import.md",
    ROOT / "action" / "README.md",
]
USES = re.compile(r"IzanVil/RippleRack/action@(v\d+\.\d+\.\d+)")
runner = CliRunner()


def load(path: Path) -> dict[Any, Any]:
    document: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document  # a key may be True: YAML 1.1 reads on: as a boolean


ACTION_FILE = load(ACTION)


def documented_default(spec: dict[str, Any]) -> str:
    if spec.get("required"):
        return "(required)"
    default = spec.get("default")
    return "empty" if default == "" else f"`{default}`"


# -------------------------------------------------------------------------- the tables


def test_the_table_of_inputs_is_the_inputs_of_the_action() -> None:
    rows = table_under(TEXT, "### Inputs")
    assert [unwrap(name) for name, *_ in rows] == list(ACTION_FILE["inputs"])
    for name, default, _ in rows:
        assert default == documented_default(ACTION_FILE["inputs"][unwrap(name)]), name


def test_the_table_of_outputs_is_the_outputs_of_the_action() -> None:
    rows = table_under(TEXT, "### Outputs")
    assert [unwrap(name) for name, _ in rows] == list(ACTION_FILE["outputs"])


def test_the_exit_codes_of_the_command_are_the_three_that_exist() -> None:
    rows = table_under(TEXT, "## The command as a gate")
    assert [unwrap(code) for code, _ in rows] == ["0", "1", "2"]


# ------------------------------------------------------------------------------- the example


def test_the_example_comment_is_what_the_command_prints_for_the_example_files() -> None:
    lines = TEXT.splitlines()
    start = lines.index("### What the comment looks like")
    opening = next(i for i in range(start, len(lines)) if lines[i] == "````markdown")
    closing = next(i for i in range(opening + 1, len(lines)) if lines[i] == "````")
    shown = "\n".join(lines[opening + 1 : closing]) + "\n"
    result = runner.invoke(
        app,
        [
            "diff",
            str(EXAMPLES / "mini_datacenter.yaml"),
            str(EXAMPLES / "mini_datacenter_v2.yaml"),
            "-F",
            "markdown",
        ],
    )
    assert result.exit_code == 0
    assert shown == result.stdout


# ----------------------------------------------------------------------- the workflow to copy


def test_the_workflow_to_copy_uses_the_action_with_inputs_that_exist() -> None:
    workflow = load(TEMPLATE)
    steps = workflow["jobs"]["impact"]["steps"]
    [step] = [s for s in steps if str(s.get("uses", "")).startswith("IzanVil/RippleRack/action@")]
    assert set(step["with"]) <= set(ACTION_FILE["inputs"])
    assert "head" in step["with"]
    assert workflow["permissions"]["pull-requests"] == "write"
    triggers = workflow["on"] if "on" in workflow else workflow[True]  # YAML 1.1: on is True
    assert "pull_request" in triggers


def test_the_workflow_to_copy_reads_the_outputs_the_action_has() -> None:
    names = re.findall(
        r"steps\.ripplerack\.outputs\.([\w-]+)", TEMPLATE.read_text(encoding="utf-8")
    )
    assert names
    assert set(names) <= set(ACTION_FILE["outputs"])


def test_every_file_names_the_same_version_of_the_action() -> None:
    named = {
        path.name: set(USES.findall(path.read_text(encoding="utf-8")))
        for path in FILES_THAT_NAME_THE_ACTION
    }
    assert all(named.values()), f"a file does not name the version: {named}"
    assert len(set.union(*named.values())) == 1, named


# ------------------------------------------------------------------------------- the text


def test_installing_says_what_to_do_without_access_to_pypi() -> None:
    lines = TEXT.splitlines()
    start = lines.index("### Installing RippleRack")
    end = next(i for i in range(start + 1, len(lines)) if re.match(r"#{2,3} ", lines[i]))
    section = "\n".join(lines[start:end])
    assert "PIP_INDEX_URL" in section
    assert "wheel" in section


def test_the_guide_says_one_comment_is_kept_for_each_file() -> None:
    flat = " ".join(TEXT.split())
    assert "five pushes to a pull request leave one comment" in flat


# ------------------------------------------------------------------------------- links


def check_links(document: Path, only: Path | None = None) -> int:
    checked = 0
    for file, anchor in links(document):
        target = (document.parent / file).resolve() if file else document
        if only is not None and target != only:
            continue
        assert target.exists(), f"{document.name} links to {file}, which does not exist"
        if anchor and target.suffix == ".md":
            assert anchor in anchors(target), (
                f"{document.name}: no heading #{anchor} in {target.name}"
            )
        checked += 1
    return checked


def test_the_links_of_the_guide_resolve() -> None:
    assert check_links(GUIDE) >= 5


@pytest.mark.parametrize("document", REFERENCES, ids=lambda path: path.name)
def test_the_documents_that_link_to_the_guide_find_it(document: Path) -> None:
    assert check_links(document, only=GUIDE) >= 1
