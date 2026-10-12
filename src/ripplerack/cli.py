"""Command line interface for RippleRack."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

from ripplerack import __version__
from ripplerack.diff import (
    AttributeChange,
    ComponentRef,
    DatacenterDiff,
    diff_datacenters,
)
from ripplerack.graph import NodeKind, to_dot, to_json
from ripplerack.impact import ImpactReport, Severity, analyze_schema_change
from ripplerack.mermaid import MermaidHighlight, to_mermaid
from ripplerack.parser import (
    ErrorCode,
    LoadedDatacenter,
    RippleRackError,
    load_datacenter,
    load_schema,
)
from ripplerack.report import diff_to_dict, dumps, error_to_dict, impact_to_dict
from ripplerack.semver import ChangeLevel, SchemaDiff
from ripplerack.simulate import SimulationReport, Status, simulate

app = typer.Typer(
    name="ripplerack",
    help="Simulate datacenters & data pipelines and measure the ripple effect of every change.",
    no_args_is_help=True,
    add_completion=False,
)
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

DatacenterFile = Annotated[
    Path, typer.Argument(help="Datacenter YAML file.", dir_okay=False, show_default=False)
]


class GraphFormat(StrEnum):
    TREE = "tree"
    DOT = "dot"
    JSON = "json"
    MERMAID = "mermaid"


class ImpactFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    MERMAID = "mermaid"


class DiffFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ripplerack {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    """RippleRack: datacenter simulation + data SemVer + impact analysis."""


def _fail(message: str, *, code: ErrorCode, command: str, json_mode: bool = False) -> NoReturn:
    """Report an error and exit with status 1.

    In JSON mode the error is a JSON document on stderr (stdout stays empty);
    otherwise it is a human-readable line. The message is escaped so that text
    that looks like Rich markup, such as ``[abc]`` in a path, is printed verbatim.
    """
    if json_mode:
        typer.echo(dumps(error_to_dict(command, code, message)), err=True, nl=False)
    else:
        err_console.print(f"[bold red]error:[/] {escape(message)}")
    raise typer.Exit(code=1)


def _load(path: Path, *, command: str, json_mode: bool = False) -> LoadedDatacenter:
    try:
        return load_datacenter(path)
    except RippleRackError as exc:
        _fail(str(exc), code=exc.code, command=command, json_mode=json_mode)


@app.command()
def validate(file: DatacenterFile) -> None:
    """Validate a datacenter file and print a summary."""
    loaded = _load(file, command="validate")
    dc = loaded.datacenter
    servers = list(dc.iter_servers())
    services = list(dc.iter_services())
    console.print(f"[bold green]✓[/] [bold]{dc.name}[/] is valid")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("racks", str(len(dc.racks)))
    table.add_row("servers", str(len(servers)))
    table.add_row("services", str(len(services)))
    table.add_row("pipelines", str(len(dc.pipelines)))
    table.add_row("explicit dependencies", str(len(dc.dependencies)))
    table.add_row(
        "graph", f"{loaded.graph.number_of_nodes()} nodes, {loaded.graph.number_of_edges()} edges"
    )
    console.print(table)


@app.command()
def impact(
    file: DatacenterFile,
    pipeline: Annotated[
        str, typer.Option("--pipeline", "-p", help="Pipeline whose schema changes.")
    ],
    schema: Annotated[
        Path, typer.Option("--schema", "-s", help="YAML file with the new schema.", dir_okay=False)
    ],
    output_format: Annotated[
        ImpactFormat,
        typer.Option(
            "--format",
            "-F",
            help="Output format: text, json (documented, versioned) or a mermaid diagram "
            "of the graph with the impact highlighted.",
        ),
    ] = ImpactFormat.TEXT,
    fail_on_breaking: Annotated[
        bool,
        typer.Option("--fail-on-breaking", help="Exit with code 2 if any consumer breaks."),
    ] = False,
) -> None:
    """Compute the cascading impact of a schema change on a pipeline."""
    json_mode = output_format is ImpactFormat.JSON
    loaded = _load(file, command="impact", json_mode=json_mode)
    try:
        new_schema = load_schema(schema)
        report = analyze_schema_change(loaded.datacenter, loaded.graph, pipeline, new_schema)
    except RippleRackError as exc:
        _fail(str(exc), code=exc.code, command="impact", json_mode=json_mode)
    except KeyError:
        _fail(
            f"unknown pipeline '{pipeline}'",
            code=ErrorCode.UNKNOWN_PIPELINE,
            command="impact",
            json_mode=json_mode,
        )

    if json_mode:
        typer.echo(dumps(impact_to_dict(loaded.datacenter.name, report)), nl=False)
    elif output_format is ImpactFormat.MERMAID:
        highlight = MermaidHighlight.from_impact(report)
        typer.echo(to_mermaid(loaded.graph, highlight), nl=False)
    else:
        _print_impact(report)
    if fail_on_breaking and report.broken_consumers:
        raise typer.Exit(code=2)


@app.command()
def diff(
    base: Annotated[
        Path,
        typer.Argument(help="Base datacenter file (before).", dir_okay=False, show_default=False),
    ],
    head: Annotated[
        Path,
        typer.Argument(help="Head datacenter file (after).", dir_okay=False, show_default=False),
    ],
    output_format: Annotated[
        DiffFormat,
        typer.Option("--format", "-F", help="Output format (json is documented and versioned)."),
    ] = DiffFormat.TEXT,
    fail_on_breaking: Annotated[
        bool,
        typer.Option("--fail-on-breaking", help="Exit with code 2 if any consumer breaks."),
    ] = False,
) -> None:
    """Compare two datacenter files: components, schemas and cascading impact."""
    json_mode = output_format is DiffFormat.JSON
    base_loaded = _load(base, command="diff", json_mode=json_mode)
    head_loaded = _load(head, command="diff", json_mode=json_mode)
    result = diff_datacenters(base_loaded, head_loaded)

    if json_mode:
        typer.echo(dumps(diff_to_dict(result)), nl=False)
    else:
        _print_diff(result, base, head)
    if fail_on_breaking and result.broken_consumers:
        raise typer.Exit(code=2)


@app.command("simulate")
def simulate_command(
    file: DatacenterFile,
    load: Annotated[
        float, typer.Option("--load", "-l", min=0.0, help="Multiplier applied to service demand.")
    ] = 1.0,
    fail: Annotated[
        list[str] | None,
        typer.Option("--fail", "-f", help="Component id to take down (repeatable)."),
    ] = None,
) -> None:
    """Simulate capacity under load and the cascade of component failures."""
    loaded = _load(file, command="simulate")
    try:
        report = simulate(loaded.datacenter, loaded.graph, load_factor=load, failures=fail)
    except KeyError as exc:
        err_console.print(f"[bold red]error:[/] unknown component(s): {exc.args[0]}")
        raise typer.Exit(code=1) from exc
    _print_simulation(report)


@app.command()
def graph(
    file: DatacenterFile,
    output_format: Annotated[
        GraphFormat, typer.Option("--format", "-F", help="Output format.")
    ] = GraphFormat.TREE,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write to a file instead of stdout.")
    ] = None,
) -> None:
    """Show or export the dependency graph."""
    loaded = _load(file, command="graph")
    if output_format is GraphFormat.TREE:
        if output is not None:
            err_console.print("[bold red]error:[/] --output requires --format dot, json or mermaid")
            raise typer.Exit(code=1)
        console.print(_render_tree(loaded))
        return

    if output_format is GraphFormat.DOT:
        text = to_dot(loaded.graph)
    elif output_format is GraphFormat.MERMAID:
        text = to_mermaid(loaded.graph)
    else:
        text = to_json(loaded.graph)
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/] graph written to {output}")


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
    changes = Table(title="Schema changes", title_justify="left")
    changes.add_column("level")
    changes.add_column("kind")
    changes.add_column("detail")
    for change in sorted(diff.changes, key=lambda c: c.level, reverse=True):
        style = LEVEL_STYLES[change.level]
        changes.add_row(f"[{style}]{change.level}[/]", str(change.kind), change.message)
    return changes


def _broken_consumers_table(report: ImpactReport) -> Table:
    broken = Table(title="Broken consumers", title_justify="left")
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


def _print_impact(report: ImpactReport) -> None:
    diff = report.diff
    console.rule(f"[bold]Impact of changing [cyan]{report.pipeline}[/]")
    _print_schema_summary(diff)

    if diff.changes:
        console.print(_schema_changes_table(diff))
    else:
        console.print("[dim]No schema changes detected.[/]")

    if report.broken_consumers:
        console.print(_broken_consumers_table(report))

    if report.affected:
        affected = Table(title="Downstream components", title_justify="left")
        affected.add_column("component")
        affected.add_column("kind")
        affected.add_column("hops", justify="right")
        affected.add_column("path", style="dim")
        for node in report.affected:
            marker = (
                "[bold red]✗[/] "
                if node.id in report.broken_ids
                else "[yellow]![/] "
                if node.id in report.at_risk
                else "  "
            )
            affected.add_row(marker + node.id, node.kind, str(node.distance), " → ".join(node.path))
        console.print(affected)

    severity_style = SEVERITY_STYLES[report.severity]
    console.print(f"Severity: [{severity_style}] {str(report.severity).upper()} [/]")


PARENT_LABELS = {NodeKind.SERVER: "in", NodeKind.SERVICE: "on", NodeKind.PIPELINE: "runs on"}


def _print_diff(result: DatacenterDiff, base: Path, head: Path) -> None:
    console.rule(f"[bold]Diff[/] {escape(str(base))} → {escape(str(head))}")
    console.print(f"[bold]{escape(result.base_name)}[/] → [bold]{escape(result.head_name)}[/]")
    if not result.has_differences:
        console.print("[dim]No differences.[/]")
    else:
        console.print(
            f"{len(result.added)} added · {len(result.removed)} removed · "
            f"{len(result.modified)} modified · {len(result.schema_impacts)} schema change(s) · "
            f"{len(result.broken_consumers)} broken consumer(s)"
        )

    for change in result.metadata:
        console.print(f"[yellow]~[/] datacenter {_describe_change(change)}")

    if result.added or result.removed or result.modified:
        components = Table(title="Components", title_justify="left")
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
        console.print(components)

    if result.dependencies_added or result.dependencies_removed or result.dependencies_modified:
        dependencies = Table(title="Dependencies", title_justify="left")
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
        console.print(dependencies)

    for report in result.schema_impacts:
        console.print()
        console.print(f"[bold cyan]{report.pipeline}[/]")
        _print_schema_summary(report.diff)
        console.print(_schema_changes_table(report.diff))
        if report.broken_consumers:
            console.print(_broken_consumers_table(report))
        if report.at_risk:
            console.print(f"[yellow]At risk:[/] {', '.join(report.at_risk)}")

    if result.removed_with_dependents:
        removed = Table(title="Removed, but still depended on", title_justify="left")
        removed.add_column("component", style="bold")
        removed.add_column("kind")
        removed.add_column("dependents")
        for item in result.removed_with_dependents:
            removed.add_row(item.id, str(item.kind), ", ".join(item.dependents))
        console.print(removed)

    for rename in result.possible_renames:
        console.print(
            f"[dim]hint: {rename.kind} '{rename.old}' may have been renamed to '{rename.new}'[/]"
        )
    for warning in result.warnings:
        console.print(f"[yellow]⚠ {escape(warning.message)}[/]")

    severity_style = SEVERITY_STYLES[result.severity]
    console.print(f"Severity: [{severity_style}] {str(result.severity).upper()} [/]")


def _parent_label(ref: ComponentRef) -> str:
    if ref.parent is None:
        return ""
    return f"{PARENT_LABELS[ref.kind]} {ref.parent}"


def _describe_change(change: AttributeChange) -> str:
    if change.attribute == "schema.fields":
        return "schema.fields: changed (see below)"
    if (
        change.attribute == "inputs"
        and isinstance(change.before, list)
        and isinstance(change.after, list)
    ):
        return escape(f"inputs: {_describe_inputs_change(change.before, change.after)}")
    before, after = _format_value(change.before), _format_value(change.after)
    return escape(f"{change.attribute}: {before} → {after}")


def _describe_inputs_change(before: list[Any], after: list[Any]) -> str:
    """Summarize how a pipeline's inputs changed, e.g. ``orders: -amount +amount_cents``."""
    old = {item["pipeline"]: item["fields"] for item in before}
    new = {item["pipeline"]: item["fields"] for item in after}
    if len(old) != len(before) or len(new) != len(after):  # same upstream listed twice
        return f"{_format_value(before)} → {_format_value(after)}"

    parts: list[str] = []
    for upstream in sorted(old.keys() | new.keys()):
        if upstream not in new:
            parts.append(f"-{upstream}")
        elif upstream not in old:
            parts.append(f"+{upstream}")
        elif old[upstream] != new[upstream]:
            was, now = old[upstream], new[upstream]
            if was is None or now is None:
                shown = [", ".join(f) if f is not None else "all fields" for f in (was, now)]
                parts.append(f"{upstream}: {shown[0]} → {shown[1]}")
            else:
                gone, new_fields = sorted(set(was) - set(now)), sorted(set(now) - set(was))
                deltas = [*(f"-{f}" for f in gone), *(f"+{f}" for f in new_fields)]
                parts.append(f"{upstream}: {' '.join(deltas)}")
    return "; ".join(parts)


