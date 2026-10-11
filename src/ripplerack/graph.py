"""Dependency graph construction and export.

Edges always point in the direction an impact propagates: from the component
that *provides* something to the component that *depends* on it. Therefore the
blast radius of a change in ``X`` is simply ``nx.descendants(graph, X)``.

Edge relations:

* ``hosts``  - rack -> server, server -> service
* ``runs``   - service -> pipeline running on it
* ``feeds``  - upstream pipeline -> downstream pipeline
* ``runtime`` / ``data`` / ``network`` - explicit :class:`~ripplerack.models.Dependency`
"""

from __future__ import annotations

import json
from enum import StrEnum

import networkx as nx

from ripplerack.models import Datacenter


class NodeKind(StrEnum):
    RACK = "rack"
    SERVER = "server"
    SERVICE = "service"
    PIPELINE = "pipeline"


def build_graph(datacenter: Datacenter) -> nx.DiGraph[str]:
    """Build the directed impact graph of ``datacenter``."""
    graph: nx.DiGraph[str] = nx.DiGraph(name=datacenter.name)

    for rack in datacenter.racks:
        graph.add_node(rack.id, kind=NodeKind.RACK)
        for server in rack.servers:
            graph.add_node(server.id, kind=NodeKind.SERVER)
            graph.add_edge(rack.id, server.id, relation="hosts")
            for service in server.services:
                graph.add_node(service.id, kind=NodeKind.SERVICE)
                graph.add_edge(server.id, service.id, relation="hosts")

    for pipeline in datacenter.pipelines:
        graph.add_node(
            pipeline.id,
            kind=NodeKind.PIPELINE,
            data_schema_version=pipeline.schema_.version,
        )
        graph.add_edge(pipeline.runs_on, pipeline.id, relation="runs")

    for pipeline in datacenter.pipelines:
        for item in pipeline.inputs:
            graph.add_edge(item.pipeline, pipeline.id, relation="feeds")

    for dep in datacenter.dependencies:
        graph.add_edge(dep.target, dep.source, relation=str(dep.kind))

    return graph


def find_cycles(graph: nx.DiGraph[str]) -> list[list[str]]:
    """Return every simple cycle in ``graph`` (empty when it is a DAG)."""
    return [list(cycle) for cycle in nx.simple_cycles(graph)]


def to_dot(graph: nx.DiGraph[str]) -> str:
    """Render ``graph`` in Graphviz DOT format without extra dependencies."""
    shapes = {
        NodeKind.RACK: "box3d",
        NodeKind.SERVER: "box",
        NodeKind.SERVICE: "ellipse",
        NodeKind.PIPELINE: "cds",
    }
    lines = [f'digraph "{graph.graph.get("name", "ripplerack")}" {{', "  rankdir=LR;"]
    for node, data in graph.nodes(data=True):
        shape = shapes.get(data.get("kind", NodeKind.SERVICE), "ellipse")
        lines.append(f'  "{node}" [shape={shape}];')
    for source, target, data in graph.edges(data=True):
        lines.append(f'  "{source}" -> "{target}" [label="{data.get("relation", "")}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_json(graph: nx.DiGraph[str]) -> str:
    """Serialize ``graph`` as a JSON document with ``nodes`` and ``edges``.

    Attribute names are emitted in camelCase like every other JSON document
    produced by RippleRack (``data_schema_version`` becomes ``dataSchemaVersion``).
    """
    payload = {
        "name": graph.graph.get("name"),
        "nodes": [{"id": node, **_plain(data)} for node, data in graph.nodes(data=True)],
        "edges": [
            {"source": source, "target": target, **_plain(data)}
            for source, target, data in graph.edges(data=True)
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _plain(data: dict[str, object]) -> dict[str, object]:
    return {_camel_case(key): str(value) for key, value in data.items()}


def _camel_case(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)
