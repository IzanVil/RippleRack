"""JSON serialization of analysis results.

The documents built here are a stable, versioned contract meant for CI and other
third-party tooling; see ``docs/output-formats.md`` for the full reference.

Conventions:

* Every document carries an envelope (``schemaVersion``, ``tool``, ``command``).
* All keys are camelCase. Enumerated *values* are lowercase words or snake_case.
* Lists are sorted deterministically, so equal inputs give byte-identical output.
* Free-text ``message`` fields are for humans and are not part of the contract.
"""

from __future__ import annotations

import json
from typing import Any

from ripplerack import __version__
from ripplerack.impact import ImpactReport
from ripplerack.semver import SchemaChange, SchemaDiff

SCHEMA_VERSION = 1
TOOL_NAME = "ripplerack"


def envelope(command: str) -> dict[str, Any]:
    """Return the keys shared by every JSON document RippleRack emits."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": __version__},
        "command": command,
    }


def dumps(payload: dict[str, Any]) -> str:
    """Serialize ``payload`` as canonical JSON: 2-space indent, ASCII only, trailing newline."""
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def error_to_dict(command: str, code: str, message: str) -> dict[str, Any]:
    """Build the error document written to stderr when ``--format json`` fails."""
    return {**envelope(command), "error": {"code": str(code), "message": message}}


def impact_to_dict(datacenter_name: str, report: ImpactReport) -> dict[str, Any]:
    """Build the ``impact`` document for ``report``."""
    return {
        **envelope("impact"),
        "datacenter": datacenter_name,
        **impact_body(report),
    }


def impact_body(report: ImpactReport) -> dict[str, Any]:
    """Build the part of an impact document that does not depend on the envelope."""
    broken_ids = report.broken_ids
    at_risk_ids = set(report.at_risk)

    def status(node_id: str) -> str:
        if node_id in broken_ids:
            return "broken"
        if node_id in at_risk_ids:
            return "at_risk"
        return "affected"

    return {
        "pipeline": report.pipeline,
        "severity": str(report.severity),
        "schema": schema_diff_to_dict(report.diff),
        "brokenConsumers": [
            {
                "pipeline": consumer.pipeline,
                "fields": sorted(consumer.fields),
                "changes": [
                    {"kind": str(change.kind), "field": change.field}
                    for change in sorted(consumer.changes, key=_change_order)
                ],
            }
            for consumer in sorted(report.broken_consumers, key=lambda c: c.pipeline)
        ],
        "atRisk": sorted(report.at_risk),
        "affected": [
            {
                "id": node.id,
                "kind": node.kind,
                "distance": node.distance,
                "path": list(node.path),
                "status": status(node.id),
            }
            for node in report.affected
        ],
        "summary": {
            "affected": len(report.affected),
            "broken": len(report.broken_consumers),
            "atRisk": len(report.at_risk),
            "breakingChanges": len(report.diff.breaking_changes),
        },
    }


def schema_diff_to_dict(diff: SchemaDiff) -> dict[str, Any]:
    """Serialize a schema comparison; changes are listed major first."""
    return {
        "name": diff.old.name,
        "oldVersion": diff.old.version,
        "newVersion": diff.new.version,
        "level": str(diff.level),
        "suggestedVersion": diff.suggested_version,
        "versionConsistent": diff.version_is_consistent,
        "changes": [
            _change_to_dict(change)
            for change in sorted(diff.changes, key=lambda c: (-int(c.level), *_change_order(c)))
        ],
    }


def _change_to_dict(change: SchemaChange) -> dict[str, Any]:
    return {
        "kind": str(change.kind),
        "level": str(change.level),
        "field": change.field,
        "message": change.message,
        "breaksReaders": change.breaks_readers,
    }


def _change_order(change: SchemaChange) -> tuple[str, str]:
    return (change.field or "", str(change.kind))
