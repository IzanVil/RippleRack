"""Properties that must hold for every input, checked on thousands of generated ones.

The examples are derived from each test (see the settings profile in ``conftest.py``), so
they are the same on every run: a failure here is a real one, and Hypothesis shrinks it to
the smallest document that still fails.

* what the importer writes always loads back as the schema it came from;
* the importer answers any document with a schema or a ``RippleRackError``, never with
  another exception, and reading the document from its text gives the same answer.
"""

from __future__ import annotations

import json
from typing import Any

import yaml
from hypothesis import event, given, settings
from hypothesis import strategies as st

from ripplerack.importers import render_schema_yaml
from ripplerack.importers.json_schema import from_json_schema, import_json_schema
from ripplerack.models import FieldType, Schema, SchemaField
from ripplerack.parser import RippleRackError

# ----------------------------------------------------------------- schemas to write

# Text that YAML is most likely to read as something else, so it is generated far more often
# than chance would: line breaks of every kind, indicators, quotes and invisible characters.
AWKWARD = "\x85\u2028\u2029\r\n\t\x00\x7f\ufeff\xa0 '\"#:-?[]{}&*!|>%@`,~=<"
# Names that YAML reads as a boolean, a null, a number or a date when they are not quoted.
AWKWARD_NAMES = [
    "no",
    "yes",
    "on",
    "off",
    "null",
    "true",
    "1e3",
    "1.5",
    "0o17",
    "2024-01-01",
    ".inf",
    "-",
]

identifiers = st.one_of(
    st.from_regex(r"[A-Za-z0-9_.\-]{1,12}", fullmatch=True), st.sampled_from(AWKWARD_NAMES)
)
versions = st.tuples(st.integers(0, 99), st.integers(0, 99), st.integers(0, 99)).map(
    lambda parts: ".".join(map(str, parts))
)
descriptions = st.one_of(
    st.text(max_size=24),
    st.text(alphabet=st.sampled_from(AWKWARD), max_size=5),  # short, so YAML picks the style
    st.text(alphabet=st.one_of(st.characters(), st.sampled_from(AWKWARD)), max_size=24),
)
schema_fields = st.builds(
    SchemaField,
    name=identifiers,
    type=st.sampled_from(FieldType),
    nullable=st.booleans(),
    description=descriptions,
)
schemas = st.builds(
    Schema,
    name=identifiers,
    version=versions,
    fields=st.lists(schema_fields, max_size=6, unique_by=lambda field: field.name),
)


@given(schema=schemas)
def test_the_yaml_always_loads_back_as_the_same_schema(schema: Schema) -> None:
    assert Schema.model_validate(yaml.safe_load(render_schema_yaml(schema))) == schema


# --------------------------------------------------------- documents to read
#
# Most of what is generated is well formed, with an occasional keyword of the wrong shape, so
# that the translation itself is exercised and not only the checks that refuse a document.

noise = st.one_of(
    st.none(), st.booleans(), st.integers(-2, 2), st.text(max_size=3), st.just([]), st.just({})
)
values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-2, 2),
    st.text(max_size=3),
    st.just({"k": 1}),
    st.just([1]),
)
type_names = st.sampled_from(["string", "number", "integer", "boolean", "object", "array", "null"])
property_names = st.sampled_from(["a", "b", "c", "d.e", "f-g", "h_i"])
odd_names = st.sampled_from(["h i", "@j", "", " k"])
definition_names = st.sampled_from(["a", "b", "a b", "~", "/"])
references = st.sampled_from(
    [
        "#",
        "#/$defs/a",
        "#/$defs/b",
        "#/$defs/a%20b",
        "#/$defs/~0",
        "#/$defs/~1",
        "#/definitions/a",
        "#/properties/a",
        "#/properties/a/anyOf/0",
        "#/allOf/0",
        "#/$defs/missing",
        "https://example.com/other.json",
        "other.json#/a",
        "#anchor",
    ]
)
document_ids = st.sampled_from(
    ["https://example.com/s/order.schema.json", "urn:example:order", "http://[::1", "", "x"]
)


