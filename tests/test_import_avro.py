"""Translation of an Avro schema into a RippleRack schema, and everything that can go wrong."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from ripplerack.importers import (
    IMPORTERS,
    SELECTABLE,
    ImportIssue,
    IssueCode,
    SourceFormat,
)
from ripplerack.importers.avro import from_avro, import_avro
from ripplerack.importers.json_schema import import_json_schema
from ripplerack.parser import ErrorCode, RippleRackError

INVALID = ErrorCode.INVALID_AVRO_SCHEMA
UNSUPPORTED = ErrorCode.UNSUPPORTED_AVRO_SCHEMA


def record(**types: Any) -> dict[str, Any]:
    """A record called ``Row`` with these fields: the keyword is the name, the value the type."""
    return {
        "type": "record",
        "name": "Row",
        "fields": [{"name": name, "type": type_} for name, type_ in types.items()],
    }


def named(name: str, *fields: tuple[str, Any], **extra: Any) -> dict[str, Any]:
    """A record with these ``(name, type)`` fields, and any other attribute of its own."""
    return {
        "type": "record",
        "name": name,
        "fields": [{"name": field, "type": type_} for field, type_ in fields],
        **extra,
    }


def enum(name: str, *symbols: str, **extra: Any) -> dict[str, Any]:
    return {"type": "enum", "name": name, "symbols": list(symbols), **extra}


def logical(base: str, name: Any, **extra: Any) -> dict[str, Any]:
    return {"type": base, "logicalType": name, **extra}


def fields(document: Any, **options: Any) -> list[tuple[str, str, bool, str]]:
    """``(name, type, nullable, description)`` of every imported field."""
    result = from_avro(document, source="test.avsc", **options)
    return [(f.name, str(f.type), f.nullable, f.description) for f in result.schema.fields]


def one(type_: Any, **options: Any) -> tuple[str, bool, str]:
    """``(type, nullable, description)`` of a single field called ``value`` of this type."""
    [(name, field_type, nullable, description)] = fields(record(value=type_), **options)
    assert name == "value"
    return field_type, nullable, description


def issues(document: Any, **options: Any) -> list[ImportIssue]:
    return list(from_avro(document, source="test.avsc", **options).issues)


def fails(document: Any, code: ErrorCode, *fragments: str, **options: Any) -> str:
    """Import ``document``, expect ``code`` and the given fragments in the message."""
    with pytest.raises(RippleRackError) as excinfo:
        from_avro(document, source="test.avsc", **options)
    message = str(excinfo.value)
    assert excinfo.value.code is code, message
    for fragment in fragments:
        assert fragment in message, message
    return message


# ------------------------------------------------------------------------- types


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        ("boolean", "boolean"),
        ("int", "integer"),
        ("long", "integer"),
        ("float", "float"),
        ("double", "float"),
        ("string", "string"),
        ("bytes", "string"),
        ({"type": "long"}, "integer"),
        ({"type": "string", "avro.java.string": "String"}, "string"),
        (named("Address", ("street", "string")), "json"),
        ({"type": "error", "name": "Oops", "fields": []}, "json"),
        ({"type": "array", "items": "string"}, "json"),
        ({"type": "map", "values": "long"}, "json"),
        ({"type": "fixed", "name": "Hash", "size": 16}, "string"),
        (enum("Status", "NEW"), "string"),
    ],
)
def test_types(type_: Any, expected: str) -> None:
    assert one(type_)[0] == expected


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        (logical("long", "timestamp-millis"), "timestamp"),
        (logical("long", "timestamp-micros"), "timestamp"),
        (logical("long", "timestamp-nanos"), "timestamp"),
        (logical("long", "local-timestamp-millis"), "timestamp"),
        (logical("long", "local-timestamp-micros"), "timestamp"),
        (logical("long", "local-timestamp-nanos"), "timestamp"),
        (logical("int", "date"), "date"),
        (logical("int", "time-millis"), "string"),
        (logical("long", "time-micros"), "string"),
        (logical("string", "uuid"), "string"),
        ({"type": "fixed", "name": "Id", "size": 16, "logicalType": "uuid"}, "string"),
        ({"type": "fixed", "name": "Span", "size": 12, "logicalType": "duration"}, "string"),
        (logical("bytes", "decimal", precision=10, scale=2), "float"),
        (logical("bytes", "decimal", precision=5), "float"),  # the scale is 0 unless given
        (logical("bytes", "decimal", precision=4, scale=4), "float"),
        (
            {"type": "fixed", "name": "Money", "size": 8, "logicalType": "decimal", "precision": 9},
            "float",
        ),
        (logical("bytes", "big-decimal"), "float"),
    ],
)
def test_logical_types(type_: Any, expected: str) -> None:
    assert one(type_)[0] == expected


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        (logical("long", "no-such-type"), "integer"),
        (logical("long", 7), "integer"),
        (logical("long", None), "integer"),
        (logical("int", "timestamp-millis"), "integer"),  # a timestamp sits on a long
        (logical("long", "date"), "integer"),  # a date sits on an int
        (logical("long", "uuid"), "integer"),
        (logical("bytes", "timestamp-millis"), "string"),
        (logical("string", "decimal", precision=10), "string"),  # a decimal sits on bytes or fixed
        (logical("bytes", "decimal"), "string"),  # no precision
        (logical("bytes", "decimal", precision=0), "string"),
        (logical("bytes", "decimal", precision=-3), "string"),
        (logical("bytes", "decimal", precision=4, scale=5), "string"),  # scale above precision
        (logical("bytes", "decimal", precision=4, scale=-1), "string"),
        (logical("bytes", "decimal", precision="4"), "string"),
        (logical("bytes", "decimal", precision=4.5), "string"),
        (logical("bytes", "decimal", precision=True), "string"),
        (logical("bytes", "decimal", precision=4, scale=True), "string"),
    ],
)
def test_a_logical_type_that_is_unknown_or_does_not_fit_is_ignored(
    type_: Any, expected: str
) -> None:
    assert one(type_)[0] == expected


def test_fields_keep_the_order_of_the_record() -> None:
    document = record(zeta="string", alpha="long", mid="double")
    assert [name for name, *_ in fields(document)] == ["zeta", "alpha", "mid"]


def test_nested_records_arrays_and_maps_are_one_field_and_are_not_flattened() -> None:
    document = record(
        address=named("Address", ("street", "string")),
        tags={"type": "array", "items": "string"},
        attrs={"type": "map", "values": "long"},
    )
    assert fields(document) == [
        ("address", "json", False, ""),
        ("tags", "json", False, ""),
        ("attrs", "json", False, ""),
    ]


def test_what_is_inside_a_json_field_is_not_read() -> None:
    document = record(
        tags={"type": "array", "items": ["int", "string"]},
        deep={"type": "map", "values": {"type": "array", "items": "Nope"}},
    )
    assert [(name, field_type) for name, field_type, *_ in fields(document)] == [
        ("tags", "json"),
        ("deep", "json"),
    ]


def test_the_attributes_that_say_nothing_about_the_type_are_ignored() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "doc": "A record",
        "aliases": ["Old"],
        "custom": {"anything": True},
        "fields": [
            {
                "name": "a",
                "type": "long",
                "default": 0,
                "order": "descending",
                "aliases": ["b"],
                "x-custom": [1, 2],
            }
        ],
    }
    assert fields(document) == [("a", "integer", False, "")]


# --------------------------------------------------------------------- nullability


@pytest.mark.parametrize(
    ("type_", "expected"),
    [
        (["null", "string"], "string"),
        (["string", "null"], "string"),
        (["null", {"type": "string"}], "string"),
        ([{"type": "null"}, "long"], "integer"),
        (["null", logical("long", "timestamp-millis")], "timestamp"),
        (["null", logical("int", "date")], "date"),
        (["null", {"type": "array", "items": "string"}], "json"),
        (["null", named("Address", ("street", "string"))], "json"),
        (["null", {"type": "fixed", "name": "Hash", "size": 4}], "string"),
    ],
)
def test_a_union_with_null_is_a_nullable_field_of_the_other_type(type_: Any, expected: str) -> None:
    field_type, nullable, _ = one(type_)
    assert field_type == expected
    assert nullable


@pytest.mark.parametrize("type_", ["string", ["string"], {"type": "string"}, [{"type": "long"}]])
def test_a_type_that_cannot_be_null_is_not_nullable(type_: Any) -> None:
    assert not one(type_)[1]


def test_a_default_of_null_does_not_make_a_field_nullable() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "a", "type": "string", "default": None}],
    }
    assert fields(document) == [("a", "string", False, "")]


def test_only_a_union_with_null_makes_a_field_nullable() -> None:
    document = record(id="long", note=["null", "string"], tags={"type": "array", "items": "string"})
    assert [(name, nullable) for name, _, nullable, _ in fields(document)] == [
        ("id", False),
        ("note", True),
        ("tags", False),
    ]


# ----------------------------------------------------------------- unions of types


@pytest.mark.parametrize(
    ("type_", "fragment"),
    [
        (["int", "string"], "the union ['int', 'string'] mixes several types in one field"),
        (["null", "int", "string"], "the union ['int', 'string'] mixes several types"),
        (["string", "string"], "the union ['string', 'string'] mixes several types"),
        (
            [named("A"), named("B")],
            "the union ['record A', 'record B'] mixes several types in one field",
        ),
        (["int", {"type": "array", "items": "int"}], "['int', 'array']"),
        ([], "an empty union has no data type"),
        (["null"], "type 'null' on its own has no data type"),
        (["null", "null"], "type 'null' on its own has no data type"),
        ("null", "type 'null' on its own has no data type"),
        ({"type": "null"}, "type 'null' on its own has no data type"),
    ],
)
def test_a_field_that_has_no_single_type_is_unsupported(type_: Any, fragment: str) -> None:
    message = fails(record(value=type_), UNSUPPORTED, "#/fields/0/type", fragment)
    assert "hint: --lenient imports fields like these as json fields" in message


@pytest.mark.parametrize(
    ("type_", "nullable"),
    [
        (["int", "string"], False),
        (["null", "int", "string"], True),
        ([], False),
        (["null"], True),
        ("null", True),
        ({"type": "null"}, True),
    ],
)
def test_lenient_imports_such_a_field_as_json_with_a_warning(type_: Any, nullable: bool) -> None:
    document = record(before="long", value=type_, after="long")
    assert fields(document, lenient=True) == [
        ("before", "integer", False, ""),
        ("value", "json", nullable, ""),
        ("after", "integer", False, ""),
    ]
    [issue] = issues(document, lenient=True)
    assert issue.code is IssueCode.DEGRADED_TO_JSON
    assert issue.pointer == "#/fields/1/type"
    assert issue.message.endswith("; field 'value' imported as json")


@pytest.mark.parametrize(
    ("type_", "pointer"),
    [
        (["null", "Nope"], "#/fields/0/type/1"),
        (["Nope", "null"], "#/fields/0/type/0"),
        (["null", {"type": 5}], "#/fields/0/type/1/type"),
        (["null", {"type": "array"}], "#/fields/0/type/1"),
    ],
)
def test_a_problem_inside_a_union_names_the_branch(type_: Any, pointer: str) -> None:
    fails(record(value=type_), INVALID, f"{pointer}:")


def test_a_degraded_field_keeps_its_doc() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "v", "type": ["int", "string"], "doc": "Either\n one"}],
    }
    assert fields(document, lenient=True) == [("v", "json", False, "Either one")]


def test_strict_mode_gives_no_warning_for_what_it_imports() -> None:
    assert issues(record(a="long", b=["null", "string"])) == []


@pytest.mark.parametrize("lenient", [False, True])
def test_a_union_inside_a_union_is_invalid_in_both_modes(lenient: bool) -> None:
    message = fails(
        record(value=["null", ["string", "int"]]),
        INVALID,
        "#/fields/0/type/1",
        "a union cannot contain another union",
        lenient=lenient,
    )
    assert "hint" not in message


# ---------------------------------------------------------------------- enums


STATUS = enum("Status", "NEW", "PAID", "SHIPPED")


def test_an_enum_lists_its_symbols_in_the_description() -> None:
    assert one(STATUS) == ("string", False, "One of: NEW, PAID, SHIPPED")


def test_the_symbols_come_after_the_doc() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "s", "type": STATUS, "doc": "Order status"}],
    }
    assert fields(document) == [("s", "string", False, "Order status. One of: NEW, PAID, SHIPPED")]


def test_a_doc_that_ends_a_sentence_is_not_given_another_stop() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "s", "type": STATUS, "doc": "Where is it?"}],
    }
    assert fields(document)[0][3] == "Where is it? One of: NEW, PAID, SHIPPED"


def test_a_long_enum_is_cut_with_a_count() -> None:
    symbols = [f"S{n}" for n in range(25)]
    expected = "One of: " + ", ".join(symbols[:10]) + ", … (25 values)"
    assert one(enum("Big", *symbols))[2] == expected


def test_ten_symbols_are_all_listed() -> None:
    symbols = [f"S{n}" for n in range(10)]
    assert one(enum("Ten", *symbols))[2] == "One of: " + ", ".join(symbols)


def test_a_nullable_enum_is_a_nullable_string_with_its_symbols() -> None:
    assert one(["null", STATUS]) == ("string", True, "One of: NEW, PAID, SHIPPED")


def test_an_enum_without_symbols_has_nothing_to_list() -> None:
    assert one(enum("Empty")) == ("string", False, "")


def test_the_repeated_symbols_of_an_enum_are_listed_once() -> None:
    assert one(enum("Twice", "A", "B", "A"))[2] == "One of: A, B"


def test_an_enum_used_by_name_lists_its_symbols_wherever_it_is_used() -> None:
    document = record(first=STATUS, second="Status", third=["null", "Status"])
    assert fields(document) == [
        ("first", "string", False, "One of: NEW, PAID, SHIPPED"),
        ("second", "string", False, "One of: NEW, PAID, SHIPPED"),
        ("third", "string", True, "One of: NEW, PAID, SHIPPED"),
    ]


def test_the_doc_of_an_enum_itself_is_not_the_description_of_a_field() -> None:
    assert one(enum("Status", "A", doc="About the enum"))[2] == "One of: A"


# ----------------------------------------------------------------------- docs


def with_doc(doc: Any) -> dict[str, Any]:
    return {"type": "record", "name": "Row", "fields": [{"name": "a", "type": "long", "doc": doc}]}


def test_doc_is_the_description_on_one_line() -> None:
    assert fields(with_doc("  Order\n total\tin   cents "))[0][3] == "Order total in cents"


@pytest.mark.parametrize("doc", [None, "", "   \n "])
def test_no_doc_or_a_blank_one_is_no_description(doc: Any) -> None:
    assert fields(with_doc(doc))[0][3] == ""


@pytest.mark.parametrize("doc", [5, True, [], {}, ["a"]])
def test_a_doc_that_is_not_text_is_invalid(doc: Any) -> None:
    fails(with_doc(doc), INVALID, "#/fields/0/doc", "doc must be a string")


def test_the_doc_of_the_record_is_not_a_description() -> None:
    document = {**record(a="long"), "doc": "About the record"}
    assert fields(document) == [("a", "integer", False, "")]


# ----------------------------------------------------------------- field names


@pytest.mark.parametrize("name", ["first name", "@id", "año", "a/b", "", " id", "id ", "a\nb"])
def test_a_name_that_is_not_an_identifier_is_never_renamed_or_skipped(name: str) -> None:
    document = record(**{"ok": "string", name: "string"})
    message = fails(document, UNSUPPORTED, "#/fields/1/name", "not a valid field name")
    assert "hint" not in message  # lenient does not forgive it


def test_names_with_dots_dashes_and_digits_are_fine() -> None:
    document = record(**{"a.b": "long", "c-d": "long", "_e": "long", "9": "long"})
    assert [name for name, *_ in fields(document)] == ["a.b", "c-d", "_e", "9"]


@pytest.mark.parametrize("lenient", [False, True])
def test_a_name_that_is_not_an_identifier_stays_an_error_with_lenient(lenient: bool) -> None:
    fails(record(**{"a b": "long"}), UNSUPPORTED, "not a valid field name", lenient=lenient)


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("\x1b[31mRED\x1b[0m", "'\\x1b[31mRED\\x1b[0m'"),
        ("\x1b[2J\x1b[H", "'\\x1b[2J\\x1b[H'"),
        ("nul\x00", "'nul\\x00'"),
        ("bidi\u202eoverride", "'bidi\\u202eoverride'"),
    ],
)
def test_control_characters_in_a_name_are_written_out_in_a_message(name: str, shown: str) -> None:
    message = fails(record(**{name: "long"}), UNSUPPORTED, shown)
    assert not any(not char.isprintable() and char != "\n" for char in message)


def test_the_same_field_twice_is_invalid() -> None:
    document = {
        "type": "record",
        "name": "Row",
        "fields": [{"name": "a", "type": "long"}, {"name": "a", "type": "string"}],
    }
    fails(document, INVALID, "#/fields/1/name", "field 'a' is declared more than once")


# --------------------------------------------------------------------- references


def test_a_name_is_looked_up_first_in_the_namespace_of_the_record_that_uses_it() -> None:
    document = [
        enum("Status", "NEW", namespace="shop"),
        enum("Status", "OTHER", namespace="warehouse"),
        named("Order", ("status", "Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: NEW")]


def test_a_name_with_a_dot_is_a_full_name() -> None:
    document = [
        enum("Status", "NEW", namespace="shop"),
        enum("Status", "OTHER", namespace="warehouse"),
        named("Order", ("status", "warehouse.Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: OTHER")]


def test_a_simple_name_does_not_reach_into_another_namespace() -> None:
    document = [
        enum("Status", "NEW", namespace="warehouse"),
        named("Order", ("status", "Status"), namespace="shop"),
    ]
    fails(document, INVALID, "#/1/fields/0/type", "unknown type 'Status'")


def test_a_simple_name_falls_back_to_the_type_that_has_no_namespace() -> None:
    document = [
        enum("Status", "NEW"),
        named("Order", ("status", "Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: NEW")]


def test_the_empty_namespace_is_no_namespace() -> None:
    document = [
        enum("Status", "NEW", namespace=""),
        named("Order", ("status", "Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: NEW")]


def test_a_name_with_a_dot_ignores_the_namespace_written_next_to_it() -> None:
    document = [
        enum("warehouse.Status", "NEW", namespace="shop"),
        named("Order", ("status", "warehouse.Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: NEW")]


def test_a_name_with_a_dot_decides_the_namespace_its_record_reads_names_in() -> None:
    document = [
        enum("Status", "SHOP", namespace="shop"),
        enum("Status", "WAREHOUSE", namespace="warehouse"),
        named("warehouse.Box", ("status", "Status"), namespace="shop"),
    ]
    assert fields(document) == [("status", "string", False, "One of: WAREHOUSE")]


def test_a_type_defined_inside_a_record_has_the_namespace_of_that_record() -> None:
    document = named(
        "Order",
        ("status", enum("Status", "NEW")),
        ("again", "Status"),
        ("full", "shop.Status"),
        namespace="shop",
    )
    assert fields(document) == [
        ("status", "string", False, "One of: NEW"),
        ("again", "string", False, "One of: NEW"),
        ("full", "string", False, "One of: NEW"),
    ]


@pytest.mark.parametrize("written", ["absent", "null"])
def test_a_namespace_that_is_absent_or_null_is_that_of_the_type_that_contains_it(
    written: str,
) -> None:
    status = enum("Status", "NEW")
    if written == "null":
        status["namespace"] = None
    document = [
        named("Outer", ("status", status), namespace="shop"),
        named("Other", ("status", "shop.Status")),
    ]
    assert fields(document, select="Other") == [("status", "string", False, "One of: NEW")]


def test_a_namespace_given_to_a_type_is_inherited_by_what_it_defines() -> None:
    document = [
        named(
            "Outer",
            ("inner", named("Inner", ("x", "long"), namespace="deep")),
            ("status", enum("Status", "A")),
            namespace="shop",
        ),
        named("Other", ("status", "shop.Status"), ("inner", "deep.Inner")),
    ]
    assert fields(document, select="Other") == [
        ("status", "string", False, "One of: A"),
        ("inner", "json", False, ""),
    ]


def test_a_record_may_refer_to_itself() -> None:
    document = named("Node", ("value", "long"), ("next", ["null", "Node"]), ("kids", "Node"))
    assert fields(document) == [
        ("value", "integer", False, ""),
        ("next", "json", True, ""),
        ("kids", "json", False, ""),
    ]


def test_records_may_refer_to_each_other() -> None:
    document = [
        named("A", ("b", ["null", "B"])),
        named("B", ("a", ["null", "A"])),
    ]
    assert fields(document, select="A") == [("b", "json", True, "")]
    assert fields(document, select="B") == [("a", "json", True, "")]


def test_a_type_written_as_an_object_with_a_name_is_a_reference_too() -> None:
    document = record(a=STATUS, b={"type": "Status"})
    assert fields(document)[1] == ("b", "string", False, "One of: NEW, PAID, SHIPPED")


def test_a_fixed_type_used_by_name_keeps_its_logical_type() -> None:
    money = {"type": "fixed", "name": "Money", "size": 8, "logicalType": "decimal", "precision": 9}
    plain = {"type": "fixed", "name": "Hash", "size": 8}
    document = record(price=money, again="Money", hash=plain, other="Hash")
    assert [(name, field_type) for name, field_type, *_ in fields(document)] == [
        ("price", "float"),
        ("again", "float"),
        ("hash", "string"),
        ("other", "string"),
    ]


@pytest.mark.parametrize("lenient", [False, True])
def test_a_name_that_nothing_defines_is_invalid_in_both_modes(lenient: bool) -> None:
    message = fails(
        record(a="Nope"),
        INVALID,
        "#/fields/0/type",
        "unknown type 'Nope'",
        "no record, enum or fixed with that name",
        lenient=lenient,
    )
    assert "hint" not in message


@pytest.mark.parametrize("type_", ["record", "enum", "array", "map", "fixed", "union", "Null"])
def test_the_word_for_a_kind_of_type_is_not_a_type(type_: str) -> None:
    fails(record(a=type_), INVALID, f"unknown type '{type_}'")


def test_a_type_defined_twice_is_invalid() -> None:
    document = record(a=STATUS, b=enum("Status", "OTHER"))
    fails(document, INVALID, "#/fields/1/type/name", "'Status' is defined more than once")


def test_the_same_name_in_two_namespaces_is_two_types() -> None:
    document = [
        enum("Status", "A", namespace="x"),
        enum("Status", "B", namespace="y"),
        named("Row", ("s", "x.Status"), ("t", "y.Status")),
    ]
    assert fields(document) == [
        ("s", "string", False, "One of: A"),
        ("t", "string", False, "One of: B"),
    ]


def test_a_type_defined_twice_in_the_list_of_types_is_invalid() -> None:
    fails([named("A", ("x", "long")), named("A", ("y", "long"))], INVALID, "'A' is defined more")


# ----------------------------------------------------------------------- select


def shop() -> list[dict[str, Any]]:
    """Three records in two namespaces, one of them defined inside another, and an enum."""
    line = named("Line", ("sku", "string"))
    return [
        named("Address", ("street", "string"), namespace="shop"),
        named("Order", ("id", "long"), ("shipping", "Address"), ("line", line), namespace="shop"),
        named("Address", ("iban", "string"), namespace="billing"),
        enum("Color", "RED", namespace="shop"),
    ]


def test_a_list_of_types_with_one_record_imports_it() -> None:
    document = [enum("Color", "RED"), named("Only", ("a", "long")), "string"]
    assert fields(document) == [("a", "integer", False, "")]


def test_a_list_of_records_needs_to_be_told_which() -> None:
    message = fails(shop()[:3], UNSUPPORTED, "#:", "choose one with --select")
    assert "('billing.Address', 'shop.Address', 'shop.Order')" in message
    assert "hint" not in message


@pytest.mark.parametrize(
    ("select", "expected"),
    [
        ("shop.Order", ["id", "shipping", "line"]),
        ("Order", ["id", "shipping", "line"]),
        ("billing.Address", ["iban"]),
        ("shop.Address", ["street"]),
        ("Line", ["sku"]),  # defined inside Order, and still a record of the file
        ("shop.Line", ["sku"]),
    ],
)
def test_select_chooses_a_record_by_its_name_or_its_full_name(
    select: str, expected: list[str]
) -> None:
    assert [name for name, *_ in fields(shop(), select=select)] == expected


def test_a_name_that_two_records_share_must_be_given_in_full() -> None:
    fails(
        shop(),
        UNSUPPORTED,
        "several records are called 'Address'",
        "('billing.Address', 'shop.Address')",
        "give the full name",
        select="Address",
    )


def test_the_full_name_wins_over_the_name_alone() -> None:
    document = [named("A", ("plain", "long")), named("A", ("scoped", "long"), namespace="x")]
    assert [name for name, *_ in fields(document, select="A")] == ["plain"]
    assert [name for name, *_ in fields(document, select="x.A")] == ["scoped"]


@pytest.mark.parametrize("select", ["Nope", "shop.Nope", "Color", "shop.Color", "string", ""])
def test_select_names_a_record_that_the_file_does_not_define(select: str) -> None:
    message = fails(
        shop(), UNSUPPORTED, f"no record called {select!r}", "its records are", select=select
    )
    assert "'shop.Order'" in message
    assert "Color" not in message.split("its records are")[1]  # an enum is not a record


def test_select_in_a_file_with_no_record_at_all() -> None:
    fails(enum("E", "A"), UNSUPPORTED, "no record called 'X'", select="X")


def test_select_may_name_a_record_other_than_the_root() -> None:
    document = named("Outer", ("inner", named("Inner", ("x", "long"))), ("y", "string"))
    assert [name for name, *_ in fields(document)] == ["inner", "y"]
    assert [name for name, *_ in fields(document, select="Inner")] == ["x"]
    assert [name for name, *_ in fields(document, select="Outer")] == ["inner", "y"]


def test_the_name_of_the_schema_is_that_of_the_record_chosen() -> None:
    schema = from_avro(shop(), source="shop.avsc", select="shop.Order").schema
    assert schema.name == "order"


def test_select_finds_a_record_in_a_file_whose_root_is_not_one() -> None:
    document = {"type": "array", "items": named("Item", ("sku", "string"))}
    message = fails(
        document, UNSUPPORTED, "the root is the type 'array'", "choose one with --select"
    )
    assert "'Item'" in message
    assert [name for name, *_ in fields(document, select="Item")] == ["sku"]


WHERE: dict[str, Callable[[Any], Any]] = {
    "a field": lambda inner: inner,
    "an array": lambda inner: {"type": "array", "items": inner},
    "a map": lambda inner: {"type": "map", "values": inner},
    "a union": lambda inner: ["null", inner],
    "an array of maps of unions": lambda inner: {
        "type": "array",
        "items": {"type": "map", "values": ["null", inner]},
    },
}


@pytest.mark.parametrize("where", WHERE)
def test_a_record_can_be_selected_wherever_it_is_defined(where: str) -> None:
    document = record(holder=WHERE[where](named("Inner", ("x", "long"))))
    assert [name for name, *_ in fields(document)] == ["holder"]
    assert [name for name, *_ in fields(document, select="Inner")] == ["x"]


@pytest.mark.parametrize("where", WHERE)
def test_a_type_defined_anywhere_can_be_used_by_name_after_it(where: str) -> None:
    document = record(holder=WHERE[where](enum("Status", "NEW")), again="Status")
    assert fields(document)[1] == ("again", "string", False, "One of: NEW")


def test_an_error_type_is_a_record() -> None:
    document = [{"type": "error", "name": "Oops", "fields": [{"name": "why", "type": "string"}]}]
    assert fields(document) == [("why", "string", False, "")]


@pytest.mark.parametrize("count", [11, 30])
def test_a_long_list_of_records_is_cut_with_a_count(count: int) -> None:
    document = [named(f"R{n:02}", ("a", "long")) for n in range(count)]
    message = fails(document, UNSUPPORTED, "choose one with --select", f"({count} in all)")
    assert "'R09'" in message
    assert "'R10'" not in message


def test_ten_records_are_all_listed() -> None:
    document = [named(f"R{n}", ("a", "long")) for n in range(10)]
    message = fails(document, UNSUPPORTED, "'R9'")
    assert "in all" not in message


@pytest.mark.parametrize("select", ["\x1b[2J", "A\x1b[31m"])
def test_names_from_the_file_and_the_command_cannot_write_control_characters(select: str) -> None:
    hostile = "B\x1b[31m"
    document = [named("A", ("a", "long")), named(hostile, ("a", "long"))]
    for message in (
        fails(document, UNSUPPORTED, "choose one with --select"),
        fails(document, UNSUPPORTED, "no record called", select=select),
        fails(record(a="Nope\x1b[0m"), INVALID, "unknown type"),
        fails(record(a=["int", named(hostile)]), UNSUPPORTED, "mixes several types"),
    ):
        assert "\x1b" not in message


# ------------------------------------------------------------------------- the root


@pytest.mark.parametrize(
    ("root", "fragment"),
    [
        ("string", "the root is the type 'string'"),
        ({"type": "string"}, "the root is the type 'string'"),
        ({"type": "array", "items": "string"}, "the root is the type 'array'"),
        ({"type": "map", "values": "string"}, "the root is the type 'map'"),
        (enum("E", "A"), "the root is the type 'enum'"),
        ({"type": "fixed", "name": "F", "size": 4}, "the root is the type 'fixed'"),
        ({}, "the root is an object without a type"),
        ({"protocol": "P", "types": []}, "the root is an object without a type"),
        ({"type": {"type": "string"}}, "the root is an object without a type"),
        (["null", "string"], "the root is a list of types that holds no record"),
        ([], "the root is a list of types that holds no record"),
        (3, "the root is a number"),
        (None, "the root is null"),
        (True, "the root is a boolean"),
    ],
)
def test_the_root_must_be_a_record(root: Any, fragment: str) -> None:
    message = fails(root, UNSUPPORTED, "#:", fragment, "only a record can be imported")
    assert "hint" not in message  # --lenient would not help


@pytest.mark.parametrize("lenient", [False, True])
def test_a_root_that_is_not_a_record_is_an_error_in_both_modes(lenient: bool) -> None:
    fails("long", UNSUPPORTED, "the root is the type 'long'", lenient=lenient)


def test_a_record_without_fields_is_unsupported() -> None:
    fails(record(), UNSUPPORTED, "#:", "the record declares no fields to import")


def test_a_nested_record_without_fields_is_just_a_json_field() -> None:
    assert one(named("Empty")) == ("json", False, "")


# ---------------------------------------------------------------- invalid shapes


@pytest.mark.parametrize(
    ("document", "pointer", "fragment"),
    [
        ({"type": "record", "fields": []}, "#/name", "a record needs a name"),
        ({"type": "record", "name": "", "fields": []}, "#/name", "a record needs a name"),
        ({"type": "record", "name": 5, "fields": []}, "#/name", "a record needs a name"),
        ({"type": "error", "fields": []}, "#/name", "an error needs a name"),
        ({"type": "record", "name": "R"}, "#/fields", "the fields of a record must be a list"),
        (
            {"type": "record", "name": "R", "fields": {"a": "long"}},
            "#/fields",
            "the fields of a record must be a list",
        ),
        (
            {"type": "record", "name": "R", "namespace": 5, "fields": []},
            "#/namespace",
            "namespace must be a string",
        ),
        (record(a={"type": "enum", "symbols": ["A"]}), "#/fields/0/type/name", "an enum needs"),
        (record(a={"type": "fixed", "size": 4}), "#/fields/0/type/name", "a fixed type needs"),
        (record(a={"type": "enum", "name": "E"}), "#/fields/0/type/symbols", "list of strings"),
        (
            record(a={"type": "enum", "name": "E", "symbols": "AB"}),
            "#/fields/0/type/symbols",
            "list of strings",
        ),
        (
            record(a={"type": "enum", "name": "E", "symbols": ["A", 1]}),
            "#/fields/0/type/symbols",
            "list of strings",
        ),
        (record(a={"type": "array"}), "#/fields/0/type", "an array needs items"),
        (record(a={"type": "map"}), "#/fields/0/type", "a map needs values"),
        (record(a=5), "#/fields/0/type", "a type must be a name, an object or a list, found a n"),
        (record(a=None), "#/fields/0/type", "found null"),
        (record(a=True), "#/fields/0/type", "found a boolean"),
        (record(a={"name": "x"}), "#/fields/0/type/type", "the type of a schema must be a name"),
        (record(a={"type": 5}), "#/fields/0/type/type", "the type of a schema must be a name"),
        (
            record(a={"type": {"type": "string"}}),
            "#/fields/0/type/type",
            "the type of a schema must be a name",
        ),
        (
            record(a={"type": ["null", "string"]}),
            "#/fields/0/type/type",
            "the type of a schema must be a name",
        ),
    ],
)
def test_shapes_that_are_not_avro_are_invalid(document: Any, pointer: str, fragment: str) -> None:
    fails(document, INVALID, pointer, fragment)


@pytest.mark.parametrize(
    ("field", "pointer", "fragment"),
    [
        ("long", "#/fields/0", "a field must be an object, found a string"),
        (5, "#/fields/0", "found a number"),
        (None, "#/fields/0", "found null"),
        ([], "#/fields/0", "found an array"),
        ({"type": "long"}, "#/fields/0/name", "a field needs a name"),
        ({"name": 5, "type": "long"}, "#/fields/0/name", "a field needs a name"),
        ({"name": "a"}, "#/fields/0", "field 'a' has no type"),
    ],
)
def test_a_field_that_is_not_one_is_invalid(field: Any, pointer: str, fragment: str) -> None:
    document = {"type": "record", "name": "R", "fields": [field]}
    fails(document, INVALID, pointer, fragment)


def test_every_problem_is_reported_at_once_and_in_order() -> None:
    document = record(
        ok="long",
        ghost="Nope",
        mixed=["int", "string"],
        **{"bad name": "long"},
        late=["null"],
    )
    message = fails(document, INVALID)
    positions = [
        message.index(fragment)
        for fragment in (
            "#/fields/1/type: unknown type 'Nope'",
            "#/fields/2/type: the union ['int', 'string']",
            "#/fields/3/name: field name 'bad name'",
            "#/fields/4/type: type 'null' on its own",
        )
    ]
    assert positions == sorted(positions)
    assert message.startswith("test.avsc: cannot import this Avro schema:\n")


def test_unsupported_problems_alone_make_an_unsupported_error_with_a_hint() -> None:
    message = fails(record(a=["int", "string"], b=["null"]), UNSUPPORTED, "#/fields/0/type")
    assert "#/fields/1/type" in message
    assert message.endswith("hint: --lenient imports fields like these as json fields")


def test_one_invalid_problem_makes_the_whole_error_invalid_and_drops_the_hint() -> None:
    message = fails(record(a=["int", "string"], b="Nope"), INVALID, "#/fields/1/type")
    assert "#/fields/0/type" in message
    assert "hint" not in message


def test_lenient_does_not_forgive_what_is_invalid() -> None:
    document = record(a=["int", "string"], b="Nope")
    fails(document, INVALID, "#/fields/1/type", lenient=True)


def test_lenient_forgives_only_the_fields_it_can_and_the_rest_are_still_listed() -> None:
    document = record(a=["int", "string"], b="Nope", c=["null"])
    message = fails(document, INVALID, lenient=True)
    assert "#/fields/1/type" in message
    assert "#/fields/0/type" not in message  # forgiven
    assert "#/fields/2/type" not in message


def test_a_malformed_record_elsewhere_in_the_file_is_reported_even_if_it_is_not_chosen() -> None:
    document = [named("Good", ("a", "long")), {"type": "record", "name": "Bad"}]
    fails(document, INVALID, "#/1/fields", "the fields of a record must be a list", select="Good")


# --------------------------------------------------------------------- nesting


def nested(depth: int) -> dict[str, Any]:
    type_: Any = "string"
    for _ in range(depth):
        type_ = {"type": "array", "items": type_}
    return record(a=type_)


def test_nesting_well_under_the_limit_is_accepted() -> None:
    assert fields(nested(30)) == [("a", "json", False, "")]


def test_nesting_beyond_the_limit_is_an_error() -> None:
    fails(nested(40), UNSUPPORTED, "the schema is nested too deeply")


def test_unions_nested_deeply_are_an_error() -> None:
    type_: Any = "string"
    for _ in range(40):
        type_ = [{"type": "array", "items": type_}]
    fails(record(a=type_), UNSUPPORTED, "the schema is nested too deeply")


def test_records_nested_deeply_are_an_error() -> None:
    type_: Any = "string"
    for n in range(40):
        type_ = named(f"R{n}", ("x", type_))
    fails(record(a=type_), UNSUPPORTED, "the schema is nested too deeply")


def test_a_document_nested_beyond_any_interpreter_limit_is_an_error_not_a_crash() -> None:
    text = '{"type": "record", "name": "R", "fields": [{"name": "a", "type": ' + "[" * 200_000
    with pytest.raises(RippleRackError) as excinfo:
        import_avro(text, source="deep.avsc")
    assert excinfo.value.code is ErrorCode.INVALID_JSON


def test_a_type_nested_a_few_hundred_levels_is_an_error_not_a_crash() -> None:
    type_: Any = "string"
    for _ in range(500):
        type_ = [type_]
    fails(record(a=type_), UNSUPPORTED, "the schema is nested too deeply")


# ------------------------------------------------------------- name and version


def make(document: Any, source: str = "x.avsc", **options: Any) -> tuple[str, str]:
    schema = from_avro(document, source=source, **options).schema
    return schema.name, schema.version


@pytest.mark.parametrize(
    ("record_name", "expected"),
    [
        ("Orders", "orders"),
        ("orders", "orders"),
        ("OrderEvent", "order_event"),
        ("HTTPRequest", "http_request"),
        ("HTTPRequestLog", "http_request_log"),
        ("order_event", "order_event"),
        ("Order2Event", "order2_event"),
        ("v2Orders", "v2_orders"),
        ("ID", "id"),
        ("ORDER_EVENT", "order_event"),
        ("a.b.OrderEvent", "order_event"),
    ],
)
def test_the_name_of_the_schema_is_that_of_the_record(record_name: str, expected: str) -> None:
    assert make(named(record_name, ("a", "long")))[0] == expected


def test_the_namespace_is_not_part_of_the_name() -> None:
    assert make(named("Orders", ("a", "long"), namespace="com.example.orders"))[0] == "orders"


def test_the_name_option_wins() -> None:
    assert make(named("Orders", ("a", "long")), name="mine") == ("mine", "1.0.0")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("dir/Customer Data.avsc", "customer_data"),
        ("dir/customerEvents.avsc", "customer_events"),
        ("C:\\Users\\ana\\schemas\\order-lines.avsc", "order_lines"),
        ("orders.avsc", "orders"),
        ("orders.AVSC", "orders"),
        ("events.json", "events"),
        ("<stdin>", "schema"),
        ("dir/", "schema"),
    ],
)
def test_a_record_that_cannot_name_the_schema_leaves_it_to_the_file(
    source: str, expected: str
) -> None:
    assert make(named("_", ("a", "long")), source=source)[0] == expected


def test_the_record_comes_before_the_file_name() -> None:
    assert make(named("Orders", ("a", "long")), source="other.avsc")[0] == "orders"


def test_the_version_defaults_to_1_0_0_and_can_be_given() -> None:
    assert make(record(a="long"))[1] == "1.0.0"
    assert make(record(a="long"), version="2.3.4")[1] == "2.3.4"


@pytest.mark.parametrize(("name", "version"), [("bad name", "1.0.0"), ("ok", "1.0"), ("", "1.0.0")])
def test_a_name_or_version_the_model_rejects_is_a_validation_error(name: str, version: str) -> None:
    fails(record(a="long"), ErrorCode.VALIDATION_FAILED, name=name, version=version)


# ------------------------------------------------------------------ parsing JSON


def test_import_avro_parses_and_translates() -> None:
    text = json.dumps(named("Events", ("id", "long"), ("at", logical("long", "timestamp-millis"))))
    result = import_avro(text, source="events.avsc", version="3.0.0")
    assert result.schema.name == "events"
    assert result.schema.version == "3.0.0"
    assert [(f.name, str(f.type)) for f in result.schema.fields] == [
        ("id", "integer"),
        ("at", "timestamp"),
    ]


def test_import_avro_accepts_a_select() -> None:
    text = json.dumps(shop())
    result = import_avro(text, source="shop.avsc", select="shop.Order")
    assert result.schema.name == "order"


@pytest.mark.parametrize("text", ["", "{", "{'a': 1}", '{"a": 1,}', "[1 2]", "\x00"])
def test_text_that_is_not_json_has_its_own_code(text: str) -> None:
    with pytest.raises(RippleRackError) as excinfo:
        import_avro(text, source="f.avsc")
    assert excinfo.value.code is ErrorCode.INVALID_JSON
    assert str(excinfo.value).startswith("f.avsc: invalid JSON: ")


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ('{"type": "record", "name": "R", "fields": [], "name": "S"}', "'name' appears more than"),
        ('{"type": "record", "name": "R", "fields": [{"name": "a", "type": NaN}]}', "NaN"),
        (
            '{"type": "record", "name": "R", "fields": [{"name": "a", "name": "b"}]}',
            "'name' appears more than once",
        ),
    ],
)
def test_json_that_would_be_read_ambiguously_is_rejected(text: str, fragment: str) -> None:
    with pytest.raises(RippleRackError) as excinfo:
        import_avro(text, source="f.avsc")
    assert excinfo.value.code is ErrorCode.INVALID_JSON
    assert fragment in str(excinfo.value)


# ------------------------------------------------------------------- the registry


def test_the_importer_is_registered_by_format() -> None:
    importer = IMPORTERS[SourceFormat.AVRO]
    result = importer(
        json.dumps(record(a="long")),
        source="<stdin>",
        name="s",
        version="1.0.0",
        lenient=False,
        select=None,
    )
    assert result.schema.name == "s"
    assert result.issues == ()


def test_avro_is_the_only_format_that_can_select() -> None:
    assert set(SELECTABLE) == {SourceFormat.AVRO}
    assert set(IMPORTERS) == set(SourceFormat)


def test_a_json_schema_has_nothing_to_select() -> None:
    with pytest.raises(ValueError, match="select does not apply to JSON Schema"):
        import_json_schema('{"properties": {"a": {}}}', source="x.json", select="Order")
