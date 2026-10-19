"""The files of the action: ``action.yml``, the workflow that tries it and what they promise.

``rr_action.py`` reads its inputs from variables and writes its outputs by name, and
``action.yml`` is what connects those to the workflow of whoever uses the action. A name that
changes in one place and not in the other would only be found when a workflow runs, so they are
compared here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import rr_action
from ripplerack.cli import app
from ripplerack.markdown import DEFAULT_MAX_ITEMS
from tests.helpers import EXAMPLES

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action" / "action.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "action-test.yml"
runner = CliRunner()


def load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


ACTION_FILE = load(ACTION)
STEPS: list[dict[str, Any]] = ACTION_FILE["runs"]["steps"]


def steps_of_the_workflow() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = load(WORKFLOW)["jobs"]["example"]["steps"]
    return steps


# ------------------------------------------------------------------------------- action.yml


def test_the_inputs_are_the_ones_the_script_reads() -> None:
    assert set(ACTION_FILE["inputs"]) == set(rr_action.INPUT_VARIABLES)


def test_each_input_reaches_the_script_in_its_own_variable() -> None:
    [compare] = [step for step in STEPS if step.get("id") == "compare"]
    for name, variable in rr_action.INPUT_VARIABLES.items():
        assert compare["env"][variable] == f"${{{{ inputs.{name} }}}}", name
    assert set(compare["env"]) == set(rr_action.INPUT_VARIABLES.values())


def test_the_outputs_are_the_ones_the_script_writes() -> None:
    assert tuple(ACTION_FILE["outputs"]) == rr_action.OUTPUT_NAMES
    for name, output in ACTION_FILE["outputs"].items():
        assert output["value"] == f"${{{{ steps.compare.outputs.{name} }}}}"
        assert output["description"]


def test_the_defaults_are_what_the_guide_promises() -> None:
    inputs = ACTION_FILE["inputs"]
    assert {name: spec.get("default") for name, spec in inputs.items()} == {
        "head": None,
        "base": "",
        "fail-on-breaking": "false",
        "comment-on-pr": "true",
        "github-token": "${{ github.token }}",
        "max-items": str(DEFAULT_MAX_ITEMS),
        "diagram": "true",
    }
    assert [name for name, spec in inputs.items() if spec.get("required")] == ["head"]
    assert all(spec["description"] for spec in inputs.values())


def test_it_is_a_composite_action_that_uses_no_other_action() -> None:
    assert ACTION_FILE["runs"]["using"] == "composite"
    assert all("uses" not in step for step in STEPS)
    assert all(step["shell"] == "bash" for step in STEPS)


def test_no_input_is_pasted_into_a_script() -> None:
    """``${{ inputs.x }}`` inside ``run`` would let a value become a command; env is safe."""
    for step in STEPS:
        assert "${{" not in step["run"], step["name"]


def test_the_steps_run_the_script_that_is_in_the_folder() -> None:
    commands = [step["run"] for step in STEPS]
    assert commands == [
        'python3 "$GITHUB_ACTION_PATH/rr_action.py" install',
        'python3 "$GITHUB_ACTION_PATH/rr_action.py" run',
    ]
    assert (ACTION.parent / "rr_action.py").is_file()


# ------------------------------------------------------------------------------- the workflow


def test_the_workflow_that_tries_the_action_runs_the_folder_with_inputs_that_exist() -> None:
    uses = [step for step in steps_of_the_workflow() if str(step.get("uses", "")).startswith("./")]
    assert [step["uses"] for step in uses] == ["./action", "./action"]
    for step in uses:
        assert set(step["with"]) <= set(ACTION_FILE["inputs"])
        assert "head" in step["with"]
        assert (ROOT / step["with"]["head"]).is_file()
        assert (ROOT / step["with"]["base"]).is_file()


def test_the_workflow_checks_the_values_the_action_really_reports() -> None:
    result = runner.invoke(
        app,
        [
            "diff",
            str(EXAMPLES / "mini_datacenter.yaml"),
            str(EXAMPLES / "mini_datacenter_v2.yaml"),
            "-F",
            "json",
        ],
    )
    severity, broken, at_risk = rr_action.summarize(json.loads(result.stdout))
    [check] = [
        s for s in steps_of_the_workflow() if s.get("name") == "Check what the action reported"
    ]
    assert f'test "$SEVERITY" = {severity}' in check["run"]
    assert f'test "$BROKEN" = {broken}' in check["run"]
    assert f'test "$AT_RISK" = {at_risk}' in check["run"]


def test_the_workflow_only_reads_and_does_not_comment() -> None:
    workflow = load(WORKFLOW)
    assert workflow["permissions"] == {"contents": "read"}
    for step in steps_of_the_workflow():
        if str(step.get("uses", "")).startswith("./"):
            assert step["with"]["comment-on-pr"] == "false"


def test_the_gate_is_expected_to_fail_and_the_workflow_says_so() -> None:
    [gate] = [s for s in steps_of_the_workflow() if s.get("id") == "gate"]
    assert gate["continue-on-error"] is True
    assert gate["with"]["fail-on-breaking"] == "true"
    [check] = [s for s in steps_of_the_workflow() if s.get("name") == "Check that the gate failed"]
    assert check["run"] == 'test "$OUTCOME" = failure'


@pytest.mark.parametrize("path", [ACTION, WORKFLOW])
def test_the_files_have_no_tab_and_end_with_a_newline(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "\t" not in text
    assert text.endswith("\n")
