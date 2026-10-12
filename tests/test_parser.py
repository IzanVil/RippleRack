from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ripplerack.parser import (
    ErrorCode,
    RippleRackError,
    load_datacenter,
    load_schema,
    parse_datacenter,
)


def test_example_builds_graph(raw_mini: dict[str, Any]) -> None:
    loaded = parse_datacenter(raw_mini)
    graph = loaded.graph
    assert graph.nodes["rack-a"]["kind"] == "rack"
    assert graph.has_edge("kafka", "orders-ingest")  # runs
    assert graph.has_edge("orders-ingest", "orders-enriched")  # feeds
    assert graph.has_edge("postgres", "api")  # explicit dependency, reversed
    assert graph.edges["postgres", "api"]["relation"] == "runtime"


def test_inputs_shorthand(raw_mini: dict[str, Any]) -> None:
    pipeline = parse_datacenter(raw_mini).datacenter.pipeline("customer-360")
    assert pipeline.inputs[0].pipeline == "orders-ingest"
    assert pipeline.inputs[0].fields is None


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["racks"][0]["servers"][0].update(id="srv-b1"), "duplicate component ids"),
        (lambda d: d["pipelines"][0].update(runs_on="nope"), "unknown service 'nope'"),
        (lambda d: d["pipelines"][1]["inputs"][0].update(pipeline="nope"), "unknown pipeline"),
        (lambda d: d["pipelines"][1]["inputs"][0].update(fields=["ghost"]), "missing from"),
        (
            lambda d: d["dependencies"].append({"source": "api", "target": "ghost"}),
            "unknown 'ghost'",
        ),
        (lambda d: d["racks"][0].update(colour="red"), "Extra inputs are not permitted"),
        (lambda d: d["pipelines"][0]["schema"].update(version="1.0"), "version"),
        (lambda d: d["racks"][0].update(power_capacity_kw=-1), "greater than 0"),
        (
            lambda d: d["dependencies"].append({"source": "kafka", "target": "dashboard"}),
            "dependency cycle",
        ),
    ],
)
def test_invalid_documents(raw_mini: dict[str, Any], mutate: Any, message: str) -> None:
    data = copy.deepcopy(raw_mini)
    mutate(data)
    with pytest.raises(RippleRackError, match=message):
        parse_datacenter(data)


def test_non_mapping_document() -> None:
    with pytest.raises(RippleRackError, match="must be a mapping"):
        parse_datacenter(["not", "a", "mapping"])


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RippleRackError, match="file not found"):
        load_datacenter(tmp_path / "missing.yaml")


def test_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("racks: [unclosed")
    with pytest.raises(RippleRackError, match="invalid YAML"):
        load_datacenter(path)


def test_load_schema_accepts_wrapped_form(tmp_path: Path) -> None:
    path = tmp_path / "schema.yaml"
    path.write_text("schema:\n  name: s\n  version: 1.0.0\n  fields: [{name: a, type: integer}]\n")
    assert load_schema(path).fields[0].name == "a"


def test_load_schema_rejects_duplicate_fields(tmp_path: Path) -> None:
    path = tmp_path / "schema.yaml"
    path.write_text(
        "name: s\nversion: 1.0.0\nfields: [{name: a, type: integer}, {name: a, type: string}]\n"
    )
    with pytest.raises(RippleRackError, match="duplicate fields"):
        load_schema(path)


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"racks: [a, b\n", ErrorCode.INVALID_YAML),
        (b"- a\n- list\n", ErrorCode.INVALID_DOCUMENT),
        (b"name: x\nbogus: 1\n", ErrorCode.VALIDATION_FAILED),
        (b"\xff\xfe not utf-8", ErrorCode.IO_ERROR),
    ],
)
def test_errors_carry_a_stable_code(tmp_path: Path, content: bytes, code: ErrorCode) -> None:
    path = tmp_path / "dc.yaml"
    path.write_bytes(content)
    with pytest.raises(RippleRackError) as excinfo:
        load_datacenter(path)
    assert excinfo.value.code is code


def test_missing_file_has_its_own_code(tmp_path: Path) -> None:
    with pytest.raises(RippleRackError) as excinfo:
        load_datacenter(tmp_path / "missing.yaml")
    assert excinfo.value.code is ErrorCode.FILE_NOT_FOUND


def test_cycle_has_its_own_code(raw_mini: dict[str, Any]) -> None:
    data = copy.deepcopy(raw_mini)
    data["dependencies"].append({"source": "kafka", "target": "dashboard"})
    with pytest.raises(RippleRackError) as excinfo:
        parse_datacenter(data)
    assert excinfo.value.code is ErrorCode.DEPENDENCY_CYCLE


def test_invalid_schema_file_has_a_validation_code(tmp_path: Path) -> None:
    path = tmp_path / "schema.yaml"
    path.write_text("name: s\n")
    with pytest.raises(RippleRackError) as excinfo:
        load_schema(path)
    assert excinfo.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_numbers_are_rejected(raw_mini: dict[str, Any], value: float) -> None:
    data = copy.deepcopy(raw_mini)
    data["racks"][0]["power_capacity_kw"] = value
    with pytest.raises(RippleRackError, match="finite number"):
        parse_datacenter(data)
