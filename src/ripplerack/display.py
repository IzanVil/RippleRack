"""What the commands print for people: tables, trees and one-line summaries drawn with Rich.

Nothing here decides anything. Every function takes a result that the engine has already
computed and draws it. The JSON documents are built in ``report.py`` and the diagrams in
``mermaid.py``.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from ripplerack.describe import PARENT_LABELS, describe_change, diff_counts
from ripplerack.diff import AttributeChange, ComponentRef, DatacenterDiff
from ripplerack.graph import NodeKind
from ripplerack.impact import ImpactReport, NodeStatus, Severity
from ripplerack.models import Datacenter
from ripplerack.parser import LoadedDatacenter
from ripplerack.semver import ChangeLevel, SchemaDiff
from ripplerack.simulate import SimulationReport, Status

console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

LEVEL_STYLES = {
    ChangeLevel.NONE: "dim",
    ChangeLevel.PATCH: "green",
    ChangeLevel.MINOR: "yellow",
    ChangeLevel.MAJOR: "bold red",
}
SEVERITY_STYLES = {
    Severity.NONE: "dim",
    Severity.LOW: "green",
    Severity.MEDIUM: "yellow",
    Severity.HIGH: "red",
    Severity.CRITICAL: "bold white on red",
}
STATUS_STYLES = {
    Status.OK: "green",
    Status.WARNING: "yellow",
    Status.OVERLOADED: "bold red",
    Status.FAILED: "bold white on red",
}
NODE_MARKERS = {
    NodeStatus.BROKEN: "[bold red]✗[/] ",
    NodeStatus.AT_RISK: "[yellow]![/] ",
    NodeStatus.AFFECTED: "  ",
}


def _table(title: str) -> Table:
    return Table(title=title, title_justify="left")


def _print_severity(severity: Severity) -> None:
    console.print(f"Severity: [{SEVERITY_STYLES[severity]}] {str(severity).upper()} [/]")


# ----------------------------------------------------------------------------- validate


def print_validation(loaded: LoadedDatacenter) -> None:
    """The summary of a datacenter that is valid."""
    datacenter, graph = loaded.datacenter, loaded.graph
    console.print(f"[bold green]✓[/] [bold]{escape(datacenter.name)}[/] is valid")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("racks", str(len(datacenter.racks)))
    table.add_row("servers", str(len(list(datacenter.iter_servers()))))
    table.add_row("services", str(len(list(datacenter.iter_services()))))
    table.add_row("pipelines", str(len(datacenter.pipelines)))
    table.add_row("explicit dependencies", str(len(datacenter.dependencies)))
    table.add_row("graph", f"{graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    console.print(table)


# ------------------------------------------------------------------------------ impact


def print_impact(report: ImpactReport) -> None:
    """The impact of a schema change: the change, who breaks, what is downstream, how bad."""
    console.rule(f"[bold]Impact of changing [cyan]{report.pipeline}[/]")
    _print_schema_summary(report.diff)
    if report.diff.changes:
        console.print(_schema_changes_table(report.diff))
    else:
        console.print("[dim]No schema changes detected.[/]")
    if report.broken_consumers:
        console.print(_broken_consumers_table(report))
    if report.affected:
        console.print(_affected_table(report))
    _print_severity(report.severity)


def _print_schema_summary(diff: SchemaDiff) -> None:
    level_style = LEVEL_STYLES[diff.level]
    console.print(
        f"Schema [bold]{diff.old.name}[/] {diff.old.version} → {diff.new.version}   "
        f"change: [{level_style}]{diff.level}[/]   "
        f"suggested version: [bold]{diff.suggested_version}[/]"
    )
    if not diff.version_is_consistent:
        console.print(
            f"[yellow]⚠ declared version {diff.new.version} is too low for a "
            f"{diff.level} change (expected ≥ {diff.suggested_version})[/]"
        )


def _schema_changes_table(diff: SchemaDiff) -> Table:
    changes = _table("Schema changes")
    changes.add_column("level")
    changes.add_column("kind")
    changes.add_column("detail")
    for change in sorted(diff.changes, key=lambda c: c.level, reverse=True):
        style = LEVEL_STYLES[change.level]
        changes.add_row(f"[{style}]{change.level}[/]", str(change.kind), change.message)
    return changes


def _broken_consumers_table(report: ImpactReport) -> Table:
    broken = _table("Broken consumers")
    broken.add_column("pipeline", style="bold red")
    broken.add_column("fields")
    broken.add_column("reason")
    for consumer in report.broken_consumers:
        broken.add_row(
            consumer.pipeline,
            ", ".join(consumer.fields) or "-",
            "; ".join(change.message for change in consumer.changes),
        )
    return broken


def _affected_table(report: ImpactReport) -> Table:
    affected = _table("Downstream components")
    affected.add_column("component")
    affected.add_column("kind")
    affected.add_column("hops", justify="right")
    affected.add_column("path", style="dim")
    statuses = report.statuses()
    for node in report.affected:
        marker = NODE_MARKERS[statuses[node.id]]
        affected.add_row(marker + node.id, node.kind, str(node.distance), " → ".join(node.path))
    return affected


# -------------------------------------------------------------------------------- diff


def print_diff(result: DatacenterDiff, base: Path, head: Path) -> None:
    """Everything that differs between two datacenter files, section by section."""
    _print_diff_header(result, base, head)
    _print_diff_sections(result)
    _print_diff_notes(result)
    _print_severity(result.severity)


def _print_diff_header(result: DatacenterDiff, base: Path, head: Path) -> None:
    console.rule(f"[bold]Diff[/] {escape(str(base))} → {escape(str(head))}")
    console.print(f"[bold]{escape(result.base_name)}[/] → [bold]{escape(result.head_name)}[/]")
    console.print(_diff_summary(result))
    for change in result.metadata:
        console.print(f"[yellow]~[/] datacenter {_describe_change(change)}")


def _print_diff_sections(result: DatacenterDiff) -> None:
    """The tables: components, dependencies, schema changes and what was removed."""
    if result.added or result.removed or result.modified:
        console.print(_components_table(result))
    if result.dependencies_added or result.dependencies_removed or result.dependencies_modified:
        console.print(_dependencies_table(result))
    for report in result.schema_impacts:
        _print_schema_impact(report)
    if result.removed_with_dependents:
        console.print(_removed_with_dependents_table(result))


def _print_diff_notes(result: DatacenterDiff) -> None:
    """The hints about renames and the warnings, which close the comparison."""
    for rename in result.possible_renames:
        console.print(
            f"[dim]hint: {rename.kind} '{rename.old}' may have been renamed to '{rename.new}'[/]"
        )
    for warning in result.warnings:
        console.print(f"[yellow]⚠ {escape(warning.message)}[/]")


def _diff_summary(result: DatacenterDiff) -> str:
    if not result.has_differences:
        return f"[dim]{diff_counts(result)}[/]"
    return diff_counts(result)


def _components_table(result: DatacenterDiff) -> Table:
    components = _table("Components")
    components.add_column("")
    components.add_column("kind")
    components.add_column("id")
    components.add_column("details")
    for ref in result.added:
        components.add_row("[green]+[/]", str(ref.kind), ref.id, _parent_label(ref))
    for ref in result.removed:
        components.add_row("[red]-[/]", str(ref.kind), ref.id, _parent_label(ref))
    for component in result.modified:
        details = "\n".join(_describe_change(change) for change in component.changes)
        components.add_row("[yellow]~[/]", str(component.kind), component.id, details)
    return components


def _parent_label(ref: ComponentRef) -> str:
    if ref.parent is None:
        return ""
    return f"{PARENT_LABELS[ref.kind]} {ref.parent}"


def _dependencies_table(result: DatacenterDiff) -> Table:
    dependencies = _table("Dependencies")
    dependencies.add_column("")
    dependencies.add_column("dependency")
    dependencies.add_column("kind")
    for dep in result.dependencies_added:
        dependencies.add_row("[green]+[/]", f"{dep.source} → {dep.target}", str(dep.kind))
    for dep in result.dependencies_removed:
        dependencies.add_row("[red]-[/]", f"{dep.source} → {dep.target}", str(dep.kind))
    for changed in result.dependencies_modified:
        dependencies.add_row(
            "[yellow]~[/]",
            f"{changed.source} → {changed.target}",
            f"{changed.before} → {changed.after}",
        )
    return dependencies


def _print_schema_impact(report: ImpactReport) -> None:
    """The schema change of one pipeline, inside a comparison of two datacenters."""
    console.print()
    console.print(f"[bold cyan]{report.pipeline}[/]")
    _print_schema_summary(report.diff)
    console.print(_schema_changes_table(report.diff))
    if report.broken_consumers:
        console.print(_broken_consumers_table(report))
    if report.at_risk:
        console.print(f"[yellow]At risk:[/] {', '.join(report.at_risk)}")


def _removed_with_dependents_table(result: DatacenterDiff) -> Table:
    removed = _table("Removed, but still depended on")
    removed.add_column("component", style="bold")
    removed.add_column("kind")
    removed.add_column("dependents")
    for item in result.removed_with_dependents:
        removed.add_row(item.id, str(item.kind), ", ".join(item.dependents))
    return removed


def _describe_change(change: AttributeChange) -> str:
    """One changed attribute as a line, with its text made safe for Rich markup."""
    return escape(describe_change(change))


# ------------------------------------------------------------------------------ simulate


def print_simulation(report: SimulationReport) -> None:
    """The load on every rack and server, and what the failures took down."""
    console.rule(f"[bold]Simulation[/] (load x{report.load_factor:g})")
    console.print(_racks_table(report))
    console.print(_servers_table(report))
    if report.failed:
        console.print(f"[bold]Failed:[/] {', '.join(report.failed)}")
        if report.unavailable:
            console.print(_unavailable_table(report))
    if report.healthy:
        console.print("[bold green]✓ All components within capacity.[/]")
    elif report.overloaded:
        console.print(f"[bold red]✗ Overloaded:[/] {', '.join(report.overloaded)}")


def _racks_table(report: SimulationReport) -> Table:
    racks = _table("Racks")
    racks.add_column("rack")
    racks.add_column("power (kW)", justify="right")
    racks.add_column("usage", justify="right")
    racks.add_column("status")
    for rack in report.racks:
        racks.add_row(
            rack.id,
            f"{rack.power.used:.1f} / {rack.power.capacity:g}",
            f"{rack.power.ratio:.0%}",
            _status(rack.status),
        )
    return racks


def _servers_table(report: SimulationReport) -> Table:
    servers = _table("Servers")
    servers.add_column("server")
    servers.add_column("rack")
    servers.add_column("cpu (cores)", justify="right")
    servers.add_column("memory (GB)", justify="right")
    servers.add_column("status")
    for server in report.servers:
        servers.add_row(
            server.id,
            server.rack,
            f"{server.cpu.used:g} / {server.cpu.capacity:g} ({server.cpu.ratio:.0%})",
            f"{server.memory.used:g} / {server.memory.capacity:g} ({server.memory.ratio:.0%})",
            _status(server.status),
        )
    return servers


def _unavailable_table(report: SimulationReport) -> Table:
    lost = _table("Unavailable as a consequence")
    lost.add_column("component")
    lost.add_column("kind")
    lost.add_column("via", style="dim")
    for node in report.unavailable:
        lost.add_row(node.id, node.kind, " → ".join(node.path))
    return lost


def _status(status: Status) -> str:
    return f"[{STATUS_STYLES[status]}]{status}[/]"


# --------------------------------------------------------------------------------- graph


def render_tree(loaded: LoadedDatacenter) -> Tree:
    """The datacenter as a tree: infrastructure, pipelines and explicit dependencies."""
    datacenter = loaded.datacenter
    root = Tree(f"[bold]{escape(datacenter.name)}[/]")
    _add_infrastructure(root.add("[bold]infrastructure[/]"), datacenter)
    _add_pipelines(root.add("[bold]pipelines[/]"), datacenter)
    if datacenter.dependencies:
        _add_dependencies(root.add("[bold]dependencies[/]"), datacenter)
    root.add(_graph_summary(loaded))
    return root


def _add_infrastructure(branch: Tree, datacenter: Datacenter) -> None:
    for rack in datacenter.racks:
        rack_node = branch.add(
            f"[magenta]rack[/] {rack.id} [dim]({rack.power_capacity_kw:g} kW)[/]"
        )
        for server in rack.servers:
            server_node = rack_node.add(
                f"[blue]server[/] {server.id} "
                f"[dim]({server.cpu_cores:g} cores, {server.memory_gb:g} GB)[/]"
            )
            for service in server.services:
                server_node.add(f"[green]service[/] {service.id}")


def _add_pipelines(branch: Tree, datacenter: Datacenter) -> None:
    for pipeline in datacenter.pipelines:
        node = branch.add(
            f"[cyan]pipeline[/] {pipeline.id} "
            f"[dim]({pipeline.schema_.name}@{pipeline.schema_.version}, on {pipeline.runs_on})[/]"
        )
        for item in pipeline.inputs:
            fields = f" [dim]{', '.join(item.fields)}[/]" if item.fields else ""
            node.add(f"← {item.pipeline}{fields}")


def _add_dependencies(branch: Tree, datacenter: Datacenter) -> None:
    for dep in datacenter.dependencies:
        branch.add(f"{dep.source} → {dep.target} [dim]({dep.kind})[/]")


def _graph_summary(loaded: LoadedDatacenter) -> str:
    kinds = [data.get("kind") for _, data in loaded.graph.nodes(data=True)]
    counts = ", ".join(f"{kinds.count(kind)} {kind}s" for kind in NodeKind)
    return f"[dim]{counts}, {loaded.graph.number_of_edges()} edges[/]"
