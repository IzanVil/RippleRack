"""Cascading impact analysis.

Given a schema change on a pipeline, walk the dependency graph to find every
affected component, decide which direct consumers actually break (based on the
fields they read) and derive an overall severity.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum

import networkx as nx

from ripplerack.graph import NodeKind
from ripplerack.models import Datacenter, Pipeline, PipelineInput, Schema
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


class NodeStatus(StrEnum):
    """What a change does to a component downstream of it."""

    BROKEN = "broken"  # a consumer that reads a field the change breaks
    AT_RISK = "at_risk"  # fed, directly or not, by a broken consumer
    AFFECTED = "affected"  # reached by the change and nothing more


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

    def statuses(self) -> dict[str, NodeStatus]:
        """What the change does to each component it reaches, by id."""
        broken, at_risk = self.broken_ids, set(self.at_risk)
        return {node.id: _status(node.id, broken, at_risk) for node in self.affected}


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
    return analyze_diff(datacenter, graph, pipeline_id, diff)


def analyze_diff(
    datacenter: Datacenter,
    graph: nx.DiGraph[str],
    pipeline_id: str,
    diff: SchemaDiff,
    *,
    ignore_consumers: Collection[str] = (),
) -> ImpactReport:
    """Compute the impact of an already computed schema ``diff`` of ``pipeline_id``.

    ``datacenter`` and ``graph`` describe the world the consumers live in. Pipelines
    listed in ``ignore_consumers`` are never reported as broken, which is how callers
    exclude consumers that were written against the new schema.
    """
    affected = blast_radius(graph, pipeline_id)

    broken = _broken_consumers(datacenter, pipeline_id, diff, set(ignore_consumers))
    at_risk = _at_risk(graph, {consumer.pipeline for consumer in broken})

    return ImpactReport(
        pipeline=pipeline_id,
        diff=diff,
        affected=affected,
        broken_consumers=broken,
        at_risk=sorted(at_risk),
        severity=_severity(diff, broken, at_risk, graph),
    )


def _broken_consumers(
    datacenter: Datacenter, pipeline_id: str, diff: SchemaDiff, ignored: set[str]
) -> list[BrokenConsumer]:
    """The direct consumers that read a field the change breaks, with the fields."""
    breaking = diff.reader_breaking_changes
    if not breaking:
        return []
    result: list[BrokenConsumer] = []
    for consumer, item in _readers_of(datacenter, pipeline_id, ignored):
        read = _fields_read(item, diff.old)
        hits = [change for change in breaking if change.field in read]
        if hits:
            result.append(BrokenConsumer(consumer.id, _fields_of(hits), hits))
    return result


def _readers_of(
    datacenter: Datacenter, pipeline_id: str, ignored: set[str]
) -> Iterator[tuple[Pipeline, PipelineInput]]:
    """Every input that reads the pipeline, with the pipeline it belongs to; some are ignored."""
    for consumer in datacenter.pipelines:
        if consumer.id in ignored:
            continue
        for item in consumer.inputs:
            if item.pipeline == pipeline_id:
                yield consumer, item


def _at_risk(graph: nx.DiGraph[str], broken_ids: set[str]) -> set[str]:
    """The components downstream of the broken consumers that are not broken themselves."""
    downstream: set[str] = set()
    for consumer in broken_ids:
        downstream.update(nx.descendants(graph, consumer))
    return downstream - broken_ids


def _fields_read(item: PipelineInput, upstream: Schema) -> set[str]:
    """The fields of ``upstream`` that an input reads: all of them unless it lists some."""
    return set(item.fields) if item.fields is not None else set(upstream.field_map())


def _fields_of(changes: list[SchemaChange]) -> list[str]:
    """The fields that some changes are about, sorted."""
    return sorted({change.field for change in changes if change.field is not None})


def _status(node_id: str, broken: set[str], at_risk: set[str]) -> NodeStatus:
    """Broken if the component is a broken consumer, at risk if one feeds it, else affected."""
    if node_id in broken:
        return NodeStatus.BROKEN
    if node_id in at_risk:
        return NodeStatus.AT_RISK
    return NodeStatus.AFFECTED


def _severity(
    diff: SchemaDiff,
    broken: list[BrokenConsumer],
    at_risk: set[str],
    graph: nx.DiGraph[str],
) -> Severity:
    """How serious the change is: none if there is none, low if it is compatible.

    An incompatible change is medium if no consumer reads what it breaks, high if some consumer
    breaks, and critical if that puts another pipeline at risk.
    """
    if diff.level is ChangeLevel.NONE:
        return Severity.NONE
    if diff.level < ChangeLevel.MAJOR:
        return Severity.LOW
    if not broken:
        return Severity.MEDIUM
    cascades = any(graph.nodes[node].get("kind") == NodeKind.PIPELINE for node in at_risk)
    return Severity.CRITICAL if cascades else Severity.HIGH
