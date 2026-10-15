"""Translation of a JSON Schema into a RippleRack schema, and everything that can go wrong."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ripplerack.importers import IMPORTERS, ImportIssue, IssueCode, SourceFormat
from ripplerack.importers.json_schema import from_json_schema, import_json_schema, parse_json
from ripplerack.parser import ErrorCode, RippleRackError


def record(**properties: Any) -> dict[str, Any]:
    """An object schema with these properties, every one of them required."""
    return {"type": "object", "properties": properties, "required": list(properties)}


def fields(document: Any, **options: Any) -> list[tuple[str, str, bool, str]]:
    """``(name, type, nullable, description)`` of every imported field."""
    result = from_json_schema(document, source="test.json", **options)
    return [(f.name, str(f.type), f.nullable, f.description) for f in result.schema.fields]


def one(prop: Any, *, required: bool = True, **options: Any) -> tuple[str, bool, str]:
    """``(type, nullable, description)`` of a single property called ``value``."""
    document: dict[str, Any] = {"type": "object", "properties": {"value": prop}}
    if required:
        document["required"] = ["value"]
    [(name, field_type, nullable, description)] = fields(document, **options)
    assert name == "value"
    return field_type, nullable, description


def issues(document: Any, **options: Any) -> list[ImportIssue]:
    return list(from_json_schema(document, source="test.json", **options).issues)


def fails(document: Any, code: ErrorCode, *fragments: str, **options: Any) -> str:
    """Import ``document``, expect ``code`` and the given fragments in the message."""
    with pytest.raises(RippleRackError) as excinfo:
        from_json_schema(document, source="test.json", **options)
    message = str(excinfo.value)
    assert excinfo.value.code is code, message
    for fragment in fragments:
        assert fragment in message, message
    return message


# ------------------------------------------------------------------------- types


@pytest.mark.parametrize(
    ("prop", "expected"),
    [
        ({"type": "string"}, "string"),
        ({"type": "string", "format": "date-time"}, "timestamp"),
        ({"type": "string", "format": "date"}, "date"),
        ({"type": "string", "format": "uuid"}, "string"),
        ({"type": "string", "format": "email"}, "string"),
        ({"type": "integer"}, "integer"),
        ({"type": "number"}, "float"),
        ({"type": ["integer", "number"]}, "float"),
        ({"type": "boolean"}, "boolean"),
        ({"type": "object"}, "json"),
        ({"type": "object", "properties": {"a": {"type": "string"}}}, "json"),
        ({"type": "array", "items": {"type": "string"}}, "json"),
        ({"properties": {"a": {}}}, "json"),
        ({"items": {"type": "string"}}, "json"),
        ({}, "json"),
        (True, "json"),
        ({"enum": ["a", "b"]}, "string"),
        ({"enum": [1, 2]}, "integer"),
        ({"enum": [1, 2.5]}, "float"),
        ({"enum": [True, False]}, "boolean"),
        ({"enum": ["a", 1]}, "json"),
        ({"enum": [{"a": 1}]}, "json"),
        ({"const": "EUR"}, "string"),
        ({"enum": ["2024-01-01"], "format": "date"}, "date"),
        ({"type": "string", "minLength": 3, "pattern": "^a", "default": "abc"}, "string"),
    ],
)
def test_types(prop: Any, expected: str) -> None:
    assert one(prop)[0] == expected


def test_fields_keep_the_order_of_the_properties() -> None:
    document = record(zeta={"type": "string"}, alpha={"type": "integer"}, mid={"type": "number"})
    assert [name for name, *_ in fields(document)] == ["zeta", "alpha", "mid"]


def test_nested_objects_and_arrays_are_one_field_and_are_not_flattened() -> None:
    document = record(
        address={"type": "object", "properties": {"street": {"type": "string"}}},
        tags={"type": "array", "items": {"type": "string"}},
    )
    assert fields(document) == [
        ("address", "json", False, ""),
        ("tags", "json", False, ""),
    ]


def test_a_property_that_must_not_exist_is_not_a_field() -> None:
    document = {"type": "object", "properties": {"a": {"type": "string"}, "b": False}}
    assert [name for name, *_ in fields(document)] == ["a"]


# --------------------------------------------------------------------- nullability


@pytest.mark.parametrize(
    "prop",
    [
        {"type": ["string", "null"]},
        {"type": ["null", "string"]},
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {"oneOf": [{"type": "null"}, {"type": "string"}]},
        {"anyOf": [{"type": "string"}, {"const": None}]},
        {"type": "string", "nullable": True},
        {"enum": ["a", None]},
        {"type": ["string", "null"], "enum": ["a", None]},
    ],
)
def test_a_value_that_may_be_null_is_nullable(prop: Any) -> None:
    field_type, nullable, _ = one(prop)
    assert field_type == "string"
    assert nullable


def test_required_properties_are_not_nullable_and_the_rest_are() -> None:
    document = {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "note": {"type": "string"}},
        "required": ["id"],
    }
    assert [(name, nullable) for name, _, nullable, _ in fields(document)] == [
        ("id", False),
        ("note", True),
    ]


def test_without_required_every_field_is_nullable() -> None:
    document = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "integer"}}}
    assert [nullable for _, _, nullable, _ in fields(document)] == [True, True]


def test_null_in_the_type_wins_over_required() -> None:
    assert one({"type": ["integer", "null"]}, required=True)[:2] == ("integer", True)


# ------------------------------------------------------------------- descriptions


def test_description_is_kept_on_one_line() -> None:
    prop = {"type": "string", "description": "  Order\n   total,\tin cents  "}
    assert one(prop)[2] == "Order total, in cents"


def test_title_stands_in_for_a_missing_description() -> None:
    assert one({"type": "string", "title": "Customer name"})[2] == "Customer name"
    assert one({"type": "string", "title": "T", "description": "D"})[2] == "D"


def test_enum_values_are_added_to_the_description() -> None:
    assert one({"type": "string", "enum": ["pending", "paid"]})[2] == "One of: pending, paid"
    prop = {"type": "string", "description": "Order status", "enum": ["pending", "paid"]}
    assert one(prop)[2] == "Order status. One of: pending, paid"
    prop["description"] = "Order status."
    assert one(prop)[2] == "Order status. One of: pending, paid"


def test_enum_note_skips_null_and_repeats_and_shows_other_types() -> None:
    prop = {"enum": ["a", "a", None, 2, True, {"k": 1}]}
    assert one(prop)[2] == 'One of: a, 2, true, {"k": 1}'


def test_a_long_enum_is_cut_with_a_count() -> None:
    prop = {"type": "integer", "enum": list(range(25))}
    assert one(prop)[2] == "One of: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, … (25 values)"


def test_const_is_noted_like_an_enum_of_one() -> None:
    assert one({"const": "EUR"})[2] == "Always: EUR"


# ------------------------------------------------------------------------- $ref


def test_local_references_are_resolved() -> None:
    document = {
        "type": "object",
        "required": ["status", "created"],
        "properties": {
            "status": {"$ref": "#/$defs/Status"},
            "created": {"$ref": "#/definitions/When"},
            "copy": {"$ref": "#/properties/created"},
        },
        "$defs": {"Status": {"type": "string", "enum": ["new", "done"]}},
        "definitions": {"When": {"type": "string", "format": "date-time"}},
    }
    assert fields(document) == [
        ("status", "string", False, "One of: new, done"),
        ("created", "timestamp", False, ""),
        ("copy", "timestamp", True, ""),
    ]


def test_keywords_next_to_a_reference_win() -> None:
    document = record(
        total={
            "$ref": "#/$defs/Money",
            "description": "Order total",
        }
    )
    document["$defs"] = {"Money": {"type": "number", "description": "An amount"}}
    assert fields(document) == [("total", "float", False, "Order total")]


def test_a_reference_can_be_followed_through_other_references() -> None:
    document = record(value={"$ref": "#/$defs/A"})
    document["$defs"] = {"A": {"$ref": "#/$defs/B"}, "B": {"type": "integer"}}
    assert fields(document) == [("value", "integer", False, "")]


def test_pointer_escapes_and_percent_encoding_are_understood() -> None:
    document = record(
        a={"$ref": "#/$defs/a~1b"},
        b={"$ref": "#/$defs/c%20d"},
        c={"$ref": "#/$defs/t~0x"},
        d={"$ref": "#/$defs/list/0"},
    )
    document["$defs"] = {
        "a/b": {"type": "integer"},
        "c d": {"type": "boolean"},
        "t~x": {"type": "number"},
        "list": [{"type": "string"}],
    }
    assert [(name, field_type) for name, field_type, *_ in fields(document)] == [
        ("a", "integer"),
        ("b", "boolean"),
        ("c", "float"),
        ("d", "string"),
    ]


def test_the_root_may_be_a_reference_to_a_definition() -> None:
    document = {
        "$ref": "#/$defs/Order",
        "$defs": {"Order": record(id={"type": "integer"})},
    }
    assert fields(document) == [("id", "integer", False, "")]


@pytest.mark.parametrize("ref", ["https://example.com/other.json", "other.json#/$defs/x"])
def test_a_reference_outside_the_document_is_unsupported(ref: str) -> None:
    fails(
        record(value={"$ref": ref}),
        ErrorCode.UNSUPPORTED_JSON_SCHEMA,
        "#/properties/value/$ref",
        "points outside this document",
    )


def test_a_local_definition_that_points_outside_is_unsupported_too() -> None:
    document = record(value={"$ref": "#/$defs/x"})
    document["$defs"] = {"x": {"$ref": "https://example.com/y.json"}}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "#/$defs/x/$ref", "points outside")


def test_a_circular_reference_is_unsupported() -> None:
    document = record(value={"$ref": "#/$defs/a"})
    document["$defs"] = {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "refers back to itself")


def test_the_same_definition_used_twice_is_not_a_cycle() -> None:
    document = record(a={"$ref": "#/$defs/n"}, b={"$ref": "#/$defs/n"})
    document["$defs"] = {"n": {"type": "integer"}}
    assert [field_type for _, field_type, *_ in fields(document)] == ["integer", "integer"]


def test_a_reference_that_points_nowhere_is_invalid() -> None:
    fails(
        record(value={"$ref": "#/$defs/missing"}),
        ErrorCode.INVALID_JSON_SCHEMA,
        "does not point to anything",
    )


def test_a_reference_into_a_list_with_a_huge_index_just_points_nowhere() -> None:
    document = record(value={"$ref": "#/$defs/list/" + "9" * 5000})
    document["$defs"] = {"list": [{"type": "string"}]}
    fails(document, ErrorCode.INVALID_JSON_SCHEMA, "does not point to anything")


def test_a_reference_to_a_position_in_a_list_must_be_a_plain_number() -> None:
    document = record(a={"$ref": "#/$defs/list/1"}, b={"$ref": "#/$defs/list/01x"})
    document["$defs"] = {"list": [{"type": "string"}, {"type": "integer"}]}
    fails(document, ErrorCode.INVALID_JSON_SCHEMA, "#/properties/b/$ref")
    del document["properties"]["b"], document["required"][1]
    assert fields(document) == [("a", "integer", False, "")]


def test_anchors_are_unsupported() -> None:
    fails(record(value={"$ref": "#node"}), ErrorCode.UNSUPPORTED_JSON_SCHEMA, "anchors")


def test_a_very_long_chain_of_references_is_cut_short() -> None:
    defs = {f"d{i}": {"$ref": f"#/$defs/d{i + 1}"} for i in range(60)}
    defs["d60"] = {"type": "string"}
    document = record(value={"$ref": "#/$defs/d0"})
    document["$defs"] = defs
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "nested too deeply")


# ------------------------------------------------------------------------- allOf


def test_a_single_allof_member_is_the_usual_way_to_add_text_to_a_reference() -> None:
    document = record(
        total={"allOf": [{"$ref": "#/$defs/Money"}], "description": "Order total"},
    )
    document["$defs"] = {"Money": {"type": "number"}}
    assert fields(document) == [("total", "float", False, "Order total")]


def test_allof_at_the_root_merges_the_members() -> None:
    document = {
        "allOf": [
            {"$ref": "#/$defs/Base"},
            {"type": "object", "properties": {"extra": {"type": "string"}}, "required": ["extra"]},
        ],
        "properties": {"own": {"type": "integer"}},
        "required": ["id"],
        "$defs": {"Base": record(id={"type": "integer"})},
    }
    assert fields(document) == [
        ("id", "integer", False, ""),
        ("extra", "string", False, ""),
        ("own", "integer", True, ""),
    ]


def test_the_same_property_declared_twice_the_same_way_is_fine() -> None:
    document = {
        "allOf": [record(id={"type": "integer"}), record(id={"type": "integer"})],
    }
    assert fields(document) == [("id", "integer", False, "")]


def test_the_same_property_declared_two_ways_is_unsupported() -> None:
    document = {"allOf": [record(id={"type": "integer"}), record(id={"type": "string"})]}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "#/allOf/1/properties/id", "differently")


def test_several_allof_members_on_a_field_are_unsupported() -> None:
    prop = {"allOf": [{"type": "string"}, {"minLength": 2}]}
    fails(record(value=prop), ErrorCode.UNSUPPORTED_JSON_SCHEMA, "allOf with 2 members")


# -------------------------------------------------------------- oneOf and anyOf


def test_a_union_with_null_reads_through_references() -> None:
    document = record(value={"anyOf": [{"$ref": "#/$defs/Id"}, {"type": "null"}]})
    document["$defs"] = {"Id": {"type": "integer"}}
    assert fields(document) == [("value", "integer", True, "")]


def test_the_text_next_to_a_union_is_kept() -> None:
    prop = {"anyOf": [{"type": "string", "description": "inner"}, {"type": "null"}]}
    assert one(prop)[2] == "inner"
    assert one({**prop, "description": "outer"})[2] == "outer"


@pytest.mark.parametrize(
    "prop",
    [
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]},
        {"anyOf": [{"type": "null"}]},
        {"oneOf": [{"type": "string"}], "anyOf": [{"type": "integer"}]},
    ],
)
def test_other_unions_are_unsupported(prop: Any) -> None:
    fails(record(value=prop), ErrorCode.UNSUPPORTED_JSON_SCHEMA, "#/properties/value")


def test_a_union_next_to_a_type_is_only_a_constraint() -> None:
    prop = {"type": "string", "anyOf": [{"format": "date"}, {"format": "date-time"}]}
    assert one(prop)[0] == "string"


# ------------------------------------------------------------- unsupported types


@pytest.mark.parametrize(
    ("prop", "fragment"),
    [
        ({"type": ["string", "integer"]}, "mixes several types"),
        ({"type": "null"}, "no data type"),
        ({"enum": [None]}, "only value is null"),
        ({"const": None}, "only value is null"),
        (False, "accepts nothing"),
    ],
)
def test_types_without_an_equivalent_are_unsupported(prop: Any, fragment: str) -> None:
    document = {"type": "object", "properties": {"value": {"allOf": [prop]}}}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, fragment)


# ------------------------------------------------------------------ lenient mode


def test_lenient_turns_unsupported_properties_into_json_fields_with_a_warning() -> None:
    document = record(
        keep={"type": "integer"},
        choice={"oneOf": [{"type": "string"}, {"type": "integer"}], "description": "A or B"},
        far={"$ref": "https://example.com/x.json"},
        mixed={"type": ["string", "integer"]},
    )
    assert fields(document, lenient=True) == [
        ("keep", "integer", False, ""),
        ("choice", "json", False, "A or B"),
        ("far", "json", False, ""),
        ("mixed", "json", False, ""),
    ]
    found = issues(document, lenient=True)
    assert [(i.code, i.pointer) for i in found] == [
        (IssueCode.DEGRADED_TO_JSON, "#/properties/choice/oneOf"),
        (IssueCode.DEGRADED_TO_JSON, "#/properties/far/$ref"),
        (IssueCode.DEGRADED_TO_JSON, "#/properties/mixed/type"),
    ]
    assert "imported as json" in found[0].message


def test_a_degraded_field_is_nullable_unless_required() -> None:
    document = {
        "type": "object",
        "properties": {"a": {"oneOf": [{}, {"type": "string"}]}, "b": {"anyOf": [{}, {}]}},
        "required": ["a"],
    }
    assert [(name, nullable) for name, _, nullable, _ in fields(document, lenient=True)] == [
        ("a", False),
        ("b", True),
    ]


def test_strict_mode_suggests_lenient_only_when_it_would_help() -> None:
    document = record(value={"oneOf": [{"type": "string"}, {"type": "integer"}]})
    assert "--lenient" in fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA)
    assert "--lenient" not in fails(record(**{"bad name": {}}), ErrorCode.UNSUPPORTED_JSON_SCHEMA)


def test_lenient_does_not_forgive_a_broken_schema() -> None:
    fails(record(value={"type": "bogus"}), ErrorCode.INVALID_JSON_SCHEMA, "'bogus'", lenient=True)
    fails(record(value={"$ref": "#/nowhere"}), ErrorCode.INVALID_JSON_SCHEMA, lenient=True)


def test_lenient_does_not_forgive_the_root() -> None:
    fails({"type": "array"}, ErrorCode.UNSUPPORTED_JSON_SCHEMA, lenient=True)
    fails(True, ErrorCode.UNSUPPORTED_JSON_SCHEMA, lenient=True)
    fails({"properties": {"a b": {}}}, ErrorCode.UNSUPPORTED_JSON_SCHEMA, lenient=True)


# --------------------------------------------------------------------- required


def test_a_required_name_that_is_not_declared_is_an_error() -> None:
    document = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a", "ghost"],
    }
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "#/required", "'ghost'", "not declared")


def test_lenient_adds_a_required_json_field_for_it_and_warns() -> None:
    document = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a", "ghost"],
    }
    assert fields(document, lenient=True) == [
        ("a", "string", False, ""),
        ("ghost", "json", False, ""),
    ]
    [issue] = issues(document, lenient=True)
    assert (issue.code, issue.pointer) == (IssueCode.UNDECLARED_REQUIRED, "#/required")


# -------------------------------------------------------------------- the root


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ({}, "no properties"),
        ({"type": "object"}, "no properties"),
        ({"type": "object", "properties": {}}, "no properties"),
        ({"type": "array", "items": {"type": "object"}}, "only object schemas"),
        ({"type": "string"}, "only object schemas"),
        (True, "boolean schema"),
        (False, "boolean schema"),
        ({"type": "object", "properties": {"a": False}}, "no fields"),
    ],
)
def test_a_root_without_fields_is_unsupported(document: Any, fragment: str) -> None:
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, fragment)


@pytest.mark.parametrize("document", [[], "schema", 3, None])
def test_a_root_that_is_not_a_schema_is_invalid(document: Any) -> None:
    fails(document, ErrorCode.INVALID_JSON_SCHEMA, "must be a JSON object")


def test_the_root_may_allow_null_next_to_object() -> None:
    document = {"type": ["object", "null"], "properties": {"a": {"type": "string"}}}
    assert [name for name, *_ in fields(document)] == ["a"]


def test_a_oneof_at_the_root_is_only_a_constraint_when_there_are_properties() -> None:
    document = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        "oneOf": [{"required": ["a"]}, {"required": ["b"]}],
    }
    assert [name for name, *_ in fields(document)] == ["a", "b"]


# --------------------------------------------- alternatives that would lose fields

BASE = {
    "type": "object",
    "properties": {"id": {"type": "integer"}, "kind": {"type": "string"}},
    "required": ["id"],
}
AMOUNT = {"properties": {"amount": {"type": "number"}}}


@pytest.mark.parametrize("lenient", [False, True])
@pytest.mark.parametrize(
    ("extra", "keyword", "where"),
    [
        pytest.param({"oneOf": [AMOUNT]}, "oneOf", "#/oneOf/0", id="oneOf"),
        pytest.param({"anyOf": [{"required": ["id"]}, AMOUNT]}, "anyOf", "#/anyOf/1", id="anyOf"),
        pytest.param({"then": AMOUNT}, "then", "#/then", id="then"),
        pytest.param({"else": AMOUNT}, "else", "#/else", id="else"),
        pytest.param(
            {"dependentSchemas": {"kind": AMOUNT}},
            "dependentSchemas",
            "#/dependentSchemas/kind",
            id="dependentSchemas",
        ),
        pytest.param(
            {"dependencies": {"kind": AMOUNT}},
            "dependencies",
            "#/dependencies/kind",
            id="dependencies",
        ),
        pytest.param(
            {"oneOf": [{"$ref": "#/$defs/V"}], "$defs": {"V": AMOUNT}},
            "oneOf",
            "#/oneOf/0",
            id="through a $ref",
        ),
        pytest.param({"oneOf": [{"allOf": [AMOUNT]}]}, "oneOf", "#/oneOf/0", id="through an allOf"),
    ],
)
def test_alternatives_that_declare_new_fields_are_refused(
    extra: dict[str, Any], keyword: str, where: str, lenient: bool
) -> None:
    """Their fields would be dropped without a word, so neither mode takes them."""
    message = fails(
        {**BASE, **extra},
        ErrorCode.UNSUPPORTED_JSON_SCHEMA,
        where,
        f"{keyword} declares properties that the schema does not ('amount')",
        "their fields would be lost",
        lenient=lenient,
    )
    assert "--lenient" not in message  # lenient would not help, so it is not suggested


@pytest.mark.parametrize(
    "extra",
    [
        {"oneOf": [{"required": ["id"]}, {"required": ["kind"]}]},
        {"anyOf": [{"properties": {"kind": {"const": "a"}}}, {"properties": {"kind": {}}}]},
        {"if": {"properties": {"kind": {"const": "card"}}}, "then": {"required": ["id"]}},
        {"if": {"properties": {"elsewhere": {"const": 1}}}},  # a condition, not a declaration
        {"then": {"properties": {"kind": {"type": "string"}}}},
        {"dependentSchemas": {"kind": {"required": ["id"]}}},
        {"dependencies": {"kind": ["id"]}},  # the array form lists names, it declares none
        {"not": {"properties": {"other": {}}}},
        {"oneOf": [{"$ref": "#/$defs/missing"}]},  # a reference that leads nowhere declares nothing
        {"oneOf": [True, False, 5, "x", None]},
    ],
)
def test_alternatives_that_only_constrain_declared_fields_change_nothing(
    extra: dict[str, Any],
) -> None:
    assert fields({**BASE, **extra}) == fields(BASE)


def test_alternatives_inside_an_allof_member_are_checked_too() -> None:
    document = {"allOf": [{**BASE, "oneOf": [AMOUNT]}]}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "#/allOf/0/oneOf/0", "'amount'")


def test_a_field_declared_anywhere_in_the_schema_is_not_lost() -> None:
    document = {**BASE, "allOf": [AMOUNT], "oneOf": [AMOUNT]}
    assert [name for name, *_ in fields(document)] == ["amount", "id", "kind"]


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_dynamic_references_are_not_followed(keyword: str) -> None:
    fails(
        record(value={keyword: "#node"}),
        ErrorCode.UNSUPPORTED_JSON_SCHEMA,
        f"#/properties/value/{keyword}",
        f"{keyword} is not supported",
    )


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_lenient_imports_a_dynamic_reference_as_json_with_a_warning(keyword: str) -> None:
    document = record(value={keyword: "#node", "description": "Any node"})
    assert fields(document, lenient=True) == [("value", "json", False, "Any node")]
    [issue] = issues(document, lenient=True)
    assert (issue.code, issue.pointer) == (
        IssueCode.DEGRADED_TO_JSON,
        f"#/properties/value/{keyword}",
    )


@pytest.mark.parametrize("lenient", [False, True])
@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_a_dynamic_reference_at_the_root_is_an_error_in_both_modes(
    keyword: str, lenient: bool
) -> None:
    document = {"type": "object", "properties": {"a": {}}, keyword: "#node"}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, f"#/{keyword}", lenient=lenient)


# ------------------------------------------------------------------ field names


@pytest.mark.parametrize("name", ["first name", "@id", "año", "a/b", "", " id", "id "])
def test_a_name_that_is_not_an_identifier_is_never_renamed_or_skipped(name: str) -> None:
    document = {"type": "object", "properties": {"ok": {"type": "string"}, name: {}}}
    fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA, "not a valid field name")


def test_names_with_dots_dashes_and_digits_are_fine() -> None:
    document = record(**{"a.b": {}, "c-d": {}, "_e": {}, "9": {}})
    assert [name for name, *_ in fields(document)] == ["a.b", "c-d", "_e", "9"]


def test_every_problem_is_reported_at_once() -> None:
    document = {
        "type": "object",
        "properties": {
            "bad name": {"type": "string"},
            "choice": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            "far": {"$ref": "https://example.com/x.json"},
        },
        "required": ["ghost"],
    }
    message = fails(document, ErrorCode.UNSUPPORTED_JSON_SCHEMA)
    for pointer in ("#/properties/bad name", "#/properties/choice/oneOf", "#/properties/far/$ref"):
        assert pointer in message
    assert "'ghost'" in message


def test_one_invalid_problem_makes_the_whole_error_invalid() -> None:
    document = record(a={"type": "bogus"}, b={"oneOf": [{}, {}, {}]})
    message = fails(document, ErrorCode.INVALID_JSON_SCHEMA, "#/properties/a/type")
    assert "#/properties/b/oneOf" in message


# ----------------------------------------------------------------- invalid shapes


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        (record(a={"type": "bogus"}), "'bogus' is not a JSON Schema type"),
        (record(a={"type": []}), "non-empty list"),
        (record(a={"type": 5}), "must be a string or a non-empty list"),
        ({"type": "object", "properties": [], "required": []}, "properties must be an object"),
        ({"type": "object", "properties": {"a": {}}, "required": "a"}, "required must be a list"),
        ({"type": "object", "properties": {"a": {}}, "required": [1]}, "required must be a list"),
        (record(a={"enum": "abc"}), "enum must be a list"),
        (record(a={"allOf": []}), "allOf must be a non-empty list"),
        (record(a={"anyOf": {}}), "anyOf must be a non-empty list"),
        (record(a={"description": 5}), "description must be a string"),
        (record(a={"nullable": "yes"}), "nullable must be true or false"),
        (record(a={"type": "string", "format": 3}), "format must be a string"),
        (record(a={"$ref": 3}), "$ref must be a string"),
        (record(a=[]), "a schema must be an object or a boolean"),
        (record(a="string"), "a schema must be an object or a boolean"),
    ],
)
def test_keywords_of_the_wrong_shape_are_invalid(document: Any, fragment: str) -> None:
    fails(document, ErrorCode.INVALID_JSON_SCHEMA, fragment)


# ----------------------------------------- additionalProperties, unevaluatedProperties

CLOSING = ["additionalProperties", "unevaluatedProperties"]


@pytest.mark.parametrize("keyword", CLOSING)
def test_false_at_the_root_is_a_warning(keyword: str) -> None:
    document = {**record(a={"type": "string"}), keyword: False}
    [issue] = issues(document)
    assert issue.code is IssueCode.ADDITIONAL_PROPERTIES_IGNORED
    assert issue.pointer == f"#/{keyword}"
    assert issue.message.startswith(f"{keyword}: false is ignored")


def test_both_keywords_on_one_schema_are_two_warnings_with_one_code() -> None:
    document = {
        **record(a={"type": "string"}),
        "additionalProperties": False,
        "unevaluatedProperties": False,
    }
    assert [(i.code, i.pointer) for i in issues(document)] == [
        (IssueCode.ADDITIONAL_PROPERTIES_IGNORED, "#/additionalProperties"),
        (IssueCode.ADDITIONAL_PROPERTIES_IGNORED, "#/unevaluatedProperties"),
    ]


def test_unevaluated_properties_closes_a_composition_the_usual_way() -> None:
    document = {
        "allOf": [{"$ref": "#/$defs/Base"}, {"properties": {"extra": {"type": "string"}}}],
        "unevaluatedProperties": False,
        "$defs": {"Base": record(id={"type": "integer"})},
    }
    assert [name for name, *_ in fields(document)] == ["id", "extra"]
    [issue] = issues(document)
    assert issue.pointer == "#/unevaluatedProperties"


@pytest.mark.parametrize("keyword", CLOSING)
def test_the_warning_does_not_change_the_imported_schema(keyword: str) -> None:
    plain = record(a={"type": "string"}, b={"type": "integer"})
    assert fields({**plain, keyword: False}) == fields(plain)


@pytest.mark.parametrize("lenient", [False, True])
@pytest.mark.parametrize("keyword", CLOSING)
def test_the_warning_is_given_in_both_modes(keyword: str, lenient: bool) -> None:
    document = {**record(a={"type": "string"}), keyword: False}
    assert [i.code for i in issues(document, lenient=lenient)] == [
        IssueCode.ADDITIONAL_PROPERTIES_IGNORED
    ]


@pytest.mark.parametrize("value", [True, {"type": "string"}, None, 0, "false"])
@pytest.mark.parametrize("keyword", CLOSING)
def test_other_values_say_nothing_to_warn_about(keyword: str, value: Any) -> None:
    document = {**record(a={"type": "string"}), keyword: value}
    assert issues(document) == []


def test_the_warning_covers_every_schema_that_is_read() -> None:
    document = {
        "allOf": [
            {"$ref": "#/$defs/Base"},
            {"properties": {"x": {"type": "string"}}, "unevaluatedProperties": False},
        ],
        "properties": {
            "shipping": {"type": "object", "additionalProperties": False},
            "via_ref": {"$ref": "#/$defs/Closed"},
            "optional": {
                "anyOf": [{"type": "object", "unevaluatedProperties": False}, {"type": "null"}]
            },
            "open": {
                "type": "object",
                "additionalProperties": True,
                "unevaluatedProperties": True,
            },
        },
        "unevaluatedProperties": False,
        "$defs": {
            "Base": {"properties": {"id": {"type": "integer"}}, "additionalProperties": False},
            "Closed": {"type": "object", "unevaluatedProperties": False},
            "Unused": {"additionalProperties": False, "unevaluatedProperties": False},
        },
    }
    assert sorted(i.pointer for i in issues(document)) == [
        "#/$defs/Base/additionalProperties",
        "#/$defs/Closed/unevaluatedProperties",
        "#/allOf/1/unevaluatedProperties",
        "#/properties/optional/anyOf/0/unevaluatedProperties",
        "#/properties/shipping/additionalProperties",
        "#/unevaluatedProperties",
    ]


@pytest.mark.parametrize("keyword", CLOSING)
def test_a_closed_definition_used_twice_is_reported_once(keyword: str) -> None:
    document = record(a={"$ref": "#/$defs/C"}, b={"$ref": "#/$defs/C"})
    document["$defs"] = {"C": {"type": "object", keyword: False}}
    assert [i.pointer for i in issues(document)] == [f"#/$defs/C/{keyword}"]


@pytest.mark.parametrize("keyword", CLOSING)
def test_issues_print_with_their_code_and_place(keyword: str) -> None:
    document = {**record(a={"type": "string"}), keyword: False}
    [issue] = issues(document)
    assert str(issue).startswith(
        f"warning[additional_properties_ignored] #/{keyword}: {keyword}: false"
    )


# ------------------------------------------------------------- name and version


def make(document: Any, source: str = "x.json", **options: Any) -> tuple[str, str]:
    schema = from_json_schema(document, source=source, **options).schema
    return schema.name, schema.version


def test_the_name_option_wins() -> None:
    document = {**record(a={}), "title": "Orders", "$id": "https://x.test/other.json"}
    assert make(document, name="mine") == ("mine", "1.0.0")


@pytest.mark.parametrize(
    ("extra", "source", "expected"),
    [
        ({"title": "Orders"}, "file.json", "orders"),
        ({"title": "Order Event v2!"}, "file.json", "order_event_v2"),
        ({"title": "Étude des commandes"}, "file.json", "etude_des_commandes"),
        ({"title": "!!!", "$id": "https://x.test/schemas/orders.schema.json"}, "f.json", "orders"),
        ({"$id": "https://x.test/schemas/Invoice.json?x=1#frag"}, "file.json", "invoice"),
        ({"$id": "https://x.test/"}, "events.schema.json", "events"),
        ({"$id": "urn:example:order"}, "file.json", "example_order"),
        ({}, "dir/Customer Data.json", "customer_data"),
        ({}, "<stdin>", "schema"),
        ({"title": "???"}, "<stdin>", "schema"),
        ({"title": ""}, "orders.json", "orders"),
    ],
)
def test_the_name_comes_from_title_then_id_then_the_file(
    extra: dict[str, Any], source: str, expected: str
) -> None:
    assert make({**record(a={}), **extra}, source=source)[0] == expected


@pytest.mark.parametrize("identifier", ["http://[::1", "//[", "http://[x]y/z.json", "[", ":"])
def test_an_id_that_is_not_a_url_does_not_stop_the_import(identifier: str) -> None:
    name, _ = make({**record(a={}), "$id": identifier}, source="<stdin>")
    assert name  # whatever can be made of it, or the fallback; never a crash


def test_a_recursion_error_while_reading_is_an_ordinary_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def too_deep(*args: Any, **kwargs: Any) -> str:
        raise RecursionError

    monkeypatch.setattr(json, "dumps", too_deep)  # whatever the interpreter's own limit is
    fails(record(value={"enum": ["a"]}), ErrorCode.INVALID_JSON_SCHEMA, "nested too deeply")


def test_a_document_nested_beyond_any_interpreter_limit_is_an_error_not_a_crash() -> None:
    deep: Any = "x"
    for _ in range(200_000):  # json.dumps gives up at 1000 levels on 3.11 and at 10000 later
        deep = [deep]
    fails(record(value={"enum": [deep]}), ErrorCode.INVALID_JSON_SCHEMA, "nested too deeply")


def test_a_title_that_is_not_text_is_invalid() -> None:
    fails(
        {**record(a={}), "title": 5}, ErrorCode.INVALID_JSON_SCHEMA, "#/title", "must be a string"
    )
    fails({**record(a={}), "$id": []}, ErrorCode.INVALID_JSON_SCHEMA, "#/$id", "must be a string")


def test_the_version_defaults_to_1_0_0_and_can_be_given() -> None:
    assert make(record(a={}))[1] == "1.0.0"
    assert make(record(a={}), version="2.3.4")[1] == "2.3.4"


@pytest.mark.parametrize(("name", "version"), [("bad name", "1.0.0"), ("ok", "1.0"), ("", "1.0.0")])
def test_a_name_or_version_the_model_rejects_is_a_validation_error(name: str, version: str) -> None:
    fails(record(a={}), ErrorCode.VALIDATION_FAILED, name=name, version=version)


# ------------------------------------------------------------------ parsing JSON


def test_parse_json_reads_ordinary_documents() -> None:
    assert parse_json('{"a": [1, 2.5, null, "x"]}', "f.json") == {"a": [1, 2.5, None, "x"]}


@pytest.mark.parametrize("text", ["", "{", "{'a': 1}", '{"a": 1,}', "[1 2]", '{"a": tru}', "\x00"])
def test_text_that_is_not_json_has_its_own_code(text: str) -> None:
    with pytest.raises(RippleRackError) as excinfo:
        parse_json(text, "f.json")
    assert excinfo.value.code is ErrorCode.INVALID_JSON
    assert str(excinfo.value).startswith("f.json: invalid JSON: ")


def test_a_number_with_thousands_of_digits_is_invalid_json() -> None:
    with pytest.raises(RippleRackError) as excinfo:
        parse_json("1" * 5000, "f.json")
    assert excinfo.value.code is ErrorCode.INVALID_JSON


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ('{"a": NaN}', "NaN is not valid JSON"),
        ('{"a": Infinity}', "Infinity is not valid JSON"),
        ('{"a": -Infinity}', "-Infinity is not valid JSON"),
        ('{"a": 1, "a": 2}', "'a' appears more than once"),
        ('{"properties": {"x": {}, "x": {"type": "string"}}}', "'x' appears more than once"),
        ("[" * 100_000, "nested too deeply"),
    ],
)
def test_json_that_would_be_read_ambiguously_is_rejected(text: str, fragment: str) -> None:
    with pytest.raises(RippleRackError) as excinfo:
        parse_json(text, "f.json")
    assert excinfo.value.code is ErrorCode.INVALID_JSON
    assert fragment in str(excinfo.value)


def test_import_json_schema_parses_and_translates() -> None:
    text = json.dumps(record(id={"type": "integer"}, at={"type": "string", "format": "date-time"}))
    result = import_json_schema(text, source="events.schema.json", version="3.0.0")
    assert result.schema.name == "events"
    assert result.schema.version == "3.0.0"
    assert [(f.name, str(f.type)) for f in result.schema.fields] == [
        ("id", "integer"),
        ("at", "timestamp"),
    ]


def test_the_importers_are_registered_by_format() -> None:
    importer = IMPORTERS[SourceFormat.JSON_SCHEMA]
    result = importer(
        '{"properties": {"a": {"type": "string"}}}',
        source="<stdin>",
        name="s",
        version="1.0.0",
        lenient=False,
    )
    assert result.schema.name == "s"
    assert result.issues == ()
