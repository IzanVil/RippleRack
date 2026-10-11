"""Mermaid flowchart export of the dependency graph.

Racks and servers become nested ``subgraph`` blocks (so the ``hosts`` edges are implied
by containment and not drawn), services and pipelines become nodes with a distinct
shape, and every other relation is an arrow labelled with its name. Arrows follow the
direction an impact travels, exactly as in the DOT export.

Node ids in the diagram are generated (``svc_kafka``) rather than copied from the
datacenter: ids such as ``end`` or ``a.b`` are valid in a datacenter file but would
break Mermaid. The original id is always the visible label.

The module emits plain text, so it needs no Mermaid library. Paste the output between
``mermaid`` code fences in Markdown, or feed it to ``mmdc``.

Statements are deliberately not terminated with ``;``: Mermaid reads ``#`` followed by
word characters and a ``;`` as an HTML entity, so ``fill:#f00;`` would be corrupted.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx

from ripplerack.graph import NodeKind
from ripplerack.impact import ImpactReport

_ID_PREFIXES: dict[str, str] = {
    NodeKind.RACK: "rack",
    NodeKind.SERVER: "srv",
    NodeKind.SERVICE: "svc",
    NodeKind.PIPELINE: "pl",
}

# One style per node class. A node gets exactly one class, so styles never have to merge.
_STYLES = {
    "rack": "fill:#f3e5f5,stroke:#6a1b9a,color:#4a148c",
    "server": "fill:#e8eaf6,stroke:#283593,color:#1a237e",
    "service": "fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20",
    "pipeline": "fill:#e3f2fd,stroke:#1565c0,color:#0d47a1",
    "changed": "fill:#ede7f6,stroke:#4527a0,stroke-width:4px,color:#311b92",
    "broken": "fill:#ffcdd2,stroke:#c62828,stroke-width:3px,color:#b71c1c",
    "atRisk": "fill:#ffe0b2,stroke:#ef6c00,stroke-width:2px,color:#e65100",
    "affected": "fill:#fff9c4,stroke:#f9a825,color:#5d4037",
}

# Arrow colour by the status of the node the arrow leads to.
_LINK_STYLES = {
    "broken": "stroke:#c62828,stroke-width:3px",
    "atRisk": "stroke:#ef6c00,stroke-width:3px",
    "affected": "stroke:#f9a825,stroke-width:2px",
}


@dataclass(frozen=True)
class MermaidHighlight:
    """The part of a diagram to emphasize: the impact of a change.

    ``edges`` maps each arrow on a shortest impact path to the status of the node it
    leads to. Statuses are ``broken``, ``atRisk`` and ``affected``.
    """

    source: str
    severity: str
    statuses: dict[str, str]
    edges: dict[tuple[str, str], str]

    @classmethod
    def from_impact(cls, report: ImpactReport) -> MermaidHighlight:
        """Highlight everything reachable from the changed pipeline of ``report``."""
        broken, at_risk = report.broken_ids, set(report.at_risk)
        statuses = {
            node.id: "broken"
            if node.id in broken
            else "atRisk"
            if node.id in at_risk
            else "affected"
            for node in report.affected
        }
        edges = {
            (upstream, downstream): statuses[downstream]
            for node in report.affected
            for upstream, downstream in zip(node.path, node.path[1:], strict=False)
        }
        return cls(report.pipeline, str(report.severity), statuses, edges)


def to_mermaid(graph: nx.DiGraph[str], highlight: MermaidHighlight | None = None) -> str:
    """Render ``graph`` as a Mermaid ``flowchart``, optionally highlighting an impact."""
    ids = _mermaid_ids(graph)
    kinds = {node: data.get("kind") for node, data in graph.nodes(data=True)}

    children: dict[str, list[str]] = {node: [] for node in graph}
    contained: set[str] = set()
    for upstream, downstream, data in graph.edges(data=True):
        if data.get("relation") == "hosts":
            children[upstream].append(downstream)
            contained.add(downstream)
    pipelines = [node for node in graph if kinds[node] == NodeKind.PIPELINE]
    top_level = [node for node in graph if node not in contained and node not in pipelines]

    def node_class(node: str) -> str:
        if highlight is not None:
            if node == highlight.source:
                return "changed"
            if node in highlight.statuses:
                return highlight.statuses[node]
        return str(kinds[node])

    lines = ["flowchart LR"]
    if name := _single_line(str(graph.graph.get("name", ""))):
        lines.append(f"  %% {name}")
    if highlight is not None:
        source = _single_line(highlight.source)
        lines.append(f"  %% impact of changing {source}: {highlight.severity}")

    members: dict[str, list[str]] = defaultdict(list)
    container_styles: list[str] = []

    def emit(node: str, depth: int) -> None:
        pad = "  " * depth
        label = _label(node, graph.nodes[node])
        if children[node]:
            lines.append(f'{pad}subgraph {ids[node]}["{label}"]')
            for child in children[node]:
                emit(child, depth + 1)
            lines.append(f"{pad}end")
            style = _STYLES.get(node_class(node))
            if style is not None:
                container_styles.append(f"  style {ids[node]} {style}")
        else:
            lines.append(f"{pad}{ids[node]}{_shape(kinds[node], label)}")
            members[node_class(node)].append(ids[node])

    for node in top_level:
        emit(node, 1)
    if pipelines:
        lines.append('  subgraph grp_pipelines["pipelines"]')
        for node in pipelines:
            emit(node, 2)
        lines.append("  end")

    link_indexes: dict[str, list[int]] = defaultdict(list)
    index = 0
    for upstream, downstream, data in graph.edges(data=True):
        relation = str(data.get("relation", ""))
        if relation == "hosts":
            continue
        label = f"|{_escape(relation)}|" if relation else ""
        lines.append(f"  {ids[upstream]} -->{label} {ids[downstream]}")
        if highlight is not None and (upstream, downstream) in highlight.edges:
            link_indexes[highlight.edges[(upstream, downstream)]].append(index)
        index += 1

    for name, style in _STYLES.items():
        if name in members:
            lines.append(f"  classDef {name} {style}")
            lines.append(f"  class {','.join(members[name])} {name}")
    lines.extend(container_styles)
    for status, style in _LINK_STYLES.items():
        if status in link_indexes:
            numbers = ",".join(str(i) for i in link_indexes[status])
            lines.append(f"  linkStyle {numbers} {style}")
    return "\n".join(lines) + "\n"


def _mermaid_ids(graph: nx.DiGraph[str]) -> dict[str, str]:
    """Give every node a unique id that is always safe in Mermaid."""
    ids: dict[str, str] = {}
    used: set[str] = set()
    for node, data in graph.nodes(data=True):
        prefix = _ID_PREFIXES.get(str(data.get("kind", "")), "node")
        base = f"{prefix}_{re.sub(r'[^A-Za-z0-9_]', '_', node)}"
        candidate, counter = base, 2
        while candidate in used:
            candidate, counter = f"{base}_{counter}", counter + 1
        used.add(candidate)
        ids[node] = candidate
    return ids


def _label(node: str, data: dict[str, object]) -> str:
    version = data.get("data_schema_version")
    if version is None:
        return _escape(node)
    return f"{_escape(node)}<br/>schema {_escape(str(version))}"


def _shape(kind: object, label: str) -> str:
    if kind == NodeKind.SERVICE:
        return f'("{label}")'
    if kind == NodeKind.PIPELINE:
        return f'{{{{"{label}"}}}}'
    return f'["{label}"]'


def _escape(text: str) -> str:
    """Escape the characters that would end a quoted label or start HTML."""
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def _single_line(text: str) -> str:
    return " ".join(text.split())
