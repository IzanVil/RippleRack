"""Properties of the Avro importer, checked on thousands of generated schemas.

The examples are derived from each test (see the settings profile in ``conftest.py``), so
they are the same on every run: a failure here is a real one, and Hypothesis shrinks it to
the smallest document that still fails.

* **a model**: a record is generated together with the fields it has to give, worked out when
  each type is built and not by reading it again, and the importer must give exactly those;
* **attributes that say nothing**: adding ``aliases``, ``default``, ``order`` and vendor
  attributes anywhere changes nothing, whatever the document is, even the message of an error;
* **choosing a record**: ``select`` finds each record of a list of types by its full name and,
  if no other has it, by its name alone, whatever the order of the list;
* **unions**: a union gives a field exactly when it has one type besides ``null``, and
  ``--lenient`` gives a ``json`` field for the others;
* **anything at all**: any document, and any text, gives a schema or a ``RippleRackError``,
  never another exception, and what is written always loads back as the schema it came from.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from hypothesis import event, given, settings
from hypothesis import strategies as st

from ripplerack.importers import IssueCode, render_schema_yaml
from ripplerack.importers.avro import from_avro, import_avro
from ripplerack.models import Schema
from ripplerack.parser import ErrorCode, RippleRackError

INVALID = ErrorCode.INVALID_AVRO_SCHEMA
UNSUPPORTED = ErrorCode.UNSUPPORTED_AVRO_SCHEMA

# ------------------------------------------------------------ records with a known result

SIMPLE = {
    "boolean": "boolean",
    "int": "integer",
    "long": "integer",
    "float": "float",
    "double": "float",
    "string": "string",
    "bytes": "string",
}
# A logical type on a type it fits, with what it makes of it.
FITTING: list[tuple[str, dict[str, Any], str]] = [
    ("long", {"logicalType": "timestamp-millis"}, "timestamp"),
    ("long", {"logicalType": "timestamp-micros"}, "timestamp"),
    ("long", {"logicalType": "timestamp-nanos"}, "timestamp"),
    ("long", {"logicalType": "local-timestamp-millis"}, "timestamp"),
    ("long", {"logicalType": "local-timestamp-micros"}, "timestamp"),
    ("long", {"logicalType": "local-timestamp-nanos"}, "timestamp"),
    ("int", {"logicalType": "date"}, "date"),
    ("int", {"logicalType": "time-millis"}, "string"),
    ("long", {"logicalType": "time-micros"}, "string"),
    ("string", {"logicalType": "uuid"}, "string"),
    ("bytes", {"logicalType": "decimal", "precision": 10, "scale": 2}, "float"),
    ("bytes", {"logicalType": "decimal", "precision": 3}, "float"),
    ("bytes", {"logicalType": "big-decimal"}, "float"),
]
# A logical type that is ignored: unknown, on the wrong type, or not valid.
IGNORED: list[tuple[str, dict[str, Any]]] = [
    ("long", {"logicalType": "no-such-type"}),
    ("long", {"logicalType": 7}),
    ("int", {"logicalType": "timestamp-millis"}),
    ("long", {"logicalType": "date"}),
    ("long", {"logicalType": "uuid"}),
    ("string", {"logicalType": "decimal", "precision": 4}),
    ("bytes", {"logicalType": "decimal"}),
    ("bytes", {"logicalType": "decimal", "precision": 4, "scale": 9}),
    ("bytes", {"logicalType": "decimal", "precision": 0}),
    ("bytes", {"logicalType": "decimal", "precision": 4, "scale": -1}),
    ("bytes", {"logicalType": "timestamp-millis"}),
]
# Attributes that no part of the importer reads.
HARMLESS = ["aliases", "order", "default", "x-vendor", "avro.java.string", "connect.name"]

field_names = st.one_of(
    st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,6}", fullmatch=True),
    st.sampled_from(["a.b", "c-d", "9", "no", "null", "true", "1e3", "2024-01-01"]),
)
record_names = st.one_of(
    st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,10}", fullmatch=True),
    st.sampled_from(["_", "__"]),  # no letter or digit: the file has to name the schema
)
namespaces = st.one_of(
    st.none(),
    st.just(""),
    st.from_regex(r"[a-z]{1,4}(\.[a-z]{1,4}){0,2}", fullmatch=True),
)
symbols = st.from_regex(r"[A-Z][A-Z0-9_]{0,5}", fullmatch=True)
docs = st.one_of(st.none(), st.text(max_size=20), st.sampled_from(["  Total\n in cents ", "x"]))

# The type of a field, the type it has to give, and the note it has to add to the description.
Typed = tuple[Any, str, str]
Defined = list[tuple[str, str, str]]  # the types defined so far: name, result, note


def note_of(listed: list[str]) -> str:
    """What an enum with these symbols has to add to the description."""
    if not listed:
        return ""
    shown = ", ".join(listed[:10])
    return f"One of: {shown}" + (f", … ({len(listed)} values)" if len(listed) > 10 else "")


@st.composite
def a_type(draw: st.DrawFn, index: int, defined: Defined, namespace: str | None) -> Typed:
    """A type with no union around it, and what it has to give.

    ``namespace`` is that of the record: what the record defines takes it, so it can be named
    in full as well as by its name alone.
    """
    kinds = ["simple", "object", "fitting", "ignored", "enum", "fixed", "record", "array", "map"]
    kind = draw(st.sampled_from([*kinds, *(["reference"] * 3 if defined else [])]))
    if kind == "simple":
        name = draw(st.sampled_from(sorted(SIMPLE)))
        return name, SIMPLE[name], ""
    if kind == "object":
        name = draw(st.sampled_from(sorted(SIMPLE)))
        extra = {draw(st.sampled_from(HARMLESS)): draw(st.integers(0, 3))}
        return {"type": name, **extra}, SIMPLE[name], ""
    if kind == "fitting":
        base, extra, result = draw(st.sampled_from(FITTING))
        return {"type": base, **extra}, result, ""
    if kind == "ignored":
        base, extra = draw(st.sampled_from(IGNORED))
        return {"type": base, **extra}, SIMPLE[base], ""
    if kind == "enum":
        listed = draw(st.lists(symbols, unique=True, max_size=12))
        name = f"E{index}"
        defined.append((name, "string", note_of(listed)))
        return {"type": "enum", "name": name, "symbols": listed}, "string", note_of(listed)
    if kind == "fixed":
        logical, result = draw(
            st.sampled_from(
                [(None, "string"), ("duration", "string"), ("uuid", "string"), ("decimal", "float")]
            )
        )
        name = f"F{index}"
        definition: dict[str, Any] = {
            "type": "fixed",
            "name": name,
            "size": draw(st.integers(1, 16)),
        }
        if logical:
            definition["logicalType"] = logical
        if logical == "decimal":
            definition["precision"] = 5
        defined.append((name, result, ""))
        return definition, result, ""
    if kind == "record":
        name = f"R{index}"
        inner = [{"name": "x", "type": draw(st.sampled_from(sorted(SIMPLE)))}]
        defined.append((name, "json", ""))
        record_kind = draw(st.sampled_from(["record", "error"]))
        return {"type": record_kind, "name": name, "fields": inner}, "json", ""
    if kind in ("array", "map"):
        contents: Any = draw(st.sampled_from(sorted(SIMPLE)))
        if draw(st.booleans()):  # a type defined inside, that the fields after it can use
            listed = draw(st.lists(symbols, unique=True, max_size=12))
            contents = {"type": "enum", "name": f"E{index}", "symbols": listed}
            defined.append((f"E{index}", "string", note_of(listed)))
        return {"type": kind, "items" if kind == "array" else "values": contents}, "json", ""
    name, result, note = draw(st.sampled_from(defined))
    spelling = draw(st.sampled_from(["name", "object", "full name"]))
    if spelling == "object":
        return {"type": name}, result, note  # a reference written as an object
    if spelling == "full name" and namespace:
        return f"{namespace}.{name}", result, note
    return name, result, note


@st.composite
def model_records(
    draw: st.DrawFn,
) -> tuple[dict[str, Any], list[tuple[str, str, bool, str]]]:
    """A record, and ``(name, type, nullable, description)`` of each field it has to give."""
    names = draw(st.lists(field_names, unique=True, min_size=1, max_size=8))
    namespace = draw(namespaces)
    defined: Defined = []
    declared: list[dict[str, Any]] = []
    expected: list[tuple[str, str, bool, str]] = []
    for index, name in enumerate(names):
        type_, result, note = draw(a_type(index, defined, namespace))
        wrap = draw(st.sampled_from(["plain", "null first", "null last", "alone"]))
        nullable = wrap in ("null first", "null last")
        field_type: Any = {
            "plain": type_,
            "null first": ["null", type_],
            "null last": [type_, "null"],
            "alone": [type_],
        }[wrap]
        field: dict[str, Any] = {"name": name, "type": field_type}
        description = note
        doc = draw(docs) if not note else None  # an enum with a doc is tested by example
        if doc is not None:
            field["doc"] = doc
            description = " ".join(doc.split())
        declared.append(field)
        expected.append((name, result, nullable, description))
    name = draw(record_names)
    document: dict[str, Any] = {"type": "record", "name": name, "fields": declared}
    if namespace and draw(st.booleans()):  # a full name: the namespace beside it is ignored
        document["name"] = f"{namespace}.{name}"
        if draw(st.booleans()):
            document["namespace"] = "ignored.because.the.name.is.a.full.name"
    elif namespace is not None:
        document["namespace"] = namespace
    return document, expected


def read(document: Any, **options: Any) -> list[tuple[str, str, bool, str]]:
    schema = from_avro(document, source="fuzz.avsc", **options).schema
    return [(f.name, str(f.type), f.nullable, f.description) for f in schema.fields]


@settings(max_examples=200)
@given(model=model_records(), lenient=st.booleans())
def test_a_record_gives_exactly_the_fields_it_was_built_to_give(
    model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]], lenient: bool
) -> None:
    document, expected = model
    result = from_avro(document, source="fuzz.avsc", lenient=lenient)
    assert [(f.name, str(f.type), f.nullable, f.description) for f in result.schema.fields] == (
        expected
    )
    assert result.issues == ()  # nothing in a record like this needs a warning
    assert Schema.model_validate(yaml.safe_load(render_schema_yaml(result.schema))) == (
        result.schema
    )


@given(model=model_records())
def test_the_text_of_a_record_says_what_the_record_does(
    model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]],
) -> None:
    document, _ = model
    assert import_avro(json.dumps(document), source="x.avsc") == from_avro(
        document, source="x.avsc"
    )


# ------------------------------------------------------------ documents of every shape
#
# Most of what is generated is well formed, with an occasional value of the wrong shape, so
# that the translation itself is exercised and not only the checks that refuse a document.

noise = st.one_of(
    st.none(), st.booleans(), st.integers(-2, 2), st.text(max_size=3), st.just([]), st.just({})
)
type_names = st.sampled_from(
    ["null", "boolean", "int", "long", "float", "double", "bytes", "string"]
)
reference_names = st.sampled_from(["A", "B", "C", "x.A", "a.B", "Nope", "record", "union"])
definition_names = st.sampled_from(["A", "B", "C", "x.A", "a.B", ""])
attribute_values = st.one_of(st.none(), st.booleans(), st.integers(0, 3), st.text(max_size=3))


def mostly(good: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """``good`` twenty-three times out of twenty-four, anything at all the last."""
    return st.one_of(*[good] * 23, noise)


def field_of(types: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.builds(
        lambda name, type_, doc, extra: {
            key: value
            for key, value in {"name": name, "type": type_, "doc": doc, **extra}.items()
            if value is not _MISSING
        },
        mostly(st.sampled_from(["a", "b", "c", "d-e", "f.g", "h i", ""])),
        st.one_of(*[types] * 9, st.just(_MISSING)),
        st.one_of(st.just(_MISSING), mostly(st.text(max_size=8))),
        st.dictionaries(st.sampled_from(HARMLESS), attribute_values, max_size=2),
    )


_MISSING = object()


def definitions(types: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Records, enums and fixed types, with names that sometimes collide or do not exist."""
    named = {"name": mostly(definition_names), "namespace": st.one_of(st.none(), st.just("x"))}

    def build(kind: str, name: Any, namespace: Any, extra: Any) -> dict[str, Any]:
        document: dict[str, Any] = {"type": kind, "name": name, **extra}
        if namespace is not None:
            document["namespace"] = namespace
        return document

    return st.one_of(
        st.builds(
            build,
            st.sampled_from(["record", "error"]),
            named["name"],
            named["namespace"],
            st.builds(
                lambda fields: {"fields": fields},
                mostly(st.lists(field_of(types), max_size=3)),
            ),
        ),
        st.builds(
            build,
            st.just("enum"),
            named["name"],
            named["namespace"],
            st.builds(lambda listed: {"symbols": listed}, mostly(st.lists(symbols, max_size=4))),
        ),
        st.builds(
            build,
            st.just("fixed"),
            named["name"],
            named["namespace"],
            st.builds(lambda size: {"size": size}, st.integers(1, 8)),
        ),
    )


