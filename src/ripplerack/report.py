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
import math
from typing import Any

from ripplerack import __version__
from ripplerack.capacity import ResourceUsage
from ripplerack.diff import (
    AttributeChange,
    ComponentChange,
    ComponentRef,
    DatacenterDiff,
    DependencyChange,
    DependencyRef,
    DiffWarning,
    PossibleRename,
    RemovedWithDependents,
)
from ripplerack.flow import FlowReport, PipelineFlow
from ripplerack.impact import AffectedNode, BrokenConsumer, ImpactReport, NodeStatus
from ripplerack.semver import SchemaChange, SchemaDiff
from ripplerack.simulate import SimulationReport

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
    """Serialize ``payload`` as canonical JSON: 2-space indent, ASCII only, trailing newline.

    JSON has no NaN or infinity, and the documents write such a number as ``null``; one that reaches
    this point raises ``ValueError`` instead of producing a document that strict readers refuse.
    """
    return json.dumps(payload, indent=2, ensure_ascii=True, allow_nan=False) + "\n"


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


def diff_to_dict(diff: DatacenterDiff) -> dict[str, Any]:
    """Build the ``diff`` document for ``diff``."""
    return {
        **envelope("diff"),
        "base": {"name": diff.base_name},
        "head": {"name": diff.head_name},
        "severity": str(diff.severity),
        "summary": _diff_summary(diff),
        "metadata": [_attribute_to_dict(change) for change in diff.metadata],
        "components": _components_to_dict(diff),
        "dependencies": _dependencies_to_dict(diff),
        "schemaChanges": [impact_body(report) for report in diff.schema_impacts],
        "removedWithDependents": [
            _removed_with_dependents_to_dict(item) for item in diff.removed_with_dependents
        ],
        "possibleRenames": [_rename_to_dict(rename) for rename in diff.possible_renames],
        "warnings": [_warning_to_dict(warning) for warning in diff.warnings],
    }


def _diff_summary(diff: DatacenterDiff) -> dict[str, int]:
    """The counts at the top of the ``diff`` document."""
    return {
        "added": len(diff.added),
        "removed": len(diff.removed),
        "modified": len(diff.modified),
        "dependenciesAdded": len(diff.dependencies_added),
        "dependenciesRemoved": len(diff.dependencies_removed),
        "dependenciesModified": len(diff.dependencies_modified),
        "schemaChanges": len(diff.schema_impacts),
        "brokenConsumers": len(diff.broken_consumers),
        "warnings": len(diff.warnings),
    }


def _components_to_dict(diff: DatacenterDiff) -> dict[str, Any]:
    """The components added, removed and modified."""
    return {
        "added": [_component_ref_to_dict(ref) for ref in diff.added],
        "removed": [_component_ref_to_dict(ref) for ref in diff.removed],
        "modified": [_component_change_to_dict(change) for change in diff.modified],
    }


def _dependencies_to_dict(diff: DatacenterDiff) -> dict[str, Any]:
    """The explicit dependencies added, removed and modified."""
    return {
        "added": [_dependency_ref_to_dict(dep) for dep in diff.dependencies_added],
        "removed": [_dependency_ref_to_dict(dep) for dep in diff.dependencies_removed],
        "modified": [_dependency_change_to_dict(dep) for dep in diff.dependencies_modified],
    }


def _attribute_to_dict(change: AttributeChange) -> dict[str, Any]:
    return {"attribute": change.attribute, "before": change.before, "after": change.after}


def _component_ref_to_dict(ref: ComponentRef) -> dict[str, Any]:
    return {"id": ref.id, "kind": str(ref.kind), "parent": ref.parent}


def _component_change_to_dict(component: ComponentChange) -> dict[str, Any]:
    return {
        "id": component.id,
        "kind": str(component.kind),
        "changes": [_attribute_to_dict(change) for change in component.changes],
    }


def _dependency_ref_to_dict(dep: DependencyRef) -> dict[str, Any]:
    return {"source": dep.source, "target": dep.target, "kind": str(dep.kind)}


def _dependency_change_to_dict(dep: DependencyChange) -> dict[str, Any]:
    return {
        "source": dep.source,
        "target": dep.target,
        "before": str(dep.before),
        "after": str(dep.after),
    }


