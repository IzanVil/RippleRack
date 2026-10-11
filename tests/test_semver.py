from __future__ import annotations

import pytest

from ripplerack.semver import ChangeKind, ChangeLevel, Version, diff_schemas
from tests.conftest import make_schema

BASE = make_schema(
    "1.0.0",
    {"name": "id", "type": "integer"},
    {"name": "email"},
    {"name": "nickname", "nullable": True},
)


def kinds(old_version: str, *fields: dict[str, object]) -> set[ChangeKind]:
    return {c.kind for c in diff_schemas(BASE, make_schema(old_version, *fields)).changes}


class TestVersion:
    def test_parse_and_str_roundtrip(self) -> None:
        assert str(Version.parse("10.2.33")) == "10.2.33"

    @pytest.mark.parametrize("raw", ["1.0", "v1.0.0", "01.0.0", "1.0.0-beta", ""])
    def test_rejects_invalid(self, raw: str) -> None:
        with pytest.raises(ValueError, match="invalid semantic version"):
            Version.parse(raw)

    @pytest.mark.parametrize(
        ("level", "expected"),
        [
            (ChangeLevel.NONE, "1.4.2"),
            (ChangeLevel.PATCH, "1.4.3"),
            (ChangeLevel.MINOR, "1.5.0"),
            (ChangeLevel.MAJOR, "2.0.0"),
        ],
    )
    def test_bump(self, level: ChangeLevel, expected: str) -> None:
        assert str(Version.parse("1.4.2").bump(level)) == expected

    def test_ordering(self) -> None:
        assert Version.parse("1.10.0") > Version.parse("1.9.9")
        assert Version.parse("2.0.0") >= Version.parse("2.0.0")


class TestDiffSchemas:
    def test_identical_schemas_have_no_changes(self) -> None:
        diff = diff_schemas(BASE, BASE)
        assert diff.changes == []
        assert diff.level is ChangeLevel.NONE
        assert diff.suggested_version == "1.0.0"
        assert diff.version_is_consistent

    def test_description_change_is_patch(self) -> None:
        new = make_schema(
            "1.0.1",
            {"name": "id", "type": "integer", "description": "primary key"},
            {"name": "email"},
            {"name": "nickname", "nullable": True},
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.PATCH
        assert [c.kind for c in diff.changes] == [ChangeKind.DESCRIPTION_CHANGED]

    def test_reordering_is_patch(self) -> None:
        new = make_schema(
            "1.0.1",
            {"name": "email"},
            {"name": "id", "type": "integer"},
            {"name": "nickname", "nullable": True},
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.PATCH
        assert [c.kind for c in diff.changes] == [ChangeKind.FIELDS_REORDERED]

    def test_optional_field_added_is_minor(self) -> None:
        new = make_schema(
            "1.1.0", *[f.model_dump() for f in BASE.fields], {"name": "x", "nullable": True}
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MINOR
        assert diff.suggested_version == "1.1.0"
        assert not diff.breaking_changes

    def test_required_field_added_is_major_but_does_not_break_readers(self) -> None:
        new = make_schema("2.0.0", *[f.model_dump() for f in BASE.fields], {"name": "x"})
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MAJOR
        assert diff.reader_breaking_changes == []

    def test_field_removed_is_major_and_breaks_readers(self) -> None:
        new = make_schema(
            "2.0.0", {"name": "id", "type": "integer"}, {"name": "nickname", "nullable": True}
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MAJOR
        [change] = diff.reader_breaking_changes
        assert change.kind is ChangeKind.FIELD_REMOVED
        assert change.field == "email"

    def test_type_change_is_major(self) -> None:
        new = make_schema(
            "2.0.0", {"name": "id"}, {"name": "email"}, {"name": "nickname", "nullable": True}
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MAJOR
        assert [c.kind for c in diff.reader_breaking_changes] == [ChangeKind.TYPE_CHANGED]

    def test_making_field_nullable_is_major(self) -> None:
        new = make_schema(
            "2.0.0",
            {"name": "id", "type": "integer"},
            {"name": "email", "nullable": True},
            {"name": "nickname", "nullable": True},
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MAJOR
        assert diff.reader_breaking_changes[0].field == "email"

    def test_making_field_required_is_minor(self) -> None:
        new = make_schema(
            "1.1.0", {"name": "id", "type": "integer"}, {"name": "email"}, {"name": "nickname"}
        )
        diff = diff_schemas(BASE, new)
        assert diff.level is ChangeLevel.MINOR
        assert diff.reader_breaking_changes == []

    def test_rename_is_remove_plus_add(self) -> None:
        new = make_schema(
            "2.0.0",
            {"name": "id", "type": "integer"},
            {"name": "email_address"},
            {"name": "nickname", "nullable": True},
        )
        changes = {(c.kind, c.field) for c in diff_schemas(BASE, new).changes}
        assert (ChangeKind.FIELD_REMOVED, "email") in changes
        assert (ChangeKind.FIELD_ADDED, "email_address") in changes

    def test_overall_level_is_the_highest(self) -> None:
        new = make_schema(
            "2.0.0",
            {"name": "id", "type": "integer", "description": "pk"},  # patch
            {"name": "nickname", "nullable": True},
            {"name": "extra", "nullable": True},  # minor
        )  # email removed -> major
        diff = diff_schemas(BASE, new)
        assert {c.level for c in diff.changes} == {
            ChangeLevel.PATCH,
            ChangeLevel.MINOR,
            ChangeLevel.MAJOR,
        }
        assert diff.level is ChangeLevel.MAJOR

    @pytest.mark.parametrize(
        ("declared", "consistent"),
        [("1.0.1", False), ("1.9.0", False), ("2.0.0", True), ("3.0.0", True)],
    )
    def test_declared_version_consistency(self, declared: str, consistent: bool) -> None:
        new = make_schema(declared, {"name": "id", "type": "integer"})
        assert diff_schemas(BASE, new).version_is_consistent is consistent

    def test_version_cannot_go_backwards_without_changes(self) -> None:
        older = make_schema("0.9.0", *[f.model_dump() for f in BASE.fields])
        assert not diff_schemas(BASE, older).version_is_consistent
