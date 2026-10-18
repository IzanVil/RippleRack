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
ORDERS_V2_AVRO = EXAMPLES / "schemas" / "orders_v2.avsc"
ORDERS_V2_SQL = EXAMPLES / "schemas" / "orders_v2.sql"
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# The same schema, written in each format: the examples are one and the same thing.
EXAMPLE_IN_EVERY_FORMAT = pytest.mark.parametrize(
    ("source_format", "example"),
    [("json-schema", ORDERS_V2), ("avro", ORDERS_V2_AVRO), ("sql", ORDERS_V2_SQL)],
    ids=["json-schema", "avro", "sql"],
)


def run_import(source: Path | str, *args: str, source_format: str = "json-schema") -> Result:
    # A wide terminal, so that a long error is not folded at 80 columns.
    return runner.invoke(
        app, ["import", str(source), "--from", source_format, *args], env={"COLUMNS": "300"}
    )


@EXAMPLE_IN_EVERY_FORMAT
def test_the_example_is_imported_as_the_documented_yaml(source_format: str, example: Path) -> None:
    result = run_import(example, "--version", "2.0.0", source_format=source_format)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert_text_golden("import_orders_v2.yaml", result.stdout)


@EXAMPLE_IN_EVERY_FORMAT
def test_the_example_describes_the_same_schema_as_the_orders_v2_change(
    source_format: str, example: Path, tmp_path: Path
) -> None:
    out = tmp_path / "orders.yaml"
    result = run_import(example, "--version", "2.0.0", "-o", str(out), source_format=source_format)
    assert result.exit_code == 0, result.output
    assert load_schema(out) == load_schema(EXAMPLES / "changes" / "orders_v2.yaml")


@EXAMPLE_IN_EVERY_FORMAT
def test_from_the_example_to_impact_gives_the_orders_v2_golden(
    source_format: str, example: Path, tmp_path: Path
) -> None:
    """Import, impact: the same report as with ``changes/orders_v2.yaml``, from either format."""
    out = tmp_path / "orders.yaml"
    result = run_import(example, "--version", "2.0.0", "-o", str(out), source_format=source_format)
    assert result.exit_code == 0, result.output

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
    report = runner.invoke(app, arguments)
    assert report.exit_code == 0, report.output
    assert_json_golden("impact_orders_v2.json", json.loads(report.stdout))

    gate = runner.invoke(app, [*arguments, "--fail-on-breaking"])
    assert gate.exit_code == 2  # the breaking change is found, as with the YAML file


@pytest.mark.parametrize(
    ("source", "source_format", "options", "golden"),
    [
        ("kitchen_sink.schema.json", "json-schema", [], "import_kitchen_sink"),
        ("lenient.schema.json", "json-schema", ["--lenient"], "import_lenient"),
        ("kitchen_sink.avsc", "avro", [], "import_avro_kitchen_sink"),
        ("lenient.avsc", "avro", ["--lenient"], "import_avro_lenient"),
        ("shop.avsc", "avro", ["--select", "OrderEvent"], "import_avro_shop"),
        ("kitchen_sink.sql", "sql", ["--dialect", "postgres"], "import_sql_kitchen_sink"),
        ("lenient.sql", "sql", ["--dialect", "postgres", "--lenient"], "import_sql_lenient"),
        (
            "pg_dump.sql",
            "sql",
            ["--dialect", "postgres", "--select", "orders"],
            "import_sql_pg_dump",
        ),
        ("mysqldump.sql", "sql", ["--dialect", "mysql"], "import_sql_mysqldump"),
        ("shop.sql", "sql", ["--dialect", "mysql", "--select", "OrderEvents"], "import_sql_shop"),
        ("sqlite.sql", "sql", ["--dialect", "sqlite", "--lenient"], "import_sql_sqlite"),
    ],
)
def test_golden_output_and_warnings(
    source: str, source_format: str, options: list[str], golden: str
) -> None:
    result = run_import(SCHEMAS / source, *options, source_format=source_format)
    assert result.exit_code == 0, result.output
    assert_text_golden(f"{golden}.yaml", result.stdout)
    assert_text_golden(f"{golden}.warnings.txt", result.stderr)


@pytest.mark.parametrize(
    ("source", "source_format", "options", "golden"),
    [
        ("lenient.schema.json", "json-schema", [], "import_lenient"),
        ("lenient.avsc", "avro", [], "import_avro_lenient"),
        ("shop.avsc", "avro", [], "import_avro_shop"),
        ("shop.avsc", "avro", ["--select", "Nope"], "import_avro_shop_nope"),
        ("lenient.sql", "sql", ["--dialect", "postgres"], "import_sql_lenient"),
        ("sqlite.sql", "sql", ["--dialect", "sqlite"], "import_sql_sqlite"),
        ("pg_dump.sql", "sql", ["--dialect", "postgres"], "import_sql_pg_dump"),
        ("shop.sql", "sql", ["--dialect", "mysql", "--select", "Nope"], "import_sql_shop_nope"),
        ("mysqldump.sql", "sql", [], "import_sql_mysqldump"),
    ],
)
def test_golden_error_for_a_schema_strict_mode_refuses(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    source_format: str,
    options: list[str],
    golden: str,
) -> None:
    monkeypatch.chdir(SCHEMAS)  # so that the file name in the message is the same everywhere
    result = run_import(source, *options, source_format=source_format)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert_text_golden(f"{golden}.error.txt", ANSI.sub("", result.stderr))  # colours vary