def extend_types(children: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    return st.one_of(
        st.lists(children, max_size=3),
        st.builds(lambda items: {"type": "array", "items": items}, mostly(children)),
        st.builds(lambda values: {"type": "map", "values": values}, mostly(children)),
        definitions(children),
        st.builds(lambda inner: {"type": inner}, children),
    )


leaf_types = st.one_of(
    type_names,
    reference_names,
    st.builds(lambda kind: {"type": kind}, type_names),
    st.builds(
        lambda base, logical: {"type": base, "logicalType": logical, "precision": 4},
        type_names,
        st.sampled_from(["decimal", "date", "timestamp-millis", "uuid", "unknown", 3]),
    ),
    noise,
)
any_type = st.recursive(leaf_types, extend_types, max_leaves=6)
records = definitions(any_type).filter(lambda document: document["type"] in ("record", "error"))
documents = st.one_of(
    *[records] * 10,
    st.lists(definitions(any_type), max_size=4),
    st.lists(records, min_size=2, max_size=3),
    any_type,
    noise,
)
selects = st.one_of(st.none(), st.sampled_from(["A", "B", "C", "x.A", "a.B", "Nope", ""]))


def outcome(read_it: Any) -> tuple[Any, ...]:
    """What reading a document gave, in a form two readings can be compared by."""
    try:
        result = read_it()
    except RippleRackError as error:
        return ("refused", error.code, str(error))
    return ("imported", result.schema, result.issues)


@settings(max_examples=200)
@given(document=documents, lenient=st.booleans(), select=selects)
def test_any_document_gives_a_schema_or_a_ripplerack_error(
    document: Any, lenient: bool, select: str | None
) -> None:
    def from_the_document() -> Any:
        return from_avro(document, source="fuzz.avsc", lenient=lenient, select=select)

    def from_its_text() -> Any:
        return import_avro(json.dumps(document), source="fuzz.avsc", lenient=lenient, select=select)

    result = outcome(from_the_document)
    event(result[0])
    assert outcome(from_its_text) == result  # the text of a document says what the document does
    if result[0] == "imported":
        schema: Schema = result[1]
        assert Schema.model_validate(yaml.safe_load(render_schema_yaml(schema))) == schema
    else:
        assert result[1] in {
            ErrorCode.INVALID_AVRO_SCHEMA,
            ErrorCode.UNSUPPORTED_AVRO_SCHEMA,
            ErrorCode.VALIDATION_FAILED,
        }


@given(text=st.text(max_size=120))
def test_any_text_gives_a_schema_or_a_ripplerack_error(text: str) -> None:
    outcome(lambda: import_avro(text, source="fuzz.avsc"))


# ----------------------------------------------------------- attributes that say nothing


@st.composite
def with_harmless_attributes(draw: st.DrawFn, document: Any) -> Any:
    """A copy of ``document`` with attributes no part of the importer reads added anywhere."""
    if isinstance(document, list):
        return [draw(with_harmless_attributes(item)) for item in document]
    if not isinstance(document, dict):
        return document
    copy = {key: draw(with_harmless_attributes(value)) for key, value in document.items()}
    for key in draw(st.lists(st.sampled_from(HARMLESS), unique=True, max_size=3)):
        copy.setdefault(key, draw(attribute_values))
    return copy


@settings(max_examples=150)
@given(data=st.data(), document=documents, lenient=st.booleans(), select=selects)
def test_attributes_the_importer_does_not_read_change_nothing(
    data: st.DataObject, document: Any, lenient: bool, select: str | None
) -> None:
    decorated = data.draw(with_harmless_attributes(document))
    options: dict[str, Any] = {"lenient": lenient, "select": select}
    assert outcome(lambda: from_avro(decorated, source="f.avsc", **options)) == outcome(
        lambda: from_avro(document, source="f.avsc", **options)
    )


@settings(max_examples=100)
@given(data=st.data(), model=model_records())
def test_attributes_the_importer_does_not_read_change_nothing_in_a_record_either(
    data: st.DataObject, model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]]
) -> None:
    document, expected = model
    assert read(data.draw(with_harmless_attributes(document))) == expected


