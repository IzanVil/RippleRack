"""``import`` on real files: the golden output, and the whole way on to ``impact``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from ripplerack.cli import app
from ripplerack.parser import load_schema
from tests.helpers import EXAMPLES, SCHEMAS, assert_json_golden, assert_text_golden

runner = CliRunner()
ORDERS_V2 = EXAMPLES / "schemas" / "orders_v2.schema.json"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_import(source: Path | str, *args: str) -> Result:
    # A wide terminal, so that a long error is not folded at 80 columns.
    return runner.invoke(
        app, ["import", str(source), "--from", "json-schema", *args], env={"COLUMNS": "300"}
    )


def test_the_example_is_imported_as_the_documented_yaml() -> None:
    result = run_import(ORDERS_V2, "--version", "2.0.0")
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert_text_golden("import_orders_v2.yaml", result.stdout)


def test_the_example_describes_the_same_schema_as_the_orders_v2_change(tmp_path: Path) -> None:
    out = tmp_path / "orders.yaml"
    assert run_import(ORDERS_V2, "--version", "2.0.0", "-o", str(out)).exit_code == 0
    assert load_schema(out) == load_schema(EXAMPLES / "changes" / "orders_v2.yaml")


def test_from_json_schema_to_impact_gives_the_orders_v2_golden(tmp_path: Path) -> None:
    """JSON Schema, import, impact: the same report as with ``changes/orders_v2.yaml``."""
    out = tmp_path / "orders.yaml"
    assert run_import(ORDERS_V2, "--version", "2.0.0", "-o", str(out)).exit_code == 0

    arguments = [
        "impact",
        str(EXAMPLES / "mini_datacenter.yaml"),
        "--pipeline",
        "orders-ingest",
        "--schema",
        str(out),
        "--format",
        "json",
    ]
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    assert_json_golden("impact_orders_v2.json", json.loads(result.stdout))

    gate = runner.invoke(app, [*arguments, "--fail-on-breaking"])
    assert gate.exit_code == 2  # the breaking change is found, as with the YAML file


@pytest.mark.parametrize(
    ("source", "options", "golden"),
    [
        ("kitchen_sink.schema.json", [], "import_kitchen_sink"),
        ("lenient.schema.json", ["--lenient"], "import_lenient"),
    ],
)
def test_golden_output_and_warnings(source: str, options: list[str], golden: str) -> None:
    result = run_import(SCHEMAS / source, *options)
    assert result.exit_code == 0, result.output
    assert_text_golden(f"{golden}.yaml", result.stdout)
    assert_text_golden(f"{golden}.warnings.txt", result.stderr)


def test_golden_error_for_a_schema_strict_mode_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(SCHEMAS)  # so that the file name in the message is the same everywhere
    result = run_import("lenient.schema.json")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert_text_golden("import_lenient.error.txt", ANSI.sub("", result.stderr))  # colours vary
