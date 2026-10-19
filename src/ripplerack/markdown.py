"""Markdown reports to paste in the comment of a pull request.

``impact_to_markdown`` and ``diff_to_markdown`` turn what the engine found into GitHub-flavoured
Markdown. Like the Mermaid diagram it is meant to be read by people, so it has no envelope and its
wording may change; see ``docs/output-formats.md``.

A comment is not a terminal, so three things are taken care of here:

* Everything that comes from a file is written as code. A datacenter can be called ``@team`` or
  ``</details>``; as code it mentions nobody and cannot open or close anything. A table cell escapes
  its ``|``, and a code span or a fence is one backtick longer than any run of them inside.
* GitHub refuses a comment of more than 65,536 characters. Each list shows ``max_items`` rows; a
  report that is still too long loses its diagrams, then its lists of components and dependencies,
  and is cut at a line as a last resort.
* The diagram draws what the change reaches and the racks and servers that host it, not the whole
  datacenter, which can be much larger than what a reviewer needs to see.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import TypeVar

import networkx as nx

from ripplerack.describe import PARENT_LABELS, describe_change, diff_counts
from ripplerack.diff import ComponentRef, DatacenterDiff
from ripplerack.impact import ImpactReport, NodeStatus, Severity
from ripplerack.mermaid import MermaidHighlight, to_mermaid
from ripplerack.semver import ChangeLevel, SchemaDiff

DEFAULT_MAX_ITEMS = 25
MAX_CHARACTERS = 60_000  # GitHub refuses a comment of more than 65,536
MAX_VALUE = 200  # a longer text from a file is shortened

SEVERITY_LABELS = {
    Severity.NONE: "⚪ NONE",
    Severity.LOW: "🟢 LOW",
    Severity.MEDIUM: "🟡 MEDIUM",
    Severity.HIGH: "🟠 HIGH",
    Severity.CRITICAL: "🔴 CRITICAL",
}
STATUS_LABELS = {
    NodeStatus.BROKEN: "❌ broken",
    NodeStatus.AT_RISK: "⚠️ at risk",
    NodeStatus.AFFECTED: "affected",
}

_ROOM = 200  # left free for the line that closes a report that had to be cut
_SHORTENED = "_This report was shortened to fit in a comment._"
_CUT = "_… the rest of the report does not fit in a comment._"
_NO_BREAKS = "✅ No consumer breaks."

# What is left out, attempt after attempt, until the report fits: (diagrams, lists of components).
_ATTEMPTS = ((True, True), (False, True), (False, False))

_T = TypeVar("_T")
Block = list[str]  # lines that go together; an empty line separates two blocks


@dataclass(frozen=True)
class _Style:
    """What a report includes: how many rows a list shows, whether it draws and lists."""

    max_items: int  # 0 shows every row
    diagram: bool
    details: bool

    def shown(self, items: Sequence[_T]) -> list[_T]:
        """The items that are listed."""
        return list(items) if self.max_items <= 0 else list(items[: self.max_items])

    def hidden(self, items: Sequence[object]) -> int:
        """How many items are not listed."""
        return 0 if self.max_items <= 0 else max(0, len(items) - self.max_items)


# ---------------------------------------------------------------------------- the documents


def impact_to_markdown(
    datacenter_name: str,
    report: ImpactReport,
    graph: nx.DiGraph[str],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    diagram: bool = True,
) -> str:
    """The impact of a schema change on a pipeline, as a Markdown report."""
    return _fit(
        lambda style: _impact_blocks(datacenter_name, report, graph, style), max_items, diagram
    )


def diff_to_markdown(
    result: DatacenterDiff,
    graph: nx.DiGraph[str],
    *,
    max_items: int = DEFAULT_MAX_ITEMS,
    diagram: bool = True,
) -> str:
    """What differs between two datacenters, as a Markdown report.

    ``graph`` is the graph of the head datacenter, which is where the impact is measured.
    """
    return _fit(lambda style: _diff_blocks(result, graph, style), max_items, diagram)


def _impact_blocks(
    name: str, report: ImpactReport, graph: nx.DiGraph[str], style: _Style
) -> list[Block]:
    blocks = [[_heading(report.severity)]]
    if not report.diff.changes:
        return [*blocks, [f"No schema changes detected in {_code(report.pipeline)}."]]
    blocks.append([_impact_line(name, report)])
    blocks += _schema_blocks(report.diff, style)
    blocks += _consumer_blocks(report, style)
    blocks += _downstream_blocks(report, graph, style)
    return blocks


def _diff_blocks(result: DatacenterDiff, graph: nx.DiGraph[str], style: _Style) -> list[Block]:
    counts = diff_counts(result)
    blocks = [
        [_heading(result.severity)],
        [f"{_code(result.base_name)} → {_code(result.head_name)} · {counts}"],
    ]
    if result.metadata:
        blocks.append([f"- datacenter {_code(describe_change(c))}" for c in result.metadata])
    for report in result.schema_impacts:
        blocks += _schema_section(report, graph, style)
    blocks += _removed_blocks(result, style)
    blocks += _warning_blocks(result, style)
    blocks += _hint_blocks(result, style)
    if style.details:
        blocks += _component_blocks(result, style)
        blocks += _dependency_blocks(result, style)
    return blocks


def _heading(severity: Severity) -> str:
    return f"## RippleRack · {SEVERITY_LABELS[severity]}"


# ------------------------------------------------------------------------------ the sizes


def _fit(build: Callable[[_Style], list[Block]], max_items: int, diagram: bool) -> str:
    """The report that ``build`` writes, shortened until it fits in a comment."""
    text = ""
    for with_diagram, with_details in _ATTEMPTS:
        blocks = build(_Style(max_items, diagram and with_diagram, with_details))
        if (diagram and not with_diagram) or not with_details:
            blocks.append([_SHORTENED])
        text = _render(blocks)
        if len(text) <= MAX_CHARACTERS:
            return text
    return _cut(text)


def _cut(text: str) -> str:
    """The lines of ``text`` that fit, then a line that says the rest was left out."""
    kept: list[str] = []
    size = 0
    for line in text.splitlines():
        size += len(line) + 1
        if size > MAX_CHARACTERS - _ROOM:
            break
        kept.append(line)
    return _render([kept, [_CUT]])


def _render(blocks: list[Block]) -> str:
    return "\n".join(_join(blocks)) + "\n"


def _join(blocks: list[Block]) -> Block:
    """The lines of some blocks, with an empty line between two of them."""
    lines: Block = []
    for block in blocks:
        if lines and block:
            lines.append("")
        lines.extend(block)
    return lines


# ------------------------------------------------------------------- a schema and who reads it


def _impact_line(name: str, report: ImpactReport) -> str:
    """What the change reaches, and how much of it breaks or is at risk."""
    sentence = (
        f"Changing {_code(report.pipeline)} in {_code(name)} reaches "
        f"{_count(len(report.affected), 'component')}"
    )
    counts = [
        f"{STATUS_LABELS[status]} {number}"
        for status, number in (
            (NodeStatus.BROKEN, len(report.broken_consumers)),
            (NodeStatus.AT_RISK, len(report.at_risk)),
        )
        if number
    ]
    return f"{sentence}: {' · '.join(counts)}" if counts else f"{sentence}."


def _schema_section(report: ImpactReport, graph: nx.DiGraph[str], style: _Style) -> list[Block]:
    """The schema change of one pipeline, inside a comparison of two datacenters."""
    blocks = [[f"### {SEVERITY_LABELS[report.severity]} · {_code(report.pipeline)}"]]
    blocks += _schema_blocks(report.diff, style)
    blocks += _consumer_blocks(report, style)
    if report.broken_consumers:
        blocks += _diagram_blocks(graph, report, style, collapsed=True)
    return blocks


def _schema_blocks(diff: SchemaDiff, style: _Style) -> list[Block]:
    """The line that says which versions, the warning about the version, the changes."""
    old, new = diff.old, diff.new
    blocks = [
        [
            f"Schema {_code(old.name)} {_code(old.version)} → {_code(new.version)} · "
            f"change: {_level(diff.level)} · suggested version {_code(diff.suggested_version)}"
        ]
    ]
    if not diff.version_is_consistent:
        blocks.append(
            [
                f"⚠️ The declared version {_code(new.version)} is too low for a "
                f"{diff.level} change (expected ≥ {_code(diff.suggested_version)})."
            ]
        )
    changes = sorted(diff.changes, key=lambda change: change.level, reverse=True)
    rows = [
        [_level(c.level), _code(str(c.kind)), _code(c.message, cell=True)]
        for c in style.shown(changes)
    ]
    table = _table(["level", "kind", "detail"], rows)
    return [*blocks, ["**Schema changes**"], *_listing(table, style.hidden(changes))]


def _consumer_blocks(report: ImpactReport, style: _Style) -> list[Block]:
    """The consumers that break and what is at risk; or the news that nothing breaks."""
    if not report.broken_consumers:
        return [[_NO_BREAKS]]
    consumers = sorted(report.broken_consumers, key=lambda consumer: consumer.pipeline)
    rows = [
        [
            _code(consumer.pipeline, cell=True),
            _names(consumer.fields, style, cell=True) or "-",
            _code("; ".join(change.message for change in consumer.changes), cell=True),
        ]
        for consumer in style.shown(consumers)
    ]
    table = _table(["pipeline", "fields", "reason"], rows)
    blocks = [["**Broken consumers**"], *_listing(table, style.hidden(consumers))]
    if report.at_risk:
        at_risk = _names(report.at_risk, style, cell=False)
        blocks.append([f"At risk ({len(report.at_risk)}): {at_risk}"])
    return blocks


def _level(level: ChangeLevel) -> str:
    return f"**{level}**" if level is ChangeLevel.MAJOR else str(level)


# --------------------------------------------------------------------------- what is downstream


def _downstream_blocks(report: ImpactReport, graph: nx.DiGraph[str], style: _Style) -> list[Block]:
    """What the change reaches, and the diagram; open when something breaks, else folded."""
    if not report.affected:
        return []
    statuses = report.statuses()
    rows = [
        [
            STATUS_LABELS[statuses[node.id]],
            _code(node.id, cell=True),
            node.kind,
            str(node.distance),
            _code(" → ".join(node.path), cell=True),
        ]
        for node in style.shown(report.affected)
    ]
    table = _table(["status", "component", "kind", "hops", "path"], rows, right=["hops"])
    listing = _listing(table, style.hidden(report.affected))
    if report.broken_consumers:
        return [["**Downstream components**"], *listing, *_diagram_blocks(graph, report, style)]
    summary = f"Downstream components ({len(report.affected)})"
    return [_details(summary, listing), *_diagram_blocks(graph, report, style, collapsed=True)]


def _diagram_blocks(
    graph: nx.DiGraph[str], report: ImpactReport, style: _Style, *, collapsed: bool = False
) -> list[Block]:
    """The diagram of what the change reaches; none if it is off, a note if it is too large."""
    if not style.diagram:
        return []
    if style.hidden(report.affected):
        reached = _count(len(report.affected), "component")
        return [
            [f"_Diagram left out: the change reaches {reached} (use --max-items 0 to draw it)._"]
        ]
    zone = _induced(graph, _impact_nodes(graph, report))
    drawing = _fence(to_mermaid(zone, MermaidHighlight.from_impact(report)), "mermaid")
    if collapsed:
        return [_details("Diagram of the impact", [drawing])]
    return [["**Diagram of the impact**"], drawing]


def _impact_nodes(graph: nx.DiGraph[str], report: ImpactReport) -> set[str]:
    """The pipeline that changes, what it reaches and the racks and servers that host all that."""
    reached = {report.pipeline, *(node.id for node in report.affected)}
    return reached | {host for node in reached for host in _hosts(graph, node)}


def _hosts(graph: nx.DiGraph[str], node: str) -> Iterator[str]:
    """The server and the rack that a node hangs from, closest first."""
    current = node
    while True:
        host = next(
            (
                upstream
                for upstream in graph.predecessors(current)
                if graph.edges[upstream, current].get("relation") == "hosts"
            ),
            None,
        )
        if host is None:
            return
        yield host
        current = host


def _induced(graph: nx.DiGraph[str], keep: set[str]) -> nx.DiGraph[str]:
    """``graph`` reduced to the nodes in ``keep``, in the order the graph has them.

    ``DiGraph.subgraph`` may walk a set of nodes, and the order of a set of texts changes from one
    run to the next; a diagram that is written in that order would not be the same twice.
    """
    zone: nx.DiGraph[str] = nx.DiGraph(name=graph.graph.get("name", ""))
    for node, data in graph.nodes(data=True):
        if node in keep:
            zone.add_node(node, **data)
    for upstream, downstream, data in graph.edges(data=True):
        if upstream in keep and downstream in keep:
            zone.add_edge(upstream, downstream, **data)
    return zone


# ------------------------------------------------------------------ a comparison of datacenters


def _removed_blocks(result: DatacenterDiff, style: _Style) -> list[Block]:
    items = result.removed_with_dependents
    if not items:
        return []
    rows = [
        [_code(item.id, cell=True), str(item.kind), _names(item.dependents, style, cell=True)]
        for item in style.shown(items)
    ]
    table = _table(["component", "kind", "dependents"], rows)
    return [["**Removed, but still depended on**"], *_listing(table, style.hidden(items))]


def _warning_blocks(result: DatacenterDiff, style: _Style) -> list[Block]:
    if not result.warnings:
        return []
    lines = [f"- ⚠️ {_code(warning.message)}" for warning in style.shown(result.warnings)]
    return [["**Warnings**"], *_listing(lines, style.hidden(result.warnings))]


def _hint_blocks(result: DatacenterDiff, style: _Style) -> list[Block]:
    if not result.possible_renames:
        return []
    lines = [
        f"- {rename.kind} {_code(rename.old)} may have been renamed to {_code(rename.new)}"
        for rename in style.shown(result.possible_renames)
    ]
    return [["**Hints**"], *_listing(lines, style.hidden(result.possible_renames))]


def _component_blocks(result: DatacenterDiff, style: _Style) -> list[Block]:
    """The components that were added, removed and modified, folded."""
    rows = [
        *(_component_row("added", ref) for ref in result.added),
        *(_component_row("removed", ref) for ref in result.removed),
        *(
            [
                "modified",
                str(component.kind),
                _code(component.id, cell=True),
                "<br>".join(
                    _code(describe_change(c, details="above"), cell=True) for c in component.changes
                ),
            ]
            for component in result.modified
        ),
    ]
    if not rows:
        return []
    summary = (
        f"Components: {len(result.added)} added · {len(result.removed)} removed · "
        f"{len(result.modified)} modified"
    )
    table = _table(["change", "kind", "id", "details"], style.shown(rows))
    return [_details(summary, _listing(table, style.hidden(rows)))]


def _component_row(change: str, ref: ComponentRef) -> list[str]:
    where = (
        "" if ref.parent is None else f"{PARENT_LABELS[ref.kind]} {_code(ref.parent, cell=True)}"
    )
    return [change, str(ref.kind), _code(ref.id, cell=True), where]


def _dependency_blocks(result: DatacenterDiff, style: _Style) -> list[Block]:
    """The explicit dependencies that were added, removed and changed, folded."""
    rows = [
        *(
            [word, _code(f"{dep.source} → {dep.target}", cell=True), str(dep.kind)]
            for word, deps in (
                ("added", result.dependencies_added),
                ("removed", result.dependencies_removed),
            )
            for dep in deps
        ),
        *(
            [
                "modified",
                _code(f"{dep.source} → {dep.target}", cell=True),
                f"{dep.before} → {dep.after}",
            ]
            for dep in result.dependencies_modified
        ),
    ]
    if not rows:
        return []
    summary = (
        f"Dependencies: {len(result.dependencies_added)} added · "
        f"{len(result.dependencies_removed)} removed · {len(result.dependencies_modified)} modified"
    )
    table = _table(["change", "dependency", "kind"], style.shown(rows))
    return [_details(summary, _listing(table, style.hidden(rows)))]


# ----------------------------------------------------------------------------- the syntax


def _code(text: str, *, cell: bool = False) -> str:
    """``text`` as an inline code span: one line, not too long, safe in a table cell if asked."""
    one_line = " ".join(text.split()) or " "
    if len(one_line) > MAX_VALUE:
        one_line = one_line[: MAX_VALUE - 1].rstrip() + "…"
    if cell:
        one_line = one_line.replace("|", "\\|")
    longest = max((len(run) for run in re.findall(r"`+", one_line)), default=0)
    ticks = "`" * (longest + 1)
    pad = " " if one_line.startswith("`") or one_line.endswith("`") else ""
    return f"{ticks}{pad}{one_line}{pad}{ticks}"


def _fence(text: str, language: str) -> Block:
    """``text`` in a fenced code block that no line of ``text`` can close."""
    longest = max((len(run) for run in re.findall(r"`{3,}", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return [f"{ticks}{language}", *text.rstrip("\n").split("\n"), ticks]


def _table(
    headers: Sequence[str], rows: Sequence[Sequence[str]], *, right: Sequence[str] = ()
) -> Block:
    divider = ["---:" if header in right else "---" for header in headers]
    return [_row(headers), _row(divider), *(_row(row) for row in rows)]


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _details(summary: str, blocks: list[Block]) -> Block:
    """A folded section. The empty line after the summary lets GitHub read Markdown inside."""
    return ["<details>", f"<summary>{summary}</summary>", "", *_join(blocks), "", "</details>"]


def _listing(lines: Block, hidden: int) -> list[Block]:
    """A table or a list followed by the note that says how many rows were left out."""
    if not hidden:
        return [lines]
    return [lines, [f"_… and {hidden} more (use --max-items 0 to list all)_"]]


def _names(names: Sequence[str], style: _Style, *, cell: bool) -> str:
    """Some names as code, separated by commas; the ones beyond ``max_items`` are counted."""
    text = ", ".join(_code(name, cell=cell) for name in style.shown(names))
    hidden = style.hidden(names)
    return f"{text}, … {hidden} more" if hidden else text


def _count(number: int, word: str) -> str:
    return f"{number} {word}" if number == 1 else f"{number} {word}s"