# ------------------------------------------------------------------ choosing a record


@st.composite
def lists_of_records(
    draw: st.DrawFn,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Records in three namespaces, and the names of the fields of each one by its full name."""
    count = draw(st.integers(1, 5))
    chosen = draw(
        st.lists(
            st.tuples(st.sampled_from(["", "x", "y.z"]), st.sampled_from(["A", "B", "C", "D"])),
            min_size=count,
            max_size=count,
            unique=True,
        )
    )
    document: list[dict[str, Any]] = []
    by_full: dict[str, list[str]] = {}
    for position, (namespace, name) in enumerate(chosen):
        field_name = f"f{position}"
        record: dict[str, Any] = {
            "type": "record",
            "name": name,
            "fields": [{"name": field_name, "type": "long"}],
        }
        if namespace:
            record["namespace"] = namespace
        document.append(record)
        by_full[f"{namespace}.{name}" if namespace else name] = [field_name]
    return document, by_full


@settings(max_examples=200)
@given(data=st.data(), records=lists_of_records())
def test_select_finds_every_record_wherever_it_is_in_the_list(
    data: st.DataObject, records: tuple[list[dict[str, Any]], dict[str, list[str]]]
) -> None:
    document, by_full = records
    shuffled = data.draw(st.permutations(document))

    def selecting(name: str) -> tuple[Any, ...]:
        return outcome(lambda: from_avro(shuffled, source="f.avsc", select=name))

    for full, field_names_ in by_full.items():
        assert [name for name, *_ in read(shuffled, select=full)] == field_names_
    simple = [full.rpartition(".")[2] for full in by_full]
    for name in sorted(set(simple)):
        if simple.count(name) == 1:  # no other record has the name: it is enough
            [full] = [full for full in by_full if full.rpartition(".")[2] == name]
            assert [n for n, *_ in read(shuffled, select=name)] == by_full[full]
        elif name in by_full:  # a full name is taken as it is, whatever else has that name
            assert [n for n, *_ in read(shuffled, select=name)] == by_full[name]
        else:
            assert selecting(name)[:2] == ("refused", UNSUPPORTED)
    assert selecting("Z")[:2] == ("refused", UNSUPPORTED)
    if len(document) == 1:
        [only] = by_full.values()
        assert [name for name, *_ in read(shuffled)] == only
    else:
        outcome_ = outcome(lambda: from_avro(shuffled, source="f.avsc"))
        assert outcome_[:2] == ("refused", UNSUPPORTED)


# --------------------------------------------------------------------------- unions

branches = st.sampled_from(
    [
        "int",
        "string",
        "boolean",
        {"type": "long", "logicalType": "timestamp-millis"},
        {"type": "array", "items": "string"},
        {"type": "map", "values": "long"},
    ]
)


@settings(max_examples=300)
@given(
    kinds=st.lists(branches, max_size=4),
    nulls=st.lists(st.integers(0, 4), unique=True, max_size=2),
)
def test_a_union_gives_a_field_only_when_it_has_one_type_besides_null(
    kinds: list[Any], nulls: list[int]
) -> None:
    union = list(kinds)
    for position in sorted(nulls):
        union.insert(min(position, len(union)), "null")
    document = {"type": "record", "name": "R", "fields": [{"name": "a", "type": union}]}
    has_null = "null" in union
    if len(kinds) == 1:
        expected = read(
            {"type": "record", "name": "R", "fields": [{"name": "a", "type": kinds[0]}]}
        )
        [(name, field_type, _, description)] = expected
        assert read(document) == [(name, field_type, has_null, description)]
    else:
        refused = outcome(lambda: from_avro(document, source="f.avsc"))
        assert refused[:2] == ("refused", ErrorCode.UNSUPPORTED_AVRO_SCHEMA)
        assert read(document, lenient=True) == [("a", "json", has_null, "")]


# ------------------------------------------------------ what is refused and what is forgiven

# A field that is not valid Avro, or whose name cannot be used, and the code of its error.
UNFORGIVEN: list[tuple[list[dict[str, Any]], ErrorCode]] = [
    ([{"name": "bad", "type": "Nope"}], INVALID),
    ([{"name": "bad", "type": ["null", ["int", "string"]]}], INVALID),
    ([{"name": "bad", "type": {"type": "array"}}], INVALID),
    ([{"name": "bad", "type": {"type": "map"}}], INVALID),
    ([{"name": "bad", "type": {"type": {"type": "string"}}}], INVALID),
    ([{"name": "bad", "type": 5}], INVALID),
    ([{"name": "bad", "type": "long", "doc": 5}], INVALID),
    ([{"name": "bad"}], INVALID),
    ([{"type": "long"}], INVALID),
    (
        [
            {"name": "bad", "type": {"type": "enum", "name": "Dup", "symbols": ["A"]}},
            {"name": "bad2", "type": {"type": "enum", "name": "Dup", "symbols": ["B"]}},
        ],
        INVALID,
    ),
    ([{"name": "a b", "type": "long"}], UNSUPPORTED),
]
# A type that is valid Avro but has no equivalent, and whether it admits null.
FORGIVEN: list[tuple[Any, bool]] = [
    (["int", "string"], False),
    (["null", "int", "string"], True),
    (["long", {"type": "array", "items": "int"}], False),
    ("null", True),
    ({"type": "null"}, True),
    (["null"], True),
    ([], False),
]


@settings(max_examples=150)
@given(data=st.data(), model=model_records(), lenient=st.booleans())
def test_what_is_not_valid_is_refused_in_both_modes(
    data: st.DataObject,
    model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]],
    lenient: bool,
) -> None:
    document, _ = model
    bad, code = data.draw(st.sampled_from(UNFORGIVEN))
    declared = document["fields"]
    position = data.draw(st.integers(0, len(declared)))
    declared[position:position] = bad
    refused = outcome(lambda: from_avro(document, source="f.avsc", lenient=lenient))
    assert refused[:2] == ("refused", code)


@settings(max_examples=100)
@given(data=st.data(), model=model_records(), lenient=st.booleans())
def test_a_field_declared_twice_is_refused_in_both_modes(
    data: st.DataObject,
    model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]],
    lenient: bool,
) -> None:
    document, expected = model
    name = data.draw(st.sampled_from([field[0] for field in expected]))
    document["fields"].append({"name": name, "type": "long"})
    refused = outcome(lambda: from_avro(document, source="f.avsc", lenient=lenient))
    assert refused[:2] == ("refused", INVALID)


@settings(max_examples=150)
@given(data=st.data(), model=model_records())
def test_a_field_with_no_equivalent_is_refused_or_imported_as_json(
    data: st.DataObject, model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]]
) -> None:
    document, expected = model
    type_, nullable = data.draw(st.sampled_from(FORGIVEN))
    position = data.draw(st.integers(0, len(expected)))
    document["fields"].insert(position, {"name": "odd_field", "type": type_})

    assert outcome(lambda: from_avro(document, source="f.avsc"))[:2] == ("refused", UNSUPPORTED)
    result = from_avro(document, source="f.avsc", lenient=True)
    wanted = [*expected[:position], ("odd_field", "json", nullable, ""), *expected[position:]]
    assert [(f.name, str(f.type), f.nullable, f.description) for f in result.schema.fields] == (
        wanted
    )
    [issue] = result.issues
    assert (issue.code, issue.pointer) == (IssueCode.DEGRADED_TO_JSON, f"#/fields/{position}/type")


# ------------------------------------------------------------------- the name of the schema


@settings(max_examples=100)
@given(
    model=model_records(),
    source=st.sampled_from(["a.avsc", "<stdin>", "dir/Other-Name.avsc", "C:\\x\\Y z.avsc"]),
)
def test_the_name_of_the_schema_comes_from_the_record_and_only_then_from_the_file(
    model: tuple[dict[str, Any], list[tuple[str, str, bool, str]]], source: str
) -> None:
    document, _ = model
    name = from_avro(document, source=source).schema.name
    if any(char.isalnum() for char in document["name"].rpartition(".")[2]):
        assert name == from_avro(document, source="same.avsc").schema.name
    elif source == "<stdin>":
        assert name == "schema"
    else:
        assert name == {"a.avsc": "a", "dir/Other-Name.avsc": "other_name"}.get(source, "y_z")


@given(namespace=namespaces, lenient=st.booleans())
def test_a_record_with_no_fields_is_refused_in_both_modes(
    namespace: str | None, lenient: bool
) -> None:
    document: dict[str, Any] = {"type": "record", "name": "Empty", "fields": []}
    if namespace is not None:
        document["namespace"] = namespace
    refused = outcome(lambda: from_avro(document, source="f.avsc", lenient=lenient))
    assert refused[:2] == ("refused", UNSUPPORTED)