def _removed_with_dependents_to_dict(item: RemovedWithDependents) -> dict[str, Any]:
    return {"id": item.id, "kind": str(item.kind), "dependents": item.dependents}


def _rename_to_dict(rename: PossibleRename) -> dict[str, Any]:
    return {"kind": str(rename.kind), "from": rename.old, "to": rename.new}


def _warning_to_dict(warning: DiffWarning) -> dict[str, Any]:
    return {"code": str(warning.code), "message": warning.message}


def impact_body(report: ImpactReport) -> dict[str, Any]:
    """Build the part of an impact document that does not depend on the envelope."""
    statuses = report.statuses()
    return {
        "pipeline": report.pipeline,
        "severity": str(report.severity),
        "schema": schema_diff_to_dict(report.diff),
        "brokenConsumers": [
            _broken_consumer_to_dict(consumer)
            for consumer in sorted(report.broken_consumers, key=lambda c: c.pipeline)
        ],
        "atRisk": sorted(report.at_risk),
        "affected": [_affected_to_dict(node, statuses[node.id]) for node in report.affected],
        "summary": {
            "affected": len(report.affected),
            "broken": len(report.broken_consumers),
            "atRisk": len(report.at_risk),
            "breakingChanges": len(report.diff.breaking_changes),
        },
    }


def _broken_consumer_to_dict(consumer: BrokenConsumer) -> dict[str, Any]:
    return {
        "pipeline": consumer.pipeline,
        "fields": sorted(consumer.fields),
        "changes": [
            {"kind": str(change.kind), "field": change.field}
            for change in sorted(consumer.changes, key=_change_order)
        ],
    }


def _affected_to_dict(node: AffectedNode, status: NodeStatus) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind,
        "distance": node.distance,
        "path": list(node.path),
        "status": str(status),
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


def simulate_to_dict(datacenter_name: str, report: SimulationReport) -> dict[str, Any]:
    """Build the ``simulate`` document for ``report``.

    JSON has no infinity, so a number that is not finite (a load of ``inf``) is written as ``null``.
    """
    return {
        **envelope("simulate"),
        "datacenter": datacenter_name,
        "loadFactor": _finite(report.load_factor),
        "healthy": report.healthy,
        "overloaded": report.overloaded,
        "failed": list(report.failed),
        "unavailable": [_unavailable_to_dict(node) for node in report.unavailable],
        "racks": [
            {"id": rack.id, "power": _usage_to_dict(rack.power), "status": str(rack.status)}
            for rack in report.racks
        ],
        "servers": [
            {
                "id": server.id,
                "rack": server.rack,
                "cpu": _usage_to_dict(server.cpu),
                "memory": _usage_to_dict(server.memory),
                "status": str(server.status),
            }
            for server in report.servers
        ],
        "pipelines": None if report.flow is None else _flow_to_dict(report.flow),
    }


def _finite(value: float | None) -> float | None:
    """``value``, or ``None`` when it is unknown or not a finite number."""
    return None if value is None or not math.isfinite(value) else value


def _usage_to_dict(usage: ResourceUsage) -> dict[str, Any]:
    return {
        "used": _finite(usage.used),
        "capacity": _finite(usage.capacity),
        "ratio": _finite(usage.ratio),
    }


def _unavailable_to_dict(node: AffectedNode) -> dict[str, Any]:
    return {"id": node.id, "kind": node.kind, "distance": node.distance, "path": list(node.path)}


def _flow_to_dict(flow: FlowReport) -> dict[str, Any]:
    named = flow.named_bottleneck
    path = flow.slowest_path
    return {
        "items": [_pipeline_flow_to_dict(item) for item in flow.pipelines],
        "bottleneck": None
        if named is None
        else {
            "id": named.id,
            "utilization": _finite(named.utilization),
            "offered": _finite(named.offered),
            "capacity": _finite(named.capacity),
        },
        "slowestPath": None
        if path is None
        else {"pipelines": list(path.pipelines), "seconds": _finite(path.seconds)},
    }


def _pipeline_flow_to_dict(item: PipelineFlow) -> dict[str, Any]:
    return {
        "id": item.id,
        "offered": _finite(item.offered),
        "processed": _finite(item.processed),
        "capacity": _finite(item.capacity),
        "utilization": _finite(item.utilization),
        "status": None if item.status is None else str(item.status),
        "latency": _finite(item.latency),
    }
