"""Semantic diff between two versions of a data schema.

Version levels describe the schema *contract*:

* **major** - incompatible: field removed, field type changed, required field
  made nullable (readers may now get nulls), required field added (existing
  producers and historical records cannot satisfy it).
* **minor** - compatible addition: optional field added, nullable field made
  required (a stronger guarantee for readers).
* **patch** - no structural change: description edited, fields reordered.

Independently, each change records whether it *breaks readers* of the field.
Only removals, type changes and nullability loosening do: a consumer that never
reads a field, or reads a brand new one, is unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from functools import total_ordering

from ripplerack.models import SEMVER_PATTERN, Schema

_SEMVER_RE = re.compile(SEMVER_PATTERN)


class ChangeLevel(IntEnum):
    """Severity of a schema change, ordered so ``max()`` yields the overall level."""

    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3

    def __str__(self) -> str:
        return self.name.lower()


class ChangeKind(StrEnum):
    """Elementary change detected between two schemas."""

    FIELD_ADDED = "field_added"
    FIELD_REMOVED = "field_removed"
    TYPE_CHANGED = "type_changed"
    NULLABILITY_CHANGED = "nullability_changed"
    DESCRIPTION_CHANGED = "description_changed"
    FIELDS_REORDERED = "fields_reordered"


@dataclass(frozen=True)
class SchemaChange:
    """One elementary difference between two schemas."""

    kind: ChangeKind
    level: ChangeLevel
    field: str | None
    message: str
    breaks_readers: bool = False

    @property
    def is_breaking(self) -> bool:
        """Whether the change is incompatible with the previous contract."""
        return self.level is ChangeLevel.MAJOR


@dataclass(frozen=True)
class SchemaDiff:
    """Result of comparing two schemas."""

    old: Schema
    new: Schema
    changes: list[SchemaChange] = field(default_factory=list)

    @property
    def level(self) -> ChangeLevel:
        """Overall change level (the highest among individual changes)."""
        return max((c.level for c in self.changes), default=ChangeLevel.NONE)

    @property
    def breaking_changes(self) -> list[SchemaChange]:
        return [c for c in self.changes if c.is_breaking]

    @property
    def reader_breaking_changes(self) -> list[SchemaChange]:
        """Changes that break consumers reading the affected field."""
        return [c for c in self.changes if c.breaks_readers]

    @property
    def suggested_version(self) -> str:
        """Version that ``new`` should have according to the detected changes."""
        return str(Version.parse(self.old.version).bump(self.level))

    @property
    def version_is_consistent(self) -> bool:
        """Whether ``new.version`` is at least the required bump over ``old.version``."""
        if self.level is ChangeLevel.NONE:
            return Version.parse(self.new.version) >= Version.parse(self.old.version)
        return Version.parse(self.new.version) >= Version.parse(self.suggested_version)


@total_ordering
@dataclass(frozen=True)
class Version:
    """Minimal ``MAJOR.MINOR.PATCH`` semantic version."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> Version:
        match = _SEMVER_RE.match(value.strip())
        if match is None:
            raise ValueError(f"invalid semantic version: {value!r}")
        major, minor, patch = (int(part) for part in match.groups())
        return cls(major, minor, patch)

    def bump(self, level: ChangeLevel) -> Version:
        """Return the next version for a change of the given level."""
        if level is ChangeLevel.MAJOR:
            return Version(self.major + 1, 0, 0)
        if level is ChangeLevel.MINOR:
            return Version(self.major, self.minor + 1, 0)
        if level is ChangeLevel.PATCH:
            return Version(self.major, self.minor, self.patch + 1)
        return self

    def _key(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def diff_schemas(old: Schema, new: Schema) -> SchemaDiff:
    """Compare ``old`` and ``new`` and classify every difference."""
    old_fields = old.field_map()
    new_fields = new.field_map()
    changes: list[SchemaChange] = []

    for name, old_field in old_fields.items():
        new_field = new_fields.get(name)
        if new_field is None:
            changes.append(
                SchemaChange(
                    ChangeKind.FIELD_REMOVED,
                    ChangeLevel.MAJOR,
                    name,
                    f"field '{name}' removed",
                    breaks_readers=True,
                )
            )
            continue

        if old_field.type != new_field.type:
            changes.append(
                SchemaChange(
                    ChangeKind.TYPE_CHANGED,
                    ChangeLevel.MAJOR,
                    name,
                    f"field '{name}' type changed {old_field.type} -> {new_field.type}",
                    breaks_readers=True,
                )
            )

        if old_field.nullable != new_field.nullable:
            loosened = new_field.nullable
            changes.append(
                SchemaChange(
                    ChangeKind.NULLABILITY_CHANGED,
                    ChangeLevel.MAJOR if loosened else ChangeLevel.MINOR,
                    name,
                    f"field '{name}' is now {'nullable' if loosened else 'required'}",
                    breaks_readers=loosened,
                )
            )

        if old_field.description != new_field.description:
            changes.append(
                SchemaChange(
                    ChangeKind.DESCRIPTION_CHANGED,
                    ChangeLevel.PATCH,
                    name,
                    f"field '{name}' description changed",
                )
            )

    for name, new_field in new_fields.items():
        if name in old_fields:
            continue
        required = not new_field.nullable
        changes.append(
            SchemaChange(
                ChangeKind.FIELD_ADDED,
                ChangeLevel.MAJOR if required else ChangeLevel.MINOR,
                name,
                f"{'required' if required else 'optional'} field '{name}' added",
            )
        )

    common_old = [n for n in old_fields if n in new_fields]
    common_new = [n for n in new_fields if n in old_fields]
    if common_old != common_new:
        changes.append(
            SchemaChange(ChangeKind.FIELDS_REORDERED, ChangeLevel.PATCH, None, "fields reordered")
        )

    return SchemaDiff(old=old, new=new, changes=changes)
