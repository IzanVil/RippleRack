"""The YAML that ``import`` writes must load back as exactly the schema it came from."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ripplerack.importers import render_schema_yaml
from ripplerack.models import Schema
from ripplerack.parser import LoadedDatacenter, load_schema
from tests.helpers import make_schema


def load_back(schema: Schema) -> Schema:
    return Schema.model_validate(yaml.safe_load(render_schema_yaml(schema)))


def test_the_layout_follows_the_examples() -> None:
    schema = make_schema(
        "2.0.0",
        {"name": "order_id", "type": "integer"},
        {"name": "amount_cents", "type": "integer", "description": "Order total in cents"},
        {"name": "coupon_code", "nullable": True},
        {"name": "note", "nullable": True, "description": "Free text"},
        name="orders",
    )
    assert render_schema_yaml(schema) == (
        "name: orders\n"
        "version: 2.0.0\n"
        "fields:\n"
        "  - {name: order_id, type: integer}\n"
        "  - {name: amount_cents, type: integer, description: Order total in cents}\n"
        "  - {name: coupon_code, type: string, nullable: true}\n"
        "  - {name: note, type: string, nullable: true, description: Free text}\n"
    )


def test_defaults_are_left_out() -> None:
    text = render_schema_yaml(make_schema("1.0.0", {"name": "a"}))
    assert "nullable" not in text
    assert "description" not in text


def test_a_schema_without_fields_is_an_empty_list() -> None:
    schema = make_schema("1.0.0")
    assert render_schema_yaml(schema) == "name: orders\nversion: 1.0.0\nfields: []\n"
    assert load_back(schema) == schema


def test_the_output_is_deterministic_and_clean() -> None:
    schema = make_schema("1.0.0", {"name": "a", "description": "x"}, {"name": "b"})
    text = render_schema_yaml(schema)
    assert text == render_schema_yaml(schema)
    assert text.endswith("\n")
    assert all(line == line.rstrip() for line in text.splitlines())


def test_a_long_description_stays_on_its_line() -> None:
    schema = make_schema("1.0.0", {"name": "a", "description": "word " * 80})
    assert render_schema_yaml(schema).count("\n") == 4
    assert load_back(schema) == schema


def test_unicode_stays_readable() -> None:
    schema = make_schema("1.0.0", {"name": "a", "description": "Total del pedido, en céntimos"})
    assert "céntimos" in render_schema_yaml(schema)
    assert load_back(schema) == schema


def test_the_schemas_of_the_example_datacenter_come_back_unchanged(
    mini_dc: LoadedDatacenter,
) -> None:
    for pipeline in mini_dc.datacenter.pipelines:
        assert load_back(pipeline.schema_) == pipeline.schema_


def test_the_file_can_be_used_as_a_schema_file(tmp_path: Path) -> None:
    schema = make_schema(
        "1.4.0", {"name": "id", "type": "integer"}, {"name": "tag", "nullable": True}
    )
    path = tmp_path / "schema.yaml"
    path.write_text(render_schema_yaml(schema), encoding="utf-8")
    assert load_schema(path) == schema


# Text that YAML would read as something other than a string if it were written bare.
TRICKY_NAMES = [
    "no", "yes", "on", "off", "true", "false", "null", "Null", "NO", "y", "n",
    "1e3", "1.5", "0o17", "0x1F", "1_000", "2024-01-01", ".inf", ".nan", "-", "a.b", "-1",
]  # fmt: skip
TRICKY_TEXT = [
    "no", "null", "~", "2024-01-01", "1.5", "a: b", "x #y", "# not a comment", "it's",
    'say "hi"', "both ' and \"", "año", "日本語", "emoji 😀", "multi\nline", "tab\there",
    " lead", "trail ", " ", "- z", "{x}", "[y]", "@at", "%pct", "!tag", "&anchor", "*alias",
    "|", ">", "key: value: more", "\x85", "\u2028", "\ufeff", "\x00", "back\\slash", "'", '"',
    "=", "<<", "? q", ":", "a,b", "{a: 1}", "[1, 2]",
    "a\x85b", "\r", "\r\n", "line1\r\nline2", "\x0b", "\x0c", "\x1c", "\x7f", "\x9f", "\xa0",
    "\u3000", "\u200b", "\u2029", "\x85 ", " \x85",
]  # fmt: skip


@pytest.mark.parametrize("name", TRICKY_NAMES)
def test_names_that_look_like_other_yaml_types_come_back_as_the_same_text(name: str) -> None:
    schema = make_schema("1.0.0", {"name": name}, name=name)
    assert load_back(schema) == schema


@pytest.mark.parametrize("text", TRICKY_TEXT)
def test_descriptions_come_back_as_the_same_text(text: str) -> None:
    schema = make_schema("1.0.0", {"name": "a", "description": text})
    assert load_back(schema) == schema
