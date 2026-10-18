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
from ripplerack.impact import ImpactReport, NodeStatus

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

# The class of a node, and of the arrow that leads to it, by what the change does to it.
_STATUS_CLASSES = {
    NodeStatus.BROKEN: "broken",
    NodeStatus.AT_RISK: "atRisk",
    NodeStatus.AFFECTED: "affected",
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
        statuses = {node: _STATUS_CLASSES[status] for node, status in report.statuses().items()}
        edges = {
            (upstream, downstream): statuses[downstream]
            for node in report.affected
            for upstream, downstream in zip(node.path, node.path[1:], strict=False)
        }
        return cls(report.pipeline, str(report.severity), statuses, edges)


def to_mermaid(graph: nx.DiGraph[str], highlight: MermaidHighlight | None = None) -> str:
    """Render ``graph`` as a Mermaid ``flowchart``, optionally highlighting an impact."""
    return _Flowchart(graph, highlight).render()


class _Flowchart:
    """The lines of a diagram, written in the order Mermaid needs them: nodes, arrows, styles."""

    def __init__(self, graph: nx.DiGraph[str], highlight: MermaidHighlight | None) -> None:
        self._graph = graph
        self._highlight = highlight
        self._ids = _mermaid_ids(graph)
        self._kinds = {node: data.get("kind") for node, data in graph.nodes(data=True)}
        self._children = _hosted(graph)
        self._pipelines = [node for node in graph if self._kinds[node] == NodeKind.PIPELINE]
        self._lines: list[str] = []
        self._members: dict[str, list[str]] = defaultdict(list)  # node ids by class
        self._container_styles: list[str] = []

    def render(self) -> str:
        self._add_header()
        self._add_nodes()
        link_indexes = self._add_links()
        self._add_styles(link_indexes)
        return "\n".join(self._lines) + "\n"

    def _add_header(self) -> None:
        self._lines.append("flowchart LR")
        if name := _single_line(str(self._graph.graph.get("name", ""))):
            self._lines.append(f"  %% {name}")
        if self._highlight is not None:
            source = _single_line(self._highlight.source)
            self._lines.append(f"  %% impact of changing {source}: {self._highlight.severity}")

    def _add_nodes(self) -> None:
        """Racks and servers hold what they host; the pipelines go together in their own group."""
        contained = {node for hosted in self._children.values() for node in hosted}
        for node in self._graph:
            if node not in contained and node not in self._pipelines:
                self._add_node(node, 1)
        if self._pipelines:
            self._lines.append('  subgraph grp_pipelines["pipelines"]')
            for node in self._pipelines:
                self._add_node(node, 2)
            self._lines.append("  end")

    def _add_node(self, node: str, depth: int) -> None:
        """A node, or a ``subgraph`` with everything the node hosts inside it."""
        pad = "  " * depth
        label = _label(node, self._graph.nodes[node])
        if not self._children[node]:
            self._lines.append(f"{pad}{self._ids[node]}{_shape(self._kinds[node], label)}")
            self._members[self._node_class(node)].append(self._ids[node])
            return
        self._lines.append(f'{pad}subgraph {self._ids[node]}["{label}"]')
        for hosted in self._children[node]:
            self._add_node(hosted, depth + 1)
        self._lines.append(f"{pad}end")
        if (style := _STYLES.get(self._node_class(node))) is not None:
            self._container_styles.append(f"  style {self._ids[node]} {style}")

    def _node_class(self, node: str) -> str:
        highlight = self._highlight
        if highlight is not None:
            if node == highlight.source:
                return "changed"
            if node in highlight.statuses:
                return highlight.statuses[node]
        return str(self._kinds[node])

    def _add_links(self) -> dict[str, list[int]]:
        """One arrow per relation that is not containment; says which arrows are highlighted."""
        link_indexes: dict[str, list[int]] = defaultdict(list)
        arrows = [
            (upstream, downstream, str(data.get("relation", "")))
            for upstream, downstream, data in self._graph.edges(data=True)
            if str(data.get("relation", "")) != "hosts"
        ]
        for index, (upstream, downstream, relation) in enumerate(arrows):
            label = f"|{_escape(relation)}|" if relation else ""
            self._lines.append(f"  {self._ids[upstream]} -->{label} {self._ids[downstream]}")
            highlight = self._highlight
            if highlight is not None and (upstream, downstream) in highlight.edges:
                link_indexes[highlight.edges[(upstream, downstream)]].append(index)
        return link_indexes

    def _add_styles(self, link_indexes: dict[str, list[int]]) -> None:
        for name, style in _STYLES.items():
            if name in self._members:
                self._lines.append(f"  classDef {name} {style}")
                self._lines.append(f"  class {','.join(self._members[name])} {name}")
        self._lines.extend(self._container_styles)
        for status, style in _LINK_STYLES.items():
            if status in link_indexes:
                numbers = ",".join(str(i) for i in link_indexes[status])
                self._lines.append(f"  linkStyle {numbers} {style}")


def _hosted(graph: nx.DiGraph[str]) -> dict[str, list[str]]:
    """What each node hosts: the targets of its ``hosts`` arrows, which are not drawn."""
    hosted: dict[str, list[str]] = {node: [] for node in graph}
    for upstream, downstream, data in graph.edges(data=True):
        if data.get("relation") == "hosts":
            hosted[upstream].append(downstream)
    return hosted


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
