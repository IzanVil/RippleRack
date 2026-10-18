"""What an Avro file defines: its named types, found by full name, and the record to import.

A record, an enum or a fixed type is defined once and can then be used by its name, which is
looked up with the namespace rules of Avro. This module registers every type the file defines,
wherever it is, and says which record the file is about.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ripplerack.importers.avro.problems import invalid, listing, unsupported
from ripplerack.importers.common import child, describe

_MAX_DEPTH = 32
RECORDS = ("record", "error")
NAMED_KINDS = (*RECORDS, "enum", "fixed")
HOLDS = {"array": "items", "map": "values"}  # what an array and a map are made of
CALLED = {  # how a kind of type is named in a message
    "record": "a record",
    "error": "an error",
    "enum": "an enum",
    "fixed": "a fixed type",
    "array": "an array",
    "map": "a map",
}


@dataclass(frozen=True)
class Named:
    """A record, an enum or a fixed type defined somewhere in the file."""

    kind: str
    fullname: str
    schema: dict[str, Any]
    namespace: str | None  # the namespace its own members are read in
    pointer: str

    @property
    def name(self) -> str:
        return self.fullname.rpartition(".")[2]


class Types:
    """The records, enums and fixed types that a file defines, found by their full names."""

    def __init__(self, root: Any) -> None:
        self._root = root
        self._named: dict[str, Named] = {}
        self._defined: dict[int, Named] = {}  # by the identity of the object that defines it

    def register(self) -> None:
        """Note every type the file defines, wherever it is: in a field, an array, a union..."""
        self._register(self._root, None, "#", 0)

    def find(self, name: str, namespace: str | None) -> Named | None:
        """The type a name refers to: one without a dot is looked up in the namespace first."""
        if "." not in name and namespace:
            found = self._named.get(f"{namespace}.{name}")
            if found is not None:
                return found
        return self._named.get(name)

    def choose(self, select: str | None) -> Named:
        """The record to import: the one ``select`` names, or else the only one the file holds."""
        records = {full: named for full, named in self._named.items() if named.kind in RECORDS}
        if select is not None:
            return _record_named(select, records)
        return self._only_record(records)

    def _register(self, schema: Any, namespace: str | None, pointer: str, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise unsupported(pointer, "the schema is nested too deeply", degradable=False)
        held: list[tuple[tuple[str | int, ...], Any]]
        if isinstance(schema, list):
            held = [((index,), branch) for index, branch in enumerate(schema)]
        elif isinstance(schema, dict):
            kind = schema.get("type")
            if kind in NAMED_KINDS:
                namespace = self._define(kind, schema, namespace, pointer)
            held = list(_held_by(kind, schema))
        else:
            return  # a name or a primitive: nothing is defined here
        for tokens, inner in held:
            self._register(inner, namespace, child(pointer, *tokens), depth + 1)

    def _define(
        self, kind: str, schema: dict[str, Any], namespace: str | None, pointer: str
    ) -> str | None:
        """Register a named type; returns the namespace its own members are read in."""
        fullname, own = _full_name(kind, schema, namespace, pointer)
        if fullname in self._named:
            raise invalid(child(pointer, "name"), f"{fullname!r} is defined more than once")
        _check_shape(kind, schema, pointer)
        named = Named(kind, fullname, schema, own, pointer)
        self._named[fullname] = named
        self._defined[id(schema)] = named
        return own

    def _only_record(self, records: dict[str, Named]) -> Named:
        """The record at the top of the file: the root, or the one in a list of types."""
        branches = self._root if isinstance(self._root, list) else [self._root]
        top = [
            named
            for branch in branches
            if (named := self._defined.get(id(branch))) is not None and named.kind in RECORDS
        ]
        if len(top) == 1:
            return top[0]
        if top:
            raise unsupported(
                "#",
                f"the file holds several records ({listing(sorted(n.fullname for n in top))}); "
                "choose one with --select",
                degradable=False,
            )
        raise unsupported("#", _no_record_to_import(self._root, records), degradable=False)


def _full_name(
    kind: str, schema: dict[str, Any], namespace: str | None, pointer: str
) -> tuple[str, str | None]:
    """The full name of a type that is defined, and the namespace its own members are read in."""
    name = schema.get("name")
    if not isinstance(name, str) or not name:
        raise invalid(child(pointer, "name"), f"{CALLED[kind]} needs a name")
    if "." in name:  # a full name: a namespace given next to it is ignored
        return name, name.rpartition(".")[0] or None
    own = _namespace_of(schema, namespace, pointer)
    return (f"{own}.{name}" if own else name), own


def _namespace_of(schema: dict[str, Any], enclosing: str | None, pointer: str) -> str | None:
    """The namespace a type is defined in: its own, else that of the type that contains it."""
    declared = schema.get("namespace")
    if declared is None:  # absent, or null: that of the type that contains this one
        declared = enclosing
    elif not isinstance(declared, str):
        raise invalid(child(pointer, "namespace"), "namespace must be a string")
    return declared or None  # the empty namespace is no namespace


def _check_shape(kind: str, schema: dict[str, Any], pointer: str) -> None:
    """Refuse a record whose fields, or an enum whose symbols, are not what Avro says."""
    if kind in RECORDS and not isinstance(schema.get("fields"), list):
        raise invalid(child(pointer, "fields"), "the fields of a record must be a list")
    if kind == "enum":
        symbols = schema.get("symbols")
        if not isinstance(symbols, list) or not all(isinstance(s, str) for s in symbols):
            raise invalid(
                child(pointer, "symbols"), "the symbols of an enum must be a list of strings"
            )


def _held_by(kind: Any, schema: dict[str, Any]) -> Iterator[tuple[tuple[str | int, ...], Any]]:
    """The schemas that a schema holds, each with its place in it: field types, items, values."""
    if kind in RECORDS:
        for index, field in enumerate(schema["fields"]):
            if isinstance(field, dict) and "type" in field:
                yield ("fields", index, "type"), field["type"]
    elif isinstance(kind, str) and kind in HOLDS:
        yield (HOLDS[kind],), schema.get(HOLDS[kind])


def _record_named(select: str, records: dict[str, Named]) -> Named:
    """The record ``select`` names: its full name, or its name alone if no other has it."""
    if select in records:
        return records[select]
    matches = sorted(full for full, named in records.items() if named.name == select)
    if len(matches) == 1:
        return records[matches[0]]
    if matches:
        raise unsupported(
            "#",
            f"several records are called {select!r} ({listing(matches)}); give the full name",
            degradable=False,
        )
    known = f"; its records are {listing(sorted(records))}" if records else ""
    raise unsupported("#", f"the file defines no record called {select!r}{known}", degradable=False)


def _no_record_to_import(root: Any, records: dict[str, Named]) -> str:
    """Why the root is not a record to import, and where to find one if the file defines any."""
    hint = (
        f"; the file defines the records {listing(sorted(records))}: choose one with --select"
        if records
        else ""
    )
    return (
        f"the root is {_kind_of(root)}, but only a record can be imported: its fields "
        f"become the fields of the schema{hint}"
    )


def _kind_of(schema: Any) -> str:
    """What a schema is, for a message about the root."""
    if isinstance(schema, list):
        return "a list of types that holds no record"
    if isinstance(schema, dict):
        schema = schema.get("type")
        if not isinstance(schema, str):
            return "an object without a type"
    return f"the type {schema!r}" if isinstance(schema, str) else describe(schema)
