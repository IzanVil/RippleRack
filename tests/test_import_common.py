"""What every importer shares, tested apart from the formats that use it."""

from __future__ import annotations

import pytest

from ripplerack.importers.common import describe, name_schema


@pytest.mark.parametrize(
    ("candidates", "source", "expected"),
    [
        (["Orders"], "other.json", "orders"),
        (["OrderEvent", "second"], "other.json", "order_event"),  # the first that works wins
        (["!!!", "Orders"], "other.json", "orders"),  # one that makes no name is passed over
        (["", "_"], "orders.avsc", "orders"),  # then the file
        ([], "dir/Customer Data.json", "customer_data"),
        ([], "C:\\Users\\ana\\Order-Lines.SCHEMA.JSON", "order_lines"),
        ([], "events.avsc", "events"),
        (["!!!"], "<stdin>", "schema"),  # standard input has no name to give
        ([], "<stdin>", "schema"),
        ([], "dir/", "schema"),
        ([], ".json", "schema"),
    ],
)
def test_a_schema_is_named_by_the_first_candidate_that_makes_a_name_then_by_its_file(
    candidates: list[str], source: str, expected: str
) -> None:
    assert name_schema(candidates, source) == expected


def test_the_candidates_are_not_changed() -> None:
    candidates = ["Orders"]
    name_schema(candidates, "file.json")
    assert candidates == ["Orders"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "null"),
        (True, "a boolean"),
        (False, "a boolean"),
        (3, "a number"),
        (2.5, "a number"),
        ("text", "a string"),
        ([], "an array"),
        ({}, "an object"),
    ],
)
def test_a_value_is_described_by_the_kind_of_json_it_is(value: object, expected: str) -> None:
    assert describe(value) == expected
