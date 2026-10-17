"""Translate the root object of a JSON Schema, and each of its properties, into fields."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

from ripplerack.importers.base import ImportResult, IssueCode, is_identifier
from ripplerack.importers.common import (
    ReadError,
    child,
    describe,
    name_schema,
    strip_suffixes,
    with_note,
)
from ripplerack.importers.json_schema.field_types import (
    boolean_flag,
    description_of,
    is_null_schema,
    own_description,
    type_names,
    type_of,
)
from ripplerack.importers.json_schema.problems import invalid, unsupported
from ripplerack.importers.json_schema.walker import Walker, members_of
from ripplerack.models import FieldType, SchemaField


@dataclass(frozen=True)
class _Translated:
    """What a property schema says about its field."""

    type: FieldType
    nullable: bool
    description: str


class JsonSchemaReader(Walker):
    """Reads one document; collects every problem and warning before reporting."""

    def read(self, *, source: str, name: str | None, version: str) -> ImportResult:
        fields = self._fields()
        schema_name = name if name is not None else self._schema_name(source)
        return self._finish(source=source, name=schema_name, version=version, fields=fields)

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
                    unsupported(
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
                translated = _Translated(FieldType.JSON, False, own_description(schema))
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
                    unsupported(
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
                    unsupported(
                        pointer, f"required property {name!r} is not declared in properties"
                    )
                )

        if not fields and not self._problems:
            self._problems.append(
                unsupported("#", "the schema declares no fields to import", degradable=False)
            )
        return fields

    def _root_object(self) -> tuple[dict[str, tuple[Any, str]], list[tuple[str, str]]]:
        """The properties (with their pointers) and required names of the root object."""
        root = self._root
        if isinstance(root, bool):
            raise unsupported("#", "a boolean schema declares no properties to import")
        if not isinstance(root, dict):
            raise invalid(
                "#", f"the document must be a JSON object (a schema), found {describe(root)}"
            )

        properties: dict[str, tuple[Any, str]] = {}
        required: dict[str, str] = {}
        parts = self._parts(root, "#", 0, frozenset())
        for part, pointer in parts:
            if "type" in part:
                names = type_names(part["type"], pointer)
                if "object" not in names:
                    raise unsupported(
                        child(pointer, "type"),
                        f"the schema has type {names[0]!r}, but only object schemas "
                        "(one record) can be imported",
                    )
            declared = part.get("properties", {})
            if not isinstance(declared, dict):
                raise invalid(child(pointer, "properties"), "properties must be an object")
            for name, schema in declared.items():
                where = child(pointer, "properties", name)
                if name in properties and properties[name][0] != schema:
                    raise unsupported(
                        where,
                        f"property {name!r} is declared differently by more than one allOf member",
                    )
                properties.setdefault(name, (schema, where))
            names_required = part.get("required", [])
            if not isinstance(names_required, list) or not all(
                isinstance(item, str) for item in names_required
            ):
                raise invalid(child(pointer, "required"), "required must be a list of strings")
            for item in names_required:
                required.setdefault(item, child(pointer, "required"))

        for part, pointer in parts:
            self._refuse_lost_fields(part, pointer, set(properties))
        if not properties and not required:
            raise unsupported(
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
                raise unsupported(
                    where,
                    f"{keyword} declares properties that the schema does not ({shown}), "
                    "so their fields would be lost",
                    degradable=False,
                )

    def _translate(self, schema: Any, pointer: str, depth: int) -> _Translated:
        if schema is True:  # accepts anything
            return _Translated(FieldType.JSON, False, "")
        flat = self._flatten(schema, pointer, depth, frozenset())
        description = description_of(flat, pointer)
        nullable = boolean_flag(flat, "nullable", pointer)  # the OpenAPI 3.0 extension

        if "type" not in flat and ("oneOf" in flat or "anyOf" in flat):
            union = self._union(flat, pointer, depth)
            return _Translated(union.type, True, description or union.description)

        field_type, allows_null, note = type_of(flat, pointer)
        return _Translated(field_type, nullable or allows_null, with_note(description, note))

    def _union(self, flat: dict[str, Any], pointer: str, depth: int) -> _Translated:
        """``oneOf``/``anyOf`` of one type and null: the usual way to write an optional value."""
        if "oneOf" in flat and "anyOf" in flat:
            raise unsupported(pointer, "oneOf together with anyOf has no equivalent type")
        keyword = "oneOf" if "oneOf" in flat else "anyOf"
        alternatives = members_of(flat, keyword, pointer)
        others = [(i, alt) for i, alt in enumerate(alternatives) if not is_null_schema(alt)]
        if len(others) == 1 and len(others) < len(alternatives):
            index, alternative = others[0]
            inner = self._translate(alternative, child(pointer, keyword, index), depth + 1)
            return _Translated(inner.type, True, inner.description)
        raise unsupported(
            child(pointer, keyword),
            f"{keyword} with {len(alternatives)} alternatives has no equivalent type",
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
            self._problems.append(invalid(child("#", key), f"{key} must be a string"))
            return None
        return value


def _last_segment(identifier: str) -> str:
    """The last part of the path of an ``$id``, which is usually but not always a URL."""
    try:
        path = urlparse(identifier).path
    except ValueError:  # for example an unbalanced '[', which looks like an IPv6 address
        path = identifier
    return PurePosixPath(path).name
