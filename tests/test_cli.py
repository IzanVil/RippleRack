from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from ripplerack.cli import app
from ripplerack.report import dumps
from tests.conftest import assert_json_golden

runner = CliRunner()
CHANGE_FILES = ["orders_v1_3_0", "orders_v2", "orders_sneaky_patch"]
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Remove terminal colour codes, which some environments force on."""
    return ANSI.sub("", text)


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


def impact_args(examples_dir: Path, change: str = "orders_v2", *extra: str) -> list[str]:
    return [
        "impact",
        str(examples_dir / "mini_datacenter.yaml"),
        "-p",
        "orders-ingest",
        "-s",
        str(examples_dir / "changes" / f"{change}.yaml"),
        *extra,
    ]


class TestImpactJson:
    def test_stdout_is_pure_json_and_stderr_is_empty(self, examples_dir: Path) -> None:
        result = runner.invoke(app, impact_args(examples_dir, "orders_v2", "--format", "json"))
        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        payload = json.loads(result.stdout)
        assert payload["command"] == "impact"
        assert payload["severity"] == "critical"

    @pytest.mark.parametrize("change", CHANGE_FILES)
    def test_golden(self, examples_dir: Path, change: str) -> None:
        result = runner.invoke(app, impact_args(examples_dir, change, "-F", "json"))
        assert result.exit_code == 0, result.output
        assert_json_golden(f"impact_{change}.json", json.loads(result.stdout))

    def test_output_is_canonical_and_deterministic(self, examples_dir: Path) -> None:
        args = impact_args(examples_dir, "orders_v2", "--format", "json")
        first = runner.invoke(app, args).stdout
        assert first == runner.invoke(app, args).stdout
        assert first == dumps(json.loads(first))

    def test_fail_on_breaking_still_prints_the_document(self, examples_dir: Path) -> None:
        args = impact_args(examples_dir, "orders_v2", "--format", "json", "--fail-on-breaking")
        result = runner.invoke(app, args)
        assert result.exit_code == 2
        assert json.loads(result.stdout)["summary"]["broken"] == 2

    def test_fail_on_breaking_passes_for_compatible_change(self, examples_dir: Path) -> None:
        args = impact_args(examples_dir, "orders_v1_3_0", "--format", "json", "--fail-on-breaking")
        result = runner.invoke(app, args)
        assert result.exit_code == 0
        assert json.loads(result.stdout)["severity"] == "low"

    def test_text_is_the_default_format(self, examples_dir: Path) -> None:
        default = runner.invoke(app, impact_args(examples_dir))
        explicit = runner.invoke(app, impact_args(examples_dir, "orders_v2", "--format", "text"))
        assert default.stdout == explicit.stdout
        assert "Severity:" in default.stdout
        with pytest.raises(json.JSONDecodeError):
            json.loads(default.stdout)

    def test_unknown_format_is_a_usage_error(self, examples_dir: Path) -> None:
        result = runner.invoke(app, impact_args(examples_dir, "orders_v2", "--format", "xml"))
        assert result.exit_code == 2
        assert result.stdout == ""


def write(path: Path, content: str | bytes) -> Path:
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def cyclic_datacenter(examples_dir: Path, path: Path) -> Path:
    data: dict[str, Any] = yaml.safe_load((examples_dir / "mini_datacenter.yaml").read_text())
    data["dependencies"].append({"source": "kafka", "target": "dashboard"})
    return write(path, yaml.safe_dump(data))


class TestImpactJsonErrors:
    """With --format json every failure is a JSON document on stderr and stdout stays empty."""

    def assert_error(self, args: list[str], code: str) -> dict[str, Any]:
        result = runner.invoke(app, [*args, "--format", "json"])
        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        document: dict[str, Any] = json.loads(result.stderr)
        assert list(document) == ["schemaVersion", "tool", "command", "error"]
        assert document["schemaVersion"] == 1
        assert document["command"] == "impact"
        assert list(document["error"]) == ["code", "message"]
        assert document["error"]["code"] == code
        assert document["error"]["message"]
        assert result.stderr == dumps(document)
        return document

    def test_file_not_found(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(tmp_path / "missing.yaml")
        document = self.assert_error(args, "file_not_found")
        assert "missing.yaml" in document["error"]["message"]

    def test_unknown_pipeline(self, examples_dir: Path) -> None:
        args = impact_args(examples_dir)
        args[3] = "ghost"
        document = self.assert_error(args, "unknown_pipeline")
        assert document["error"]["message"] == "unknown pipeline 'ghost'"

    def test_invalid_yaml(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(write(tmp_path / "bad.yaml", "racks: [a, b\n"))
        self.assert_error(args, "invalid_yaml")

    def test_invalid_document(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(write(tmp_path / "list.yaml", "- just\n- a list\n"))
        self.assert_error(args, "invalid_document")

    def test_validation_failed_in_datacenter(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(write(tmp_path / "bogus.yaml", "name: x\nbogus: 1\n"))
        document = self.assert_error(args, "validation_failed")
        assert "bogus" in document["error"]["message"]

    def test_validation_failed_in_schema_file(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[5] = str(write(tmp_path / "schema.yaml", "name: orders\n"))
        self.assert_error(args, "validation_failed")

    def test_dependency_cycle(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(cyclic_datacenter(examples_dir, tmp_path / "cycle.yaml"))
        document = self.assert_error(args, "dependency_cycle")
        assert "kafka" in document["error"]["message"]

    def test_io_error_for_invalid_utf8(self, examples_dir: Path, tmp_path: Path) -> None:
        args = impact_args(examples_dir)
        args[1] = str(write(tmp_path / "binary.yaml", b"\xff\xfe not utf-8"))
        self.assert_error(args, "io_error")


class TestTextErrors:
    def test_text_mode_errors_stay_human_readable(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["validate", str(tmp_path / "missing.yaml")])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert plain(result.stderr).startswith("error: file not found")
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stderr)

    def test_bracketed_text_in_a_message_is_printed_verbatim(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Rich would swallow "[abc]" as a markup tag and report a path that does not exist.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["validate", "dir[abc]/missing.yaml"])
        assert result.exit_code == 1
        assert "file not found: dir[abc]/missing.yaml" in plain(result.stderr)

    def test_unreadable_file_is_an_error_not_a_traceback(self, tmp_path: Path) -> None:
        path = write(tmp_path / "binary.yaml", b"\xff\xfe")
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 1
        assert "cannot read" in plain(result.stderr)


def test_graph_json_uses_camel_case_keys(examples_dir: Path) -> None:
    result = runner.invoke(app, ["graph", str(examples_dir / "mini_datacenter.yaml"), "-F", "json"])
    assert result.exit_code == 0
    nodes = {node["id"]: node for node in json.loads(result.stdout)["nodes"]}
    assert nodes["orders-ingest"]["dataSchemaVersion"] == "1.2.0"
    assert "schema_version" not in result.stdout