def mostly(good: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """``good`` twenty-three times out of twenty-four, anything at all the last."""
    return st.one_of(*[good] * 23, noise)


def keyword(children: st.SearchStrategy[Any]) -> st.SearchStrategy[tuple[str, Any]]:
    """One keyword the reader looks at, with a value, usually of the right shape."""
    members = mostly(st.lists(children, min_size=1, max_size=2))
    return st.one_of(
        st.tuples(
            st.just("type"), mostly(type_names | st.lists(type_names, min_size=1, max_size=3))
        ),
        st.tuples(
            st.just("properties"), mostly(st.dictionaries(property_names, children, max_size=3))
        ),
        st.tuples(st.just("required"), mostly(st.lists(property_names, max_size=3))),
        st.tuples(st.just("enum"), mostly(st.lists(values, max_size=4))),
        st.tuples(st.just("const"), values),
        st.tuples(st.just("format"), mostly(st.sampled_from(["date", "date-time", "uuid"]))),
        st.tuples(st.just("$ref"), mostly(references)),
        st.tuples(st.just("allOf"), members),
        st.tuples(st.just("oneOf"), members),
        st.tuples(st.just("anyOf"), members),
        st.tuples(st.just("nullable"), mostly(st.booleans())),
        st.tuples(st.just("description"), mostly(st.text(max_size=12))),
        st.tuples(st.just("title"), mostly(st.text(max_size=8))),
        st.tuples(st.just("additionalProperties"), st.booleans() | children),
        st.tuples(st.just("items"), children),
    )


def schema_keywords(children: st.SearchStrategy[Any]) -> st.SearchStrategy[dict[str, Any]]:
    return st.lists(keyword(children), max_size=3).map(dict)


leaf_schemas = st.one_of(
    st.just({}),
    st.booleans(),
    st.builds(lambda kind: {"type": kind}, type_names),
    st.builds(lambda kind: {"type": kind}, type_names),
    st.builds(lambda kind, fmt: {"type": kind, "format": fmt}, type_names, st.just("date-time")),
    st.builds(lambda kind: {"type": [kind, "null"]}, type_names),
)
any_schema = st.recursive(leaf_schemas, schema_keywords, max_leaves=6)


@st.composite
def object_documents(
    draw: st.DrawFn, names: st.SearchStrategy[str] = property_names
) -> dict[str, Any]:
    """An object schema whose references and ``required`` names usually resolve."""
    properties = draw(st.dictionaries(names, any_schema, min_size=1, max_size=4))
    document: dict[str, Any] = {"type": "object", "properties": properties}
    if draw(st.booleans()):
        declared = st.sampled_from(sorted(properties))
        document["required"] = draw(
            st.one_of(*[st.lists(declared, max_size=3)] * 5, st.lists(property_names, max_size=2))
        )
    if draw(st.integers(0, 4)):  # usually
        document["$defs"] = {"a": draw(any_schema), "b": draw(any_schema)}
    if draw(st.booleans()):
        document["definitions"] = {"a": draw(any_schema)}
    if draw(st.booleans()):
        document["additionalProperties"] = draw(st.booleans())
    if draw(st.booleans()):
        document["title"] = draw(st.text(max_size=8))
    if draw(st.booleans()):
        document["$id"] = draw(document_ids | st.text(max_size=8))
    if draw(st.integers(0, 4)) == 0:
        document["allOf"] = draw(st.lists(any_schema, min_size=1, max_size=2))
    return document


documents = st.one_of(
    *[object_documents()] * 10, object_documents(odd_names | property_names), any_schema, noise
)


def outcome(read: Any) -> tuple[Any, ...]:
    """What reading a document gave, in a form two readings can be compared by."""
    try:
        result = read()
    except RippleRackError as error:
        return ("refused", error.code, str(error))
    return ("imported", result.schema, result.issues)


@settings(max_examples=200)
@given(document=documents, lenient=st.booleans())
def test_any_document_gives_a_schema_or_a_ripplerack_error(document: Any, lenient: bool) -> None:
    def from_the_document() -> Any:
        return from_json_schema(document, source="fuzz.json", lenient=lenient)

    def from_its_text() -> Any:
        return import_json_schema(json.dumps(document), source="fuzz.json", lenient=lenient)

    result = outcome(from_the_document)
    event(result[0])
    assert outcome(from_its_text) == result  # the text of a document says what the document does
    if result[0] == "imported":
        schema: Schema = result[1]
        assert Schema.model_validate(yaml.safe_load(render_schema_yaml(schema))) == schema


@given(text=st.text(max_size=120))
def test_any_text_gives_a_schema_or_a_ripplerack_error(text: str) -> None:
    outcome(lambda: import_json_schema(text, source="fuzz.json"))
