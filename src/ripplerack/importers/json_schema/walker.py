"""Walk a JSON Schema document: follow ``$ref`` and ``allOf``, and note what cannot be kept."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from ripplerack.importers.base import IssueCode
from ripplerack.importers.common import Reader, ReadError, child, describe, visible
from ripplerack.importers.json_schema.problems import invalid, unsupported
from ripplerack.parser import ErrorCode

_MAX_DEPTH = 32
# Saying false for either of these closes an object: no other fields exist. A RippleRack schema
# cannot say that. The 2019-09 drafts and later use ``unevaluatedProperties`` for it, notably
# next to ``allOf``, where ``additionalProperties`` does not see the members' properties.
_CLOSING_KEYWORDS = ("additionalProperties", "unevaluatedProperties")


def members_of(schema: dict[str, Any], keyword: str, pointer: str) -> list[Any]:
    """The alternatives under ``oneOf``, ``anyOf`` or ``allOf``: a non-empty list."""
    members = schema[keyword]
    if not isinstance(members, list) or not members:
        raise invalid(child(pointer, keyword), f"{keyword} must be a non-empty list")
    return members


def _refuse_dynamic_references(schema: dict[str, Any], pointer: str) -> None:
    """``$dynamicRef`` and ``$recursiveRef`` depend on where a schema is used: not followed."""
    for keyword in ("$dynamicRef", "$recursiveRef"):
        if keyword in schema:
            raise unsupported(
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


def _own_keywords(schema: dict[str, Any]) -> dict[str, Any]:
    """What a schema says itself, without the ``$ref`` and ``allOf`` that are expanded."""
    return {key: value for key, value in schema.items() if key not in ("$ref", "allOf")}


def _local_fragment(ref: Any, where: str, seen: frozenset[str]) -> str:
    """The JSON pointer a reference to this document names (empty for the document itself)."""
    if not isinstance(ref, str):
        raise invalid(where, "$ref must be a string")
    if not ref.startswith("#"):
        raise unsupported(
            where,
            f"$ref {ref!r} points outside this document; only references to this "
            "document (#/...) are supported",
        )
    if ref in seen:
        raise unsupported(where, f"$ref {ref!r} refers back to itself")
    fragment = unquote(ref[1:])
    if fragment and not fragment.startswith("/"):
        raise unsupported(where, f"$ref {ref!r} is not a JSON pointer (anchors are not supported)")
    return fragment


def _step(node: Any, token: str, ref: str, where: str) -> Any:
    """Follow one token of a JSON pointer into ``node``."""
    key = token.replace("~1", "/").replace("~0", "~")
    if isinstance(node, dict) and key in node:
        return node[key]
    if _is_index(key, node):
        return node[int(key)]
    raise invalid(where, f"$ref {ref!r} does not point to anything in this document")


class Walker(Reader):
    """A reader that knows how to move through the document, and collects what it finds."""

    def __init__(self, root: Any, *, lenient: bool) -> None:
        super().__init__(
            lenient=lenient,
            invalid=ErrorCode.INVALID_JSON_SCHEMA,
            unsupported=ErrorCode.UNSUPPORTED_JSON_SCHEMA,
            subject="JSON Schema",
            unit="properties",
        )
        self._root = root

    def _parts(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> list[tuple[dict[str, Any], str]]:
        """Expand ``$ref`` and ``allOf`` at the root into the schemas that make it up.

        References and ``allOf`` members come first, the schema's own keywords last, so the
        fields of what is extended precede the new ones.
        """
        checked = self._checked(schema, pointer, depth)
        if checked is None:
            return []
        parts: list[tuple[dict[str, Any], str]] = []
        if "$ref" in checked:
            target, target_pointer = self._resolve(checked["$ref"], pointer, seen)
            parts += self._parts(target, target_pointer, depth + 1, seen | {checked["$ref"]})
        if "allOf" in checked:
            members = members_of(checked, "allOf", pointer)
            for index, member in enumerate(members):
                parts += self._parts(member, child(pointer, "allOf", index), depth + 1, seen)
        parts.append((_own_keywords(checked), pointer))
        return parts

    def _flatten(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> dict[str, Any]:
        """Resolve ``$ref`` and a single-member ``allOf``; keywords next to them win."""
        checked = self._checked(schema, pointer, depth)
        if checked is None:
            return {}
        flat: dict[str, Any] = {}
        if "$ref" in checked:
            target, target_pointer = self._resolve(checked["$ref"], pointer, seen)
            flat = self._flatten(target, target_pointer, depth + 1, seen | {checked["$ref"]})
        if "allOf" in checked:
            members = members_of(checked, "allOf", pointer)
            if len(members) > 1:
                raise unsupported(
                    child(pointer, "allOf"),
                    f"allOf with {len(members)} members has no equivalent for a field",
                )
            flat = {
                **flat,
                **self._flatten(members[0], child(pointer, "allOf", 0), depth + 1, seen),
            }
        return {**flat, **_own_keywords(checked)}

    def _checked(self, schema: Any, pointer: str, depth: int) -> dict[str, Any] | None:
        """The schema as an object to read, after noting what it says that cannot be kept.

        ``None`` is for ``true``, which accepts anything and says nothing.
        """
        if depth > _MAX_DEPTH:
            raise unsupported(pointer, "the schema is nested too deeply")
        if schema is True:
            return None
        if schema is False:
            raise unsupported(pointer, "a schema that accepts nothing cannot be imported")
        if not isinstance(schema, dict):
            raise invalid(
                pointer, f"a schema must be an object or a boolean, found {describe(schema)}"
            )
        self._see(schema, pointer)
        _refuse_dynamic_references(schema, pointer)
        return schema

    def _declared_names(
        self, schema: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> set[str]:
        """The names a schema declares in ``properties``, through ``$ref`` and ``allOf``."""
        if depth > _MAX_DEPTH or not isinstance(schema, dict):
            return set()
        declared = schema.get("properties")
        names: set[str] = set(declared) if isinstance(declared, dict) else set()
        if "$ref" in schema:
            names |= self._names_through_reference(schema["$ref"], pointer, depth, seen)
        members = schema.get("allOf")
        if isinstance(members, list):
            for index, member in enumerate(members):
                names |= self._declared_names(
                    member, child(pointer, "allOf", index), depth + 1, seen
                )
        return names

    def _names_through_reference(
        self, reference: Any, pointer: str, depth: int, seen: frozenset[str]
    ) -> set[str]:
        """The names declared behind a ``$ref``; none if it cannot be followed."""
        try:
            target, target_pointer = self._resolve(reference, pointer, seen)
        except ReadError:  # a reference that cannot be followed declares nothing we know
            return set()
        return self._declared_names(target, target_pointer, depth + 1, seen | {reference})

    def _resolve(self, ref: Any, pointer: str, seen: frozenset[str]) -> tuple[Any, str]:
        """Follow a reference that points inside this same document."""
        where = child(pointer, "$ref")
        fragment = _local_fragment(ref, where, seen)
        if not fragment:
            return self._root, "#"
        node = self._root
        for token in fragment[1:].split("/"):
            node = _step(node, token, ref, where)
        return node, visible(ref)

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
