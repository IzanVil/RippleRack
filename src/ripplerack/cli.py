"""Command line interface for RippleRack.

Each command loads what it is given, asks the engine, and hands the result to ``display`` for
people, to ``report`` for the JSON documents or to ``mermaid`` for a diagram.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated, NoReturn

import networkx as nx
import typer
from rich.markup import escape

from ripplerack import __version__
from ripplerack.diff import diff_datacenters
from ripplerack.display import (
    console,
    err_console,
    print_diff,
    print_impact,
    print_simulation,
    print_validation,
    render_tree,
)
from ripplerack.graph import to_dot, to_json
from ripplerack.impact import ImpactReport, analyze_schema_change
from ripplerack.importers import (
    IMPORTERS,
    SELECTABLE,
    STDIN,
    ImportResult,
    SourceFormat,
    is_identifier,
    is_version,
    read_text,
    render_schema_yaml,
    source_label,
)
from ripplerack.mermaid import MermaidHighlight, to_mermaid
from ripplerack.parser import (
    ErrorCode,
    LoadedDatacenter,
    RippleRackError,
    load_datacenter,
    load_schema,
)
from ripplerack.report import diff_to_dict, dumps, error_to_dict, impact_to_dict
from ripplerack.simulate import simulate

app = typer.Typer(
    name="ripplerack",
    help="Simulate datacenters & data pipelines and measure the ripple effect of every change.",
    no_args_is_help=True,
    add_completion=False,
)

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


# How each format that is not the tree turns the graph into text.
GRAPH_EXPORTERS: dict[GraphFormat, Callable[[nx.DiGraph[str]], str]] = {
    GraphFormat.DOT: to_dot,
    GraphFormat.JSON: to_json,
    GraphFormat.MERMAID: to_mermaid,
}


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
    print_validation(_load(file, command="validate"))


def _impact_report(
    loaded: LoadedDatacenter, pipeline: str, schema: Path, *, json_mode: bool
) -> ImpactReport:
    """The impact of the schema in the file ``schema`` on ``pipeline``; a failure ends the run."""
    try:
        new_schema = load_schema(schema)
        return analyze_schema_change(loaded.datacenter, loaded.graph, pipeline, new_schema)
    except RippleRackError as exc:
        _fail(str(exc), code=exc.code, command="impact", json_mode=json_mode)
    except KeyError:
        _fail(
            f"unknown pipeline '{pipeline}'",
            code=ErrorCode.UNKNOWN_PIPELINE,
            command="impact",
            json_mode=json_mode,
        )


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
    report = _impact_report(loaded, pipeline, schema, json_mode=json_mode)
    if json_mode:
        typer.echo(dumps(impact_to_dict(loaded.datacenter.name, report)), nl=False)
    elif output_format is ImpactFormat.MERMAID:
        highlight = MermaidHighlight.from_impact(report)
        typer.echo(to_mermaid(loaded.graph, highlight), nl=False)
    else:
        print_impact(report)
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
        print_diff(result, base, head)
    if fail_on_breaking and result.broken_consumers:
        raise typer.Exit(code=2)


# ------------------------------------------------------------------------------ import


def _check_schema_name(value: str | None) -> str | None:
    if value is not None and not is_identifier(value):
        raise typer.BadParameter("use only letters, digits, '_', '.' and '-'")
    return value


def _check_schema_version(value: str) -> str:
    if not is_version(value):
        raise typer.BadParameter("expected MAJOR.MINOR.PATCH, for example 1.0.0")
    return value


def _check_select(select: str | None, source_format: SourceFormat) -> None:
    """``--select`` chooses among the schemas of a file, so it needs a format that has several."""
    if select is not None and source_format not in SELECTABLE:
        raise typer.BadParameter(
            f"a {source_format.value} file describes one schema, so there is nothing to select",
            param_hint="'--select'",
        )


def _check_output(output: Path, source: Path, *, force: bool) -> None:
    """Refuse to overwrite the input, or any existing file unless ``--force`` is given."""
    if source != STDIN and output.resolve() == source.resolve():
        raise RippleRackError(
            f"refusing to overwrite the input file {output}", ErrorCode.OUTPUT_EXISTS
        )
    if output.exists() and not force:
        raise RippleRackError(
            f"{output} already exists; use --force to overwrite it", ErrorCode.OUTPUT_EXISTS
        )


def _write_schema(target: Path, text: str) -> None:
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise RippleRackError(f"cannot write {target}: {exc}", ErrorCode.IO_ERROR) from exc


def _report_import(result: ImportResult, text: str, target: Path | None) -> None:
    """The warnings on standard error, then the schema on standard output or a summary line."""
    for issue in result.issues:
        typer.secho(str(issue), err=True, fg=typer.colors.YELLOW)
    if target is None:
        typer.echo(text, nl=False)
        return
    schema = result.schema
    console.print(
        f"[green]✓[/] schema [bold]{escape(schema.name)}[/] {schema.version} "
        f"({len(schema.fields)} fields) written to {escape(str(target))}"
    )


@app.command("import")
def import_command(
    file: Annotated[
        Path,
        typer.Argument(
            help="File to import; - reads standard input.",
            allow_dash=True,
            dir_okay=False,
            show_default=False,
        ),
    ],
    source_format: Annotated[
        SourceFormat, typer.Option("--from", help="Format of FILE.", show_default=False)
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            allow_dash=True,
            dir_okay=False,
            help="Write the schema to this file instead of standard output (- is standard output).",
        ),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            callback=_check_schema_name,
            help="Name of the schema. Default: the title or $id of a JSON Schema, the name "
            "of an Avro record, then the file name.",
            show_default=False,
        ),
    ] = None,
    version: Annotated[
        str,
        typer.Option(
            "--version",
            callback=_check_schema_version,
            help="Version to give the schema; the source has none.",
        ),
    ] = "1.0.0",
    select: Annotated[
        str | None,
        typer.Option(
            "--select",
            help="Avro: the record to import when the file defines several, by name or full name.",
            show_default=False,
        ),
    ] = None,
    lenient: Annotated[
        bool,
        typer.Option(
            "--lenient",
            help="Import what has no equivalent as json fields, with a warning, "
            "instead of failing.",
        ),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite the output file if it exists.")
    ] = False,
) -> None:
    """Import a schema from another format and write it as RippleRack YAML.

    The result is a schema file: `impact --schema` reads it as is, and under a pipeline's
    `schema:` key it describes what the pipeline produces. Warnings go to standard error.
    """
    _check_select(select, source_format)
    target = None if output is None or output == STDIN else output
    try:
        if target is not None:
            _check_output(target, file, force=force)
        result = IMPORTERS[source_format](
            read_text(file),
            source=source_label(file),
            name=name,
            version=version,
            lenient=lenient,
            select=select,
        )
        text = render_schema_yaml(result.schema)
        if target is not None:
            _write_schema(target, text)
    except RippleRackError as exc:
        _fail(str(exc), code=exc.code, command="import")
    _report_import(result, text, target)


# --------------------------------------------------------------- simulate and graph


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
    print_simulation(report)


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
        console.print(render_tree(loaded))
        return

    text = GRAPH_EXPORTERS[output_format](loaded.graph)
    if output is None:
        typer.echo(text, nl=False)
    else:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]✓[/] graph written to {output}")
