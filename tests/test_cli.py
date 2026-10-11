from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ripplerack.cli import app

runner = CliRunner()


def test_validate(examples_dir: Path) -> None:
    result = runner.invoke(app, ["validate", str(examples_dir / "mini_datacenter.yaml")])
    assert result.exit_code == 0, result.output
    assert "is valid" in result.output


def test_validate_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nope.yaml")])
    assert result.exit_code == 1


def test_impact_fail_on_breaking(examples_dir: Path) -> None:
    args = [
        "impact",
        str(examples_dir / "mini_datacenter.yaml"),
        "--pipeline",
        "orders-ingest",
        "--schema",
        str(examples_dir / "changes" / "orders_v2.yaml"),
    ]
    assert runner.invoke(app, args).exit_code == 0
    result = runner.invoke(app, [*args, "--fail-on-breaking"])
    assert result.exit_code == 2
    assert "CRITICAL" in result.output


def test_impact_unknown_pipeline(examples_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "impact",
            str(examples_dir / "mini_datacenter.yaml"),
            "-p",
            "ghost",
            "-s",
            str(examples_dir / "changes" / "orders_v2.yaml"),
        ],
    )
    assert result.exit_code == 1


def test_simulate(examples_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "simulate",
            str(examples_dir / "mini_datacenter.yaml"),
            "--load",
            "1.5",
            "--fail",
            "kafka",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "orders-ingest" in result.output


def test_graph_json(examples_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "graph.json"
    result = runner.invoke(
        app, ["graph", str(examples_dir / "mini_datacenter.yaml"), "-F", "json", "-o", str(out)]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert {"source": "kafka", "target": "orders-ingest", "relation": "runs"} in data["edges"]


def test_graph_dot(examples_dir: Path) -> None:
    result = runner.invoke(app, ["graph", str(examples_dir / "mini_datacenter.yaml"), "-F", "dot"])
    assert result.exit_code == 0
    assert result.output.startswith('digraph "mini-datacenter"')


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ripplerack" in result.output
