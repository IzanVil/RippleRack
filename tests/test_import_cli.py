"""``ripplerack import`` as a user meets it: files, standard streams, exit codes."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner, Result

from ripplerack.cli import app
from ripplerack.models import Schema
from ripplerack.parser import load_schema

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")

DOCUMENT: dict[str, Any] = {
    "title": "Orders",
    "type": "object",
    "properties": {
        "order_id": {"type": "integer"},
        "amount_cents": {"type": "integer", "description": "Order total in cents"},
        "coupon_code": {"type": ["string", "null"]},
    },
    "required": ["order_id", "amount_cents"],
}
EXPECTED = (
    "name: orders\n"
    "version: 1.0.0\n"
    "fields:\n"
    "  - {name: order_id, type: integer}\n"
    "  - {name: amount_cents, type: integer, description: Order total in cents}\n"
    "  - {name: coupon_code, type: string, nullable: true}\n"
)
ONE_OF = {
    "type": "object",
    "properties": {"choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
    "required": ["choice"],
}
CLOSED = {**DOCUMENT, "additionalProperties": False}


def plain(text: str) -> str:
    """Remove colour codes and join wrapped lines, so text can be searched for."""
    return " ".join(ANSI.sub("", text).split())


def write(tmp_path: Path, document: Any = DOCUMENT, name: str = "orders.schema.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run(*args: str | Path, input: str | bytes | None = None) -> Result:
    # A wide terminal, so that long messages are not folded at 80 columns.
    return runner.invoke(app, ["import", *map(str, args)], input=input, env={"COLUMNS": "300"})


# ---------------------------------------------------------------------- the result


def test_import_prints_the_schema_on_standard_output(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "json-schema")
    assert result.exit_code == 0, result.output
    assert result.stdout == EXPECTED
    assert result.stderr == ""


def test_the_output_is_a_schema_file(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "json-schema")
    schema = Schema.model_validate(yaml.safe_load(result.stdout))
    assert (schema.name, schema.version, [f.name for f in schema.fields]) == (
        "orders",
        "1.0.0",
        ["order_id", "amount_cents", "coupon_code"],
    )


def test_name_and_version_can_be_given(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "json-schema", "--name", "mine", "--version", "2.3.4")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("name: mine\nversion: 2.3.4\n")


def test_the_name_falls_back_to_the_file_name_without_a_title(tmp_path: Path) -> None:
    document = {key: value for key, value in DOCUMENT.items() if key != "title"}
    result = run(write(tmp_path, document, "customer-events.schema.json"), "--from", "json-schema")
    assert result.stdout.startswith("name: customer_events\n")


def test_the_global_version_option_still_shows_the_release() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("ripplerack ")


# ------------------------------------------------------------------------ -o and -


def test_output_file(tmp_path: Path) -> None:
    out = tmp_path / "orders.yaml"
    result = run(write(tmp_path), "--from", "json-schema", "-o", out)
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == EXPECTED
    assert load_schema(out).name == "orders"
    assert "schema orders 1.0.0 (3 fields) written to" in plain(result.stdout)
    assert result.stderr == ""


def test_output_dash_is_standard_output(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "json-schema", "--output", "-")
    assert result.stdout == EXPECTED
    assert not (tmp_path / "-").exists()


def test_an_existing_output_file_is_not_overwritten(tmp_path: Path) -> None:
    out = tmp_path / "keep.yaml"
    out.write_text("precious\n", encoding="utf-8")
    result = run(write(tmp_path), "--from", "json-schema", "-o", out)
    assert result.exit_code == 1
    assert "already exists; use --force" in plain(result.stderr)
    assert out.read_text(encoding="utf-8") == "precious\n"
    assert result.stdout == ""


def test_force_overwrites_it(tmp_path: Path) -> None:
    out = tmp_path / "keep.yaml"
    out.write_text("old\n", encoding="utf-8")
    result = run(write(tmp_path), "--from", "json-schema", "-o", out, "--force")
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == EXPECTED


def test_the_input_file_is_never_overwritten(tmp_path: Path) -> None:
    source = write(tmp_path)
    for extra in ([], ["--force"]):
        result = run(source, "--from", "json-schema", "-o", source, *extra)
        assert result.exit_code == 1
        assert "refusing to overwrite the input file" in plain(result.stderr)
    assert json.loads(source.read_text(encoding="utf-8")) == DOCUMENT


def test_an_output_that_cannot_be_written_is_an_error(tmp_path: Path) -> None:
    out = tmp_path / "no-such-dir" / "orders.yaml"
    result = run(write(tmp_path), "--from", "json-schema", "-o", out)
    assert result.exit_code == 1
    assert "cannot write" in plain(result.stderr)


# --------------------------------------------------------------------- standard input


def test_standard_input(tmp_path: Path) -> None:
    result = run("-", "--from", "json-schema", input=json.dumps(DOCUMENT))
    assert result.exit_code == 0, result.output
    assert result.stdout == EXPECTED


def test_standard_input_without_a_title_is_called_schema() -> None:
    document = {key: value for key, value in DOCUMENT.items() if key != "title"}
    result = run("-", "--from", "json-schema", input=json.dumps(document))
    assert result.stdout.startswith("name: schema\n")


def test_a_byte_order_mark_is_accepted(tmp_path: Path) -> None:
    bom = b"\xef\xbb\xbf"
    from_stdin = run("-", "--from", "json-schema", input=bom + json.dumps(DOCUMENT).encode())
    assert from_stdin.stdout == EXPECTED
    path = tmp_path / "bom.json"
    path.write_bytes(bom + json.dumps(DOCUMENT).encode())
    assert run(path, "--from", "json-schema", "--name", "orders").stdout == EXPECTED


# ---------------------------------------------------------------------------- errors


def test_a_missing_file(tmp_path: Path) -> None:
    result = run(tmp_path / "nope.json", "--from", "json-schema")
    assert result.exit_code == 1
    assert "file not found" in plain(result.stderr)
    assert result.stdout == ""


def test_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"title": "caf\xe9"}')
    result = run(path, "--from", "json-schema")
    assert result.exit_code == 1
    assert "cannot read" in plain(result.stderr)


def test_standard_input_that_is_not_utf8() -> None:
    result = run("-", "--from", "json-schema", input=b'{"title": "caf\xe9"}')
    assert result.exit_code == 1
    assert "cannot read <stdin>" in plain(result.stderr)
    assert result.stdout == ""


def test_an_output_that_is_a_directory_is_a_usage_error(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "json-schema", "-o", tmp_path)
    assert result.exit_code == 2
    assert result.stdout == ""


def test_text_that_is_not_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    result = run(path, "--from", "json-schema")
    assert result.exit_code == 1
    assert "invalid JSON" in plain(result.stderr)
    assert result.stdout == ""


def test_a_schema_that_cannot_be_imported_names_the_place(tmp_path: Path) -> None:
    result = run(write(tmp_path, ONE_OF), "--from", "json-schema")
    assert result.exit_code == 1
    message = plain(result.stderr)
    assert "#/properties/choice/oneOf" in message
    assert "oneOf with 2 alternatives has no equivalent type" in message
    assert "--lenient" in message
    assert result.stdout == ""


def test_a_broken_schema_is_reported_too(tmp_path: Path) -> None:
    document = {"type": "object", "properties": {"a": {"type": "bogus"}}}
    result = run(write(tmp_path, document), "--from", "json-schema")
    assert result.exit_code == 1
    assert "#/properties/a/type" in plain(result.stderr)


def test_square_brackets_in_a_message_are_not_taken_for_markup(tmp_path: Path) -> None:
    document = {"type": "object", "properties": {"[bold]x": {}}}
    result = run(write(tmp_path, document), "--from", "json-schema")
    assert result.exit_code == 1
    assert "'[bold]x'" in plain(result.stderr)


def test_a_name_with_an_escape_sequence_is_not_sent_to_the_terminal_as_it_is(
    tmp_path: Path,
) -> None:
    document = {"type": "object", "properties": {"\x1b[31mRED\x1b[0m": {}}}
    result = run(write(tmp_path, document), "--from", "json-schema")
    assert result.exit_code == 1
    assert "\x1b[31mRED" not in result.stderr  # the command's own colours are different codes
    assert "#/properties/\\x1b[31mRED\\x1b[0m" in plain(result.stderr)


# ----------------------------------------------------------------------- warnings


@pytest.mark.parametrize("keyword", ["additionalProperties", "unevaluatedProperties"])
def test_warnings_go_to_standard_error_and_leave_the_output_alone(
    tmp_path: Path, keyword: str
) -> None:
    result = run(write(tmp_path, {**DOCUMENT, keyword: False}), "--from", "json-schema")
    assert result.exit_code == 0, result.output
    assert result.stdout == EXPECTED
    assert f"warning[additional_properties_ignored] #/{keyword}:" in plain(result.stderr)


def test_lenient_imports_what_strict_refuses(tmp_path: Path) -> None:
    source = write(tmp_path, ONE_OF)
    assert run(source, "--from", "json-schema").exit_code == 1
    result = run(source, "--from", "json-schema", "--lenient")
    assert result.exit_code == 0, result.output
    assert "choice, type: json}" in result.stdout
    assert "warning[degraded_to_json] #/properties/choice/oneOf:" in plain(result.stderr)


def test_warnings_do_not_stop_an_output_file(tmp_path: Path) -> None:
    out = tmp_path / "out.yaml"
    result = run(write(tmp_path, CLOSED), "--from", "json-schema", "-o", out)
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8") == EXPECTED
    assert "warning[additional_properties_ignored]" in plain(result.stderr)


# ------------------------------------------------------------------- usage errors


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        ([], "Missing argument"),
        (["FILE"], "Missing option '--from'"),
        (["FILE", "--from", "no-such-format"], "Invalid value for '--from'"),
        (["FILE", "--from", "json-schema", "--name", "two words"], "Invalid value for '--name'"),
        (["FILE", "--from", "json-schema", "--name", ""], "Invalid value for '--name'"),
        (["FILE", "--from", "json-schema", "--version", "1.0"], "MAJOR.MINOR.PATCH"),
        (["FILE", "--from", "json-schema", "--version", "v1.0.0"], "MAJOR.MINOR.PATCH"),
    ],
)
def test_usage_errors_exit_with_2(tmp_path: Path, args: list[str], fragment: str) -> None:
    source = write(tmp_path)
    result = run(*(str(source) if a == "FILE" else a for a in args))
    assert result.exit_code == 2
    assert fragment in plain(result.output)
    assert result.stdout == ""


def test_a_directory_is_not_a_file_to_import(tmp_path: Path) -> None:
    result = run(tmp_path, "--from", "json-schema")
    assert result.exit_code == 2


# --------------------------------------------------------------------------- help


def test_the_command_is_listed_and_documented() -> None:
    listing = plain(runner.invoke(app, ["--help"], env={"COLUMNS": "200"}).output)
    assert "import" in listing
    helptext = plain(runner.invoke(app, ["import", "--help"], env={"COLUMNS": "200"}).output)
    for fragment in (
        "--from",
        "json-schema",
        "avro",
        "--select",
        "--output",
        "--name",
        "--version",
        "--lenient",
        "--force",
    ):
        assert fragment in helptext


# ----------------------------------------------------------------------------- Avro

AVRO_DOCUMENT: dict[str, Any] = {
    "type": "record",
    "name": "Orders",
    "namespace": "com.example",
    "fields": [
        {"name": "order_id", "type": "long"},
        {"name": "amount_cents", "type": "long", "doc": "Order total in cents"},
        {"name": "coupon_code", "type": ["null", "string"], "default": None},
    ],
}
AVRO_EXPECTED = EXPECTED
SHOP: list[dict[str, Any]] = [
    {
        "type": "record",
        "name": "Address",
        "namespace": "shop",
        "fields": [{"name": "street", "type": "string"}],
    },
    {
        "type": "record",
        "name": "OrderEvent",
        "namespace": "shop",
        "fields": [{"name": "id", "type": "long"}],
    },
]
MIXED = {
    "type": "record",
    "name": "Mixed",
    "fields": [{"name": "choice", "type": ["string", "long"]}],
}


def write_avro(tmp_path: Path, document: Any = AVRO_DOCUMENT, name: str = "orders.avsc") -> Path:
    return write(tmp_path, document, name)


def test_avro_prints_the_schema_on_standard_output(tmp_path: Path) -> None:
    result = run(write_avro(tmp_path), "--from", "avro")
    assert result.exit_code == 0, result.output
    assert result.stdout == AVRO_EXPECTED
    assert result.stderr == ""


def test_avro_from_standard_input_is_named_after_the_record() -> None:
    result = run("-", "--from", "avro", input=json.dumps(AVRO_DOCUMENT))
    assert result.exit_code == 0, result.output
    assert result.stdout == AVRO_EXPECTED


def test_avro_name_version_and_output_file(tmp_path: Path) -> None:
    out = tmp_path / "mine.yaml"
    args = ("--from", "avro", "--name", "mine", "--version", "2.3.4", "-o", out)
    result = run(write_avro(tmp_path), *args)
    assert result.exit_code == 0, result.output
    schema = load_schema(out)
    assert (schema.name, schema.version, len(schema.fields)) == ("mine", "2.3.4", 3)
    assert "schema mine 2.3.4 (3 fields) written to" in plain(result.stdout)


def test_a_file_with_several_records_asks_which_one(tmp_path: Path) -> None:
    result = run(write_avro(tmp_path, SHOP, "shop.avsc"), "--from", "avro")
    assert result.exit_code == 1
    message = plain(result.stderr)
    assert "the file holds several records ('shop.Address', 'shop.OrderEvent')" in message
    assert "choose one with --select" in message
    assert result.stdout == ""


@pytest.mark.parametrize("select", ["OrderEvent", "shop.OrderEvent"])
def test_select_chooses_the_record(tmp_path: Path, select: str) -> None:
    result = run(write_avro(tmp_path, SHOP, "shop.avsc"), "--from", "avro", "--select", select)
    assert result.exit_code == 0, result.output
    assert (
        result.stdout
        == "name: order_event\nversion: 1.0.0\nfields:\n  - {name: id, type: integer}\n"
    )


def test_select_with_a_record_the_file_does_not_define(tmp_path: Path) -> None:
    result = run(write_avro(tmp_path, SHOP, "shop.avsc"), "--from", "avro", "--select", "Nope")
    assert result.exit_code == 1
    message = plain(result.stderr)
    assert "no record called 'Nope'" in message
    assert "'shop.Address', 'shop.OrderEvent'" in message


def test_select_is_a_usage_error_for_a_format_with_one_schema(tmp_path: Path) -> None:
    out = tmp_path / "out.yaml"
    result = run(write(tmp_path), "--from", "json-schema", "--select", "Orders", "-o", out)
    assert result.exit_code == 2
    assert "Invalid value for '--select'" in plain(result.output)
    assert "a json-schema file describes one schema, so there is nothing to select" in plain(
        result.output
    )
    assert result.stdout == ""
    assert not out.exists()


def test_avro_strict_and_lenient(tmp_path: Path) -> None:
    source = write_avro(tmp_path, MIXED, "mixed.avsc")
    strict = run(source, "--from", "avro")
    assert strict.exit_code == 1
    message = plain(strict.stderr)
    assert (
        "#/fields/0/type: the union ['string', 'long'] mixes several types in one field" in message
    )
    assert "hint: --lenient imports fields like these as json fields" in message
    assert strict.stdout == ""

    lenient = run(source, "--from", "avro", "--lenient")
    assert lenient.exit_code == 0, lenient.output
    assert (
        lenient.stdout == "name: mixed\nversion: 1.0.0\nfields:\n  - {name: choice, type: json}\n"
    )
    assert plain(lenient.stderr).startswith("warning[degraded_to_json] #/fields/0/type: the union")


def test_a_schema_that_is_not_avro_names_the_place(tmp_path: Path) -> None:
    document = {**AVRO_DOCUMENT, "fields": [{"name": "a", "type": "Nope"}]}
    result = run(write_avro(tmp_path, document), "--from", "avro")
    assert result.exit_code == 1
    assert "#/fields/0/type: unknown type 'Nope'" in plain(result.stderr)
    assert result.stdout == ""


def test_a_json_schema_is_not_taken_for_an_avro_schema(tmp_path: Path) -> None:
    result = run(write(tmp_path), "--from", "avro")
    assert result.exit_code == 1
    assert "the root is the type 'object'" in plain(result.stderr)