def _format_value(value: object) -> str:
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


def _print_simulation(report: SimulationReport) -> None:
    console.rule(f"[bold]Simulation[/] (load x{report.load_factor:g})")

    racks = Table(title="Racks", title_justify="left")
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
    console.print(racks)

    servers = Table(title="Servers", title_justify="left")
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
    console.print(servers)

    if report.failed:
        console.print(f"[bold]Failed:[/] {', '.join(report.failed)}")
        if report.unavailable:
            lost = Table(title="Unavailable as a consequence", title_justify="left")
            lost.add_column("component")
            lost.add_column("kind")
            lost.add_column("via", style="dim")
            for node in report.unavailable:
                lost.add_row(node.id, node.kind, " → ".join(node.path))
            console.print(lost)

    if report.healthy:
        console.print("[bold green]✓ All components within capacity.[/]")
    elif report.overloaded:
        console.print(f"[bold red]✗ Overloaded:[/] {', '.join(report.overloaded)}")


def _status(status: Status) -> str:
    return f"[{STATUS_STYLES[status]}]{status}[/]"


def _render_tree(loaded: LoadedDatacenter) -> Tree:
    dc = loaded.datacenter
    root = Tree(f"[bold]{dc.name}[/]")

    infra = root.add("[bold]infrastructure[/]")
    for rack in dc.racks:
        rack_node = infra.add(f"[magenta]rack[/] {rack.id} [dim]({rack.power_capacity_kw:g} kW)[/]")
        for server in rack.servers:
            server_node = rack_node.add(
                f"[blue]server[/] {server.id} "
                f"[dim]({server.cpu_cores:g} cores, {server.memory_gb:g} GB)[/]"
            )
            for service in server.services:
                server_node.add(f"[green]service[/] {service.id}")

    pipelines = root.add("[bold]pipelines[/]")
    for pipeline in dc.pipelines:
        node = pipelines.add(
            f"[cyan]pipeline[/] {pipeline.id} "
            f"[dim]({pipeline.schema_.name}@{pipeline.schema_.version}, on {pipeline.runs_on})[/]"
        )
        for item in pipeline.inputs:
            fields = f" [dim]{', '.join(item.fields)}[/]" if item.fields else ""
            node.add(f"← {item.pipeline}{fields}")

    if dc.dependencies:
        deps = root.add("[bold]dependencies[/]")
        for dep in dc.dependencies:
            deps.add(f"{dep.source} → {dep.target} [dim]({dep.kind})[/]")

    kinds = [data.get("kind") for _, data in loaded.graph.nodes(data=True)]
    root.add(
        "[dim]"
        + ", ".join(f"{kinds.count(kind)} {kind}s" for kind in NodeKind)
        + f", {loaded.graph.number_of_edges()} edges[/]"
    )
    return root
