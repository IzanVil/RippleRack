"""The words that say what changed between two datacenters, as plain text.

Several outputs say the same things (the terminal tables, the Markdown report), so the sentences
are written once here. Nothing is escaped: each output makes the text safe for its own syntax.
"""

from __future__ import annotations

from typing import Any

from ripplerack.diff import AttributeChange, DatacenterDiff
from ripplerack.graph import NodeKind

PARENT_LABELS = {NodeKind.SERVER: "in", NodeKind.SERVICE: "on", NodeKind.PIPELINE: "runs on"}


def diff_counts(result: DatacenterDiff) -> str:
    """How much differs, in one line; ``No differences.`` when nothing does."""
    if not result.has_differences:
        return "No differences."
    return (
        f"{len(result.added)} added · {len(result.removed)} removed · "
        f"{len(result.modified)} modified · {len(result.schema_impacts)} schema change(s) · "
        f"{len(result.broken_consumers)} broken consumer(s)"
    )


def describe_change(change: AttributeChange, *, details: str = "below") -> str:
    """One changed attribute as a line; schema fields and inputs have their own words.

    The schema fields are analysed field by field elsewhere in the output, ``details`` says where.
    """
    if change.attribute == "schema.fields":
        return f"schema.fields: changed (see {details})"
    if (
        change.attribute == "inputs"
        and isinstance(change.before, list)
        and isinstance(change.after, list)
    ):
        return f"inputs: {_describe_inputs_change(change.before, change.after)}"
    before, after = _format_value(change.before), _format_value(change.after)
    return f"{change.attribute}: {before} → {after}"


def _describe_inputs_change(before: list[Any], after: list[Any]) -> str:
    """Summarize how a pipeline's inputs changed, e.g. ``orders: -amount +amount_cents``."""
    old = {item["pipeline"]: item["fields"] for item in before}
    new = {item["pipeline"]: item["fields"] for item in after}
    if len(old) != len(before) or len(new) != len(after):  # same upstream listed twice
        return f"{_format_value(before)} → {_format_value(after)}"
    parts = (_describe_input(upstream, old, new) for upstream in sorted(old.keys() | new.keys()))
    return "; ".join(part for part in parts if part)


def _describe_input(
    upstream: str, old: dict[str, list[str] | None], new: dict[str, list[str] | None]
) -> str:
    """How the input from ``upstream`` changed; nothing when it did not."""
    if upstream not in new:
        return f"-{upstream}"
    if upstream not in old:
        return f"+{upstream}"
    was, now = old[upstream], new[upstream]
    if was == now:
        return ""
    return f"{upstream}: {_describe_fields_change(was, now)}"


def _describe_fields_change(was: list[str] | None, now: list[str] | None) -> str:
    """The fields an input reads, before and after; ``None`` is all the fields of the upstream."""
    if was is None or now is None:
        shown = [", ".join(fields) if fields is not None else "all fields" for fields in (was, now)]
        return " → ".join(shown)
    gone, added = sorted(set(was) - set(now)), sorted(set(now) - set(was))
    return " ".join([*(f"-{field}" for field in gone), *(f"+{field}" for field in added)])


def _format_value(value: object) -> str:
    """A value as a comparison shows it: no float noise, lists joined, empty said so."""
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(_format_input(item) for item in value) or "(none)"
    return str(value) if value != "" else "(empty)"


def _format_input(item: object) -> str:
    if not isinstance(item, dict):
        return str(item)
    fields = item.get("fields")
    if isinstance(fields, list):
        return f"{item.get('pipeline')}({', '.join(fields)})"
    return str(item.get("pipeline"))
