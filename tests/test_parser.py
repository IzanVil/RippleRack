from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from ripplerack.parser import RippleRackError, load_datacenter, load_schema, parse_datacenter


@pytest.fixture
def raw(examples_dir: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((examples_dir / "mini_datacenter.yaml").read_text())
    return data


def test_example_builds_graph(raw: dict[str, Any]) -> None:
    loaded = parse_datacenter(raw)
    graph = loaded.graph
    assert graph.nodes["rack-a"]["kind"] == "rack"
    assert graph.has_edge("kafka", "orders-ingest")  # runs
    assert graph.has_edge("orders-ingest", "orders-enriched")  # feeds
    assert graph.has_edge("postgres", "api")  # explicit dependency, reversed
    assert graph.edges["postgres", "api"]["relation"] == "runtime"


def test_inputs_shorthand(raw: dict[str, Any]) -> None:
    pipeline = parse_datacenter(raw).datacenter.pipeline("customer-360")
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
def test_invalid_documents(raw: dict[str, Any], mutate: Any, message: str) -> None:
    data = copy.deepcopy(raw)
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
