"""Read a JSON Schema and translate it into a RippleRack schema.

A RippleRack schema is flat and small: a list of fields, each with one of seven types and a
``nullable`` flag. A JSON Schema can say far more, so the reader only looks at the keywords
that decide which fields exist, what type they have and whether they are optional. Every
other keyword (value constraints such as ``minimum`` or ``pattern``, annotations, vendor
extensions) is ignored.

A construct that does decide the type but has no equivalent is an error, so nothing is lost
without anyone noticing. With ``lenient`` the property becomes a ``json`` field and a
warning says so. ``docs/import.md`` lists every rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from pydantic import ValidationError

from ripplerack.importers.base import ImportResult, IssueCode, is_identifier
from ripplerack.importers.common import (
    Reader,
    ReadError,
    child,
    describe,
    name_schema,
    one_line,
    parse_json,
    strip_suffixes,
    summarize,
    values_note,
    visible,
    with_note,
)
from ripplerack.models import FieldType, Schema, SchemaField
from ripplerack.parser import ErrorCode, RippleRackError

__all__ = ["from_json_schema", "import_json_schema", "parse_json"]

_MAX_DEPTH = 32
_JSON_TYPES = frozenset({"string", "number", "integer", "boolean", "object", "array", "null"})
_PLAIN_TYPES = {
    "integer": FieldType.INTEGER,
    "number": FieldType.FLOAT,
    "boolean": FieldType.BOOLEAN,
}
_STRING_FORMATS = {"date-time": FieldType.TIMESTAMP, "date": FieldType.DATE}
# Saying false for either of these closes an object: no other fields exist. A RippleRack schema
# cannot say that. The 2019-09 drafts and later use ``unevaluatedProperties`` for it, notably
# next to ``allOf``, where ``additionalProperties`` does not see the members' properties.
_CLOSING_KEYWORDS = ("additionalProperties", "unevaluatedProperties")

# TODO (second phase): this module is still long. The resolver of references (``_Reader._resolve``
# and ``_declared_names``, with the pointer helper ``_is_index``) can move to a module of its own,
# which would make it easier to test and to review. What every importer shares is already in
# ``importers/common.py``.


def _invalid(pointer: str, message: str) -> ReadError:
    """The file is not a well-formed JSON Schema."""
    return ReadError(ErrorCode.INVALID_JSON_SCHEMA, pointer, message)


def _unsupported(pointer: str, message: str, *, degradable: bool = True) -> ReadError:
    """The file is fine, but the construct has no RippleRack equivalent."""
    return ReadError(ErrorCode.UNSUPPORTED_JSON_SCHEMA, pointer, message, degradable=degradable)


@dataclass(frozen=True)
class _Translated:
    """What a property schema says about its field."""

    type: FieldType
    nullable: bool
    description: str


def import_json_schema(
    text: str,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
    select: str | None = None,
) -> ImportResult:
    """Parse the JSON Schema in ``text`` and translate it; ``source`` names it in messages.

    A JSON Schema file describes one schema, so there is nothing to ``select``.
    """
    if select is not None:
        raise ValueError("select does not apply to JSON Schema: a file describes one schema")
    return from_json_schema(
        parse_json(text, source), source=source, name=name, version=version, lenient=lenient
    )


def from_json_schema(
    document: Any,
    *,
    source: str,
    name: str | None = None,
    version: str = "1.0.0",
    lenient: bool = False,
) -> ImportResult:
    """Translate an already parsed JSON Schema into a RippleRack schema.

    ``name`` defaults to the root ``title``, then the last part of ``$id``, then the file
    name in ``source``. Raises :class:`RippleRackError` when the document cannot be imported.
    """
    try:
        return _Reader(document, lenient=lenient).read(source=source, name=name, version=version)
    except RecursionError as exc:  # a document nested beyond what Python can compare or print
        raise RippleRackError(
            f"{source}: cannot import this JSON Schema: it is nested too deeply",
            ErrorCode.INVALID_JSON_SCHEMA,
        ) from exc


class _Reader(Reader):
    """Reads one document; collects every problem and warning before reporting."""

    def __init__(self, root: Any, *, lenient: bool) -> None:
        super().__init__(
            lenient=lenient,
            invalid=ErrorCode.INVALID_JSON_SCHEMA,
            unsupported=ErrorCode.UNSUPPORTED_JSON_SCHEMA,
            subject="JSON Schema",
            unit="properties",
        )
        self._root = root

    def read(self, *, source: str, name: str | None, version: str) -> ImportResult:
        fields = self._fields()
        schema_name = name if name is not None else self._schema_name(source)
        if self._problems:
            self._fail(source)
        try:
            schema = Schema(name=schema_name, version=version, fields=fields)
        except ValidationError as exc:
            raise RippleRackError(
                f"{source}: {summarize(exc)}", ErrorCode.VALIDATION_FAILED
            ) from exc
        return ImportResult(schema=schema, issues=tuple(self._issues))

    # ------------------------------------------------------------------ the fields

    def _fields(self) -> list[SchemaField]:
        try:
            properties, required = self._root_object()
        except ReadError as error:
            error.degradable = False
            self._problems.append(error)
            return []
        required_names = {name for name, _ in required}

        fields: list[SchemaField] = []
        for name, (schema, pointer) in properties.items():
            if not is_identifier(name):
                self._problems.append(
                    _unsupported(
                        pointer,
                        f"property name {name!r} is not a valid field name "
                        "(letters, digits, '_', '.' and '-' only)",
                        degradable=False,
                    )
                )
                continue
            if schema is False:  # a property that must not exist is simply not a field
                continue
            try:
                translated = self._translate(schema, pointer, 0)
            except ReadError as error:
                if not (self._lenient and error.degradable):
                    self._problems.append(error)
                    continue
                self._warn(
                    IssueCode.DEGRADED_TO_JSON,
                    error.pointer,
                    f"{error.message}; field {name!r} imported as json",
                )
                translated = _Translated(FieldType.JSON, False, _own_description(schema))
            fields.append(
                SchemaField(
                    name=name,
                    type=translated.type,
                    nullable=translated.nullable or name not in required_names,
                    description=translated.description,
                )
            )

        for name, pointer in required:
            if name in properties:
                continue
            if not is_identifier(name):
                self._problems.append(
                    _unsupported(
                        pointer,
                        f"required property name {name!r} is not a valid field name "
                        "(letters, digits, '_', '.' and '-' only)",
                        degradable=False,
                    )
                )
            elif self._lenient:
                self._warn(
                    IssueCode.UNDECLARED_REQUIRED,
                    pointer,
                    f"required property {name!r} is not declared in properties; "
                    "imported as a json field",
                )
                fields.append(SchemaField(name=name, type=FieldType.JSON, nullable=False))
            else:
                self._problems.append(
                    _unsupported(
                        pointer, f"required property {name!r} is not declared in properties"
                    )
                )

        if not fields and not self._problems:
            self._problems.append(
                _unsupported("#", "the schema declares no fields to import", degradable=False)
            )
        return fields

    def _root_object(self) -> tuple[dict[str, tuple[Any, str]], list[tuple[str, str]]]:
        """The properties (with their pointers) and required names of the root object."""
        root = self._root
        if isinstance(root, bool):
            raise _unsupported("#", "a boolean schema declares no properties to import")
        if not isinstance(root, dict):
            raise _invalid(
                "#", f"the document must be a JSON object (a schema), found {describe(root)}"
            )

        properties: dict[str, tuple[Any, str]] = {}
        required: dict[str, str] = {}
        parts = self._parts(root, "#", 0, frozenset())
        for part, pointer in parts:
            if "type" in part:
                names = _type_names(part["type"], pointer)
                if "object" not in names:
                    raise _unsupported(
                        child(pointer, "type"),
                        f"the schema has type {names[0]!r}, but only object schemas "
                        "(one record) can be imported",
                    )
            declared = part.get("properties", {})
            if not isinstance(declared, dict):
                raise _invalid(child(pointer, "properties"), "properties must be an object")
            for name, schema in declared.items():
                where = child(pointer, "properties", name)
                if name in properties and properties[name][0] != schema:
                    raise _unsupported(
                        where,
                        f"property {name!r} is declared differently by more than one allOf member",
                    )
                properties.setdefault(name, (schema, where))
            names_required = part.get("required", [])
            if not isinstance(names_required, list) or not all(
                isinstance(item, str) for item in names_required
            ):
                raise _invalid(child(pointer, "required"), "required must be a list of strings")
            for item in names_required:
                required.setdefault(item, child(pointer, "required"))

        for part, pointer in parts:
            self._refuse_lost_fields(part, pointer, set(properties))
        if not properties and not required:
            raise _unsupported(
                "#", "the schema declares no properties, so there are no fields to import"
            )
        return properties, list(required.items())

    def _refuse_lost_fields(self, part: dict[str, Any], pointer: str, declared: set[str]) -> None:
        """Refuse alternatives that declare fields the schema does not: they would be lost.

        ``oneOf``, ``anyOf``, ``then``, ``else`` and ``dependentSchemas`` that only constrain the
        properties the schema declares change nothing, and are ignored like any constraint.
        """
        alternatives: list[tuple[str, str, Any]] = []
        for keyword in ("oneOf", "anyOf"):
            members = part.get(keyword)
            if isinstance(members, list):
                for index, member in enumerate(members):
                    alternatives.append((keyword, child(pointer, keyword, index), member))
        for keyword in ("then", "else"):
            if keyword in part:
                alternatives.append((keyword, child(pointer, keyword), part[keyword]))
        for keyword in ("dependentSchemas", "dependencies"):
            conditions = part.get(keyword)
            if isinstance(conditions, dict):
                for name, member in conditions.items():
                    alternatives.append((keyword, child(pointer, keyword, name), member))
        for keyword, where, alternative in alternatives:
            extra = self._declared_names(alternative, where, 0, frozenset()) - declared
            if extra:
                shown = ", ".join(repr(name) for name in sorted(extra))
                raise _unsupported(
                    where,
                    f"{keyword} declares properties that the schema does not ({shown}), "
                    "so their fields would be lost",
                    degradable=False,
                )

    def _declared_names(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> set[str]:
        """The names a schema declares in ``properties``, through ``$ref`` and ``allOf``."""
        if depth > _MAX_DEPTH or not isinstance(schema, dict):
            return set()
        declared = schema.get("properties")
        names: set[str] = set(declared) if isinstance(declared, dict) else set()
        if "$ref" in schema:
            try:
                target, target_pointer = self._resolve(schema["$ref"], pointer, seen)
            except ReadError:  # a reference that cannot be followed declares nothing we know
                pass
            else:
                reference = schema["$ref"]
                names |= self._declared_names(target, target_pointer, depth + 1, seen | {reference})
        members = schema.get("allOf")
        if isinstance(members, list):
            for index, member in enumerate(members):
                names |= self._declared_names(
                    member, child(pointer, "allOf", index), depth + 1, seen
                )
        return names

    def _parts(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> list[tuple[dict[str, Any], str]]:
        """Expand ``$ref`` and ``allOf`` at the root into the schemas that make it up.

        References and ``allOf`` members come first, the schema's own keywords last, so the
        fields of what is extended precede the new ones.
        """
        if depth > _MAX_DEPTH:
            raise _unsupported(pointer, "the schema is nested too deeply")
        if schema is True:
            return []
        if schema is False:
            raise _unsupported(pointer, "a schema that accepts nothing cannot be imported")
        if not isinstance(schema, dict):
            raise _invalid(
                pointer, f"a schema must be an object or a boolean, found {describe(schema)}"
            )
        self._see(schema, pointer)
        _refuse_dynamic_references(schema, pointer)

        parts: list[tuple[dict[str, Any], str]] = []
        if "$ref" in schema:
            target, target_pointer = self._resolve(schema["$ref"], pointer, seen)
            parts += self._parts(target, target_pointer, depth + 1, seen | {schema["$ref"]})
        if "allOf" in schema:
            members = _members(schema, "allOf", pointer)
            for index, member in enumerate(members):
                parts += self._parts(member, child(pointer, "allOf", index), depth + 1, seen)
        own = {key: value for key, value in schema.items() if key not in ("$ref", "allOf")}
        parts.append((own, pointer))
        return parts

    # ---------------------------------------------------------- one property's schema

    def _translate(self, schema: Any, pointer: str, depth: int) -> _Translated:
        if schema is True:  # accepts anything
            return _Translated(FieldType.JSON, False, "")
        flat = self._flatten(schema, pointer, depth, frozenset())
        description = _description(flat, pointer)
        nullable = _flag(flat, "nullable", pointer)  # the OpenAPI 3.0 extension

        if "type" not in flat and ("oneOf" in flat or "anyOf" in flat):
            union = self._union(flat, pointer, depth)
            return _Translated(union.type, True, description or union.description)

        field_type, allows_null, note = _type_of(flat, pointer)
        return _Translated(field_type, nullable or allows_null, with_note(description, note))

    def _flatten(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> dict[str, Any]:
        """Resolve ``$ref`` and a single-member ``allOf``; keywords next to them win."""
        if depth > _MAX_DEPTH:
            raise _unsupported(pointer, "the schema is nested too deeply")
        if schema is True:
            return {}
        if schema is False:
            raise _unsupported(pointer, "a schema that accepts nothing cannot be imported")
        if not isinstance(schema, dict):
            raise _invalid(
                pointer, f"a schema must be an object or a boolean, found {describe(schema)}"
            )
        self._see(schema, pointer)
        _refuse_dynamic_references(schema, pointer)

        flat: dict[str, Any] = {}
        if "$ref" in schema:
            target, target_pointer = self._resolve(schema["$ref"], pointer, seen)
            flat = self._flatten(target, target_pointer, depth + 1, seen | {schema["$ref"]})
        if "allOf" in schema:
            members = _members(schema, "allOf", pointer)
            if len(members) > 1:
                raise _unsupported(
                    child(pointer, "allOf"),
                    f"allOf with {len(members)} members has no equivalent for a field",
                )
            flat = {
                **flat,
                **self._flatten(members[0], child(pointer, "allOf", 0), depth + 1, seen),
            }
        own = {key: value for key, value in schema.items() if key not in ("$ref", "allOf")}
        return {**flat, **own}

    def _union(self, flat: dict[str, Any], pointer: str, depth: int) -> _Translated:
        """``oneOf``/``anyOf`` of one type and null: the usual way to write an optional value."""
        if "oneOf" in flat and "anyOf" in flat:
            raise _unsupported(pointer, "oneOf together with anyOf has no equivalent type")
        keyword = "oneOf" if "oneOf" in flat else "anyOf"
        alternatives = _members(flat, keyword, pointer)
        others = [(i, alt) for i, alt in enumerate(alternatives) if not _is_null_schema(alt)]
        if len(others) == 1 and len(others) < len(alternatives):
            index, alternative = others[0]
            inner = self._translate(alternative, child(pointer, keyword, index), depth + 1)
            return _Translated(inner.type, True, inner.description)
        raise _unsupported(
            child(pointer, keyword),
            f"{keyword} with {len(alternatives)} alternatives has no equivalent type",
        )

    def _resolve(self, ref: Any, pointer: str, seen: frozenset[str]) -> tuple[Any, str]:
        """Follow a reference that points inside this same document."""
        where = child(pointer, "$ref")
        if not isinstance(ref, str):
            raise _invalid(where, "$ref must be a string")
        if not ref.startswith("#"):
            raise _unsupported(
                where,
                f"$ref {ref!r} points outside this document; only references to this "
                "document (#/...) are supported",
            )
        if ref in seen:
            raise _unsupported(where, f"$ref {ref!r} refers back to itself")
        fragment = unquote(ref[1:])
        if not fragment:
            return self._root, "#"
        if not fragment.startswith("/"):
            raise _unsupported(
                where, f"$ref {ref!r} is not a JSON pointer (anchors are not supported)"
            )

        node = self._root
        for token in fragment[1:].split("/"):
            key = token.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and key in node:
                node = node[key]
            elif _is_index(key, node):
                node = node[int(key)]
            else:
                raise _invalid(where, f"$ref {ref!r} does not point to anything in this document")
        return node, visible(ref)

    # ------------------------------------------------------------------ the report

    def _see(self, schema: dict[str, Any], pointer: str) -> None:
        """Note what a schema we are about to read says that RippleRack cannot keep."""
        for keyword in _CLOSING_KEYWORDS:
            if schema.get(keyword) is False:
                self._warn(
                    IssueCode.ADDITIONAL_PROPERTIES_IGNORED,
                    child(pointer, keyword),
                    f"{keyword}: false is ignored; a RippleRack schema cannot say "
                    "that no other fields exist",
                )

    def _schema_name(self, source: str) -> str:
        """``title``, else the last part of ``$id``, else the file name, else ``schema``."""
        candidates: list[str] = []
        if isinstance(self._root, dict):
            title = self._text(self._root, "title")
            if title:
                candidates.append(title)
            identifier = self._text(self._root, "$id")
            if identifier:
                candidates.append(strip_suffixes(_last_segment(identifier)))
        return name_schema(candidates, source)

    def _text(self, schema: dict[str, Any], key: str) -> str | None:
        value = schema.get(key)
        if value is not None and not isinstance(value, str):
            self._problems.append(_invalid(child("#", key), f"{key} must be a string"))
            return None
        return value


# ---------------------------------------------------------------------- pure helpers


def _type_of(flat: dict[str, Any], pointer: str) -> tuple[FieldType, bool, str]:
    """The field type of a flat schema, whether it allows null, and the note on its values."""
    listed = _listed_values(flat, pointer)
    if "type" in flat:
        names = _type_names(flat["type"], pointer)
        kinds = set(names) - {"null"}
        if {"integer", "number"} <= kinds:
            kinds.discard("integer")  # every integer is a number
        if not kinds:
            raise _unsupported(child(pointer, "type"), "type 'null' on its own has no data type")
        if len(kinds) > 1:
            raise _unsupported(
                child(pointer, "type"), f"type {sorted(kinds)} mixes several types in one field"
            )
        (kind,) = kinds
        field_type = (
            _string_type(flat, pointer)
            if kind == "string"
            else _PLAIN_TYPES.get(kind, FieldType.JSON)
        )
        nullable = "null" in names
    elif listed:
        field_type, nullable = _infer(listed[0], flat, pointer)
    else:
        field_type, nullable = FieldType.JSON, False
    return field_type, nullable, values_note(*listed) if listed else ""


def _listed_values(flat: dict[str, Any], pointer: str) -> tuple[list[Any], str] | tuple[()]:
    """The values ``enum`` or ``const`` allows, with the words that introduce them."""
    if "enum" in flat:
        values = flat["enum"]
        if not isinstance(values, list):
            raise _invalid(child(pointer, "enum"), "enum must be a list")
        return (values, "One of") if values else ()
    if "const" in flat:
        return ([flat["const"]], "Always")
    return ()


def _infer(values: list[Any], flat: dict[str, Any], pointer: str) -> tuple[FieldType, bool]:
    """The type of a field that lists its values but says no ``type``."""
    kinds = {_value_kind(value) for value in values}
    nullable = "null" in kinds
    kinds.discard("null")
    if {"integer", "number"} <= kinds:
        kinds.discard("integer")
    if not kinds:
        raise _unsupported(pointer, "a field whose only value is null has no data type")
    if len(kinds) > 1:
        return FieldType.JSON, nullable
    (kind,) = kinds
    if kind == "string":
        return _string_type(flat, pointer), nullable
    return _PLAIN_TYPES.get(kind, FieldType.JSON), nullable


def _string_type(flat: dict[str, Any], pointer: str) -> FieldType:
    fmt = flat.get("format")
    if fmt is not None and not isinstance(fmt, str):
        raise _invalid(child(pointer, "format"), "format must be a string")
    return _STRING_FORMATS.get(fmt or "", FieldType.STRING)


def _type_names(value: Any, pointer: str) -> list[str]:
    where = child(pointer, "type")
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        names = list(value)
    else:
        raise _invalid(where, "type must be a string or a non-empty list of strings")
    for name in names:
        if name not in _JSON_TYPES:
            raise _invalid(where, f"{name!r} is not a JSON Schema type")
    return names


def _members(schema: dict[str, Any], keyword: str, pointer: str) -> list[Any]:
    members = schema[keyword]
    if not isinstance(members, list) or not members:
        raise _invalid(child(pointer, keyword), f"{keyword} must be a non-empty list")
    return members


def _is_null_schema(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    return schema.get("type") == "null" or (
        "type" not in schema and "const" in schema and schema["const"] is None
    )


def _description(flat: dict[str, Any], pointer: str) -> str:
    """``description`` on one line.

    A ``title`` on a property is not used in its place: it mostly repeats the name of the field.
    """
    value = flat.get("description")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise _invalid(child(pointer, "description"), "description must be a string")
    return one_line(value)


def _own_description(schema: Any) -> str:
    """The same, for a schema that could not be read: keep the text if there is any."""
    value = schema.get("description") if isinstance(schema, dict) else None
    return one_line(value) if isinstance(value, str) else ""


def _flag(flat: dict[str, Any], key: str, pointer: str) -> bool:
    value = flat.get(key, False)
    if not isinstance(value, bool):
        raise _invalid(child(pointer, key), f"{key} must be true or false")
    return value


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):  # before int: True is an int in Python
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "json"


def _refuse_dynamic_references(schema: dict[str, Any], pointer: str) -> None:
    """``$dynamicRef`` and ``$recursiveRef`` depend on where a schema is used: not followed."""
    for keyword in ("$dynamicRef", "$recursiveRef"):
        if keyword in schema:
            raise _unsupported(
                child(pointer, keyword),
                f"{keyword} is not supported; only $ref to this document is followed",
            )


def _is_index(key: str, node: Any) -> bool:
    """Whether ``key`` is a position inside the list ``node`` (``int`` refuses huge numbers)."""
    return (
        isinstance(node, list)
        and key.isascii()
        and key.isdigit()
        and len(key) < 10
        and (int(key) < len(node))
    )


def _last_segment(identifier: str) -> str:
    """The last part of the path of an ``$id``, which is usually but not always a URL."""
    try:
        path = urlparse(identifier).path
    except ValueError:  # for example an unbalanced '[', which looks like an IPv6 address
        path = identifier
    return PurePosixPath(path).name
