"""Cascading impact analysis.

Given a schema change on a pipeline, walk the dependency graph to find every
affected component, decide which direct consumers actually break (based on the
fields they read) and derive an overall severity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

import networkx as nx

from ripplerack.graph import NodeKind
from ripplerack.models import Datacenter, Schema
from ripplerack.semver import ChangeLevel, SchemaChange, SchemaDiff, diff_schemas


class Severity(IntEnum):
    """Overall impact severity, ordered from harmless to critical."""

    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class AffectedNode:
    """A component reachable from the changed node."""

    id: str
    kind: str
    distance: int
    path: list[str]


@dataclass(frozen=True)
class BrokenConsumer:
    """A direct consumer that reads at least one field broken by the change."""

    pipeline: str
    fields: list[str]
    changes: list[SchemaChange]


@dataclass(frozen=True)
class ImpactReport:
    """Full result of an impact analysis."""

    pipeline: str
    diff: SchemaDiff
    affected: list[AffectedNode] = field(default_factory=list)
    broken_consumers: list[BrokenConsumer] = field(default_factory=list)
    at_risk: list[str] = field(default_factory=list)
    severity: Severity = Severity.NONE

    @property
    def has_breaking_changes(self) -> bool:
        return bool(self.diff.breaking_changes)

    @property
    def broken_ids(self) -> set[str]:
        return {consumer.pipeline for consumer in self.broken_consumers}


def blast_radius(graph: nx.DiGraph[str], node: str) -> list[AffectedNode]:
    """Return every node reachable from ``node``, closest first."""
    if node not in graph:
        raise KeyError(node)
    paths: dict[str, list[str]] = nx.single_source_shortest_path(graph, node)
    affected = [
        AffectedNode(
            id=target,
            kind=str(graph.nodes[target].get("kind", "")),
            distance=len(path) - 1,
            path=path,
        )
        for target, path in paths.items()
        if target != node
    ]
    return sorted(affected, key=lambda item: (item.distance, item.id))


def analyze_schema_change(
    datacenter: Datacenter,
    graph: nx.DiGraph[str],
    pipeline_id: str,
    new_schema: Schema,
) -> ImpactReport:
    """Compute the impact of replacing ``pipeline_id``'s schema with ``new_schema``."""
    pipeline = datacenter.pipeline(pipeline_id)
    diff = diff_schemas(pipeline.schema_, new_schema)
    affected = blast_radius(graph, pipeline_id)

    broken = _broken_consumers(datacenter, pipeline_id, diff)
    broken_ids = {consumer.pipeline for consumer in broken}
    at_risk: set[str] = set()
    for consumer in broken_ids:
        at_risk.update(nx.descendants(graph, consumer))
    at_risk -= broken_ids

    return ImpactReport(
        pipeline=pipeline_id,
        diff=diff,
        affected=affected,
        broken_consumers=broken,
        at_risk=sorted(at_risk),
        severity=_severity(diff, broken, at_risk, graph),
    )


def _broken_consumers(
    datacenter: Datacenter, pipeline_id: str, diff: SchemaDiff
) -> list[BrokenConsumer]:
    breaking = diff.reader_breaking_changes
    if not breaking:
        return []

    result: list[BrokenConsumer] = []
    for consumer in datacenter.pipelines:
        for item in consumer.inputs:
            if item.pipeline != pipeline_id:
                continue
            # Without an explicit field list the consumer reads every existing field.
            read = set(item.fields) if item.fields is not None else set(diff.old.field_map())
            hits = [c for c in breaking if c.field in read]
            if hits:
                fields = sorted({c.field for c in hits if c.field is not None})
                result.append(BrokenConsumer(consumer.id, fields, hits))
    return result


def _severity(
    diff: SchemaDiff,
    broken: list[BrokenConsumer],
    at_risk: set[str],
    graph: nx.DiGraph[str],
) -> Severity:
    if diff.level is ChangeLevel.NONE:
        return Severity.NONE
    if diff.level < ChangeLevel.MAJOR:
        return Severity.LOW
    if not broken:
        return Severity.MEDIUM
    cascades = any(graph.nodes[node].get("kind") == NodeKind.PIPELINE for node in at_risk)
    return Severity.CRITICAL if cascades else Severity.HIGH
