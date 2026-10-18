"""What the commands print for people, pinned with golden files.

Each scenario writes its files in a folder, runs one command and compares what it prints (a
terminal of 110 columns, without colours) with a file in ``tests/golden/``. Together the scenarios
draw every table, line and branch of ``display.py``, which the JSON and Mermaid tests do not reach.
Run the tests with ``RIPPLERACK_UPDATE_GOLDEN=1`` to rewrite the files, and read the diff.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from ripplerack.cli import app
from ripplerack.diff import AttributeChange
from ripplerack.display import _describe_change
from tests.helpers import (
    EXAMPLES,
    assert_text_golden,
    pipeline_of,
    rack_of,
    raw_datacenter,
    server_of,
)

runner = CliRunner()
ANSI = re.compile(r"\x1b\[[0-9;]*m")
Files = dict[str, Any]
Scenario = Callable[[], tuple[Files, list[str]]]


def orders_schema(**changes: Any) -> dict[str, Any]:
    """The schema of ``orders-ingest`` as it is in the example, with the changes asked for."""
    schema: dict[str, Any] = copy.deepcopy(pipeline_of(raw_datacenter(), "orders-ingest")["schema"])
    schema.update(changes)
    return schema


def with_field(schema: dict[str, Any], **field: Any) -> dict[str, Any]:
    return {**schema, "fields": [*schema["fields"], field]}


# ------------------------------------------------------------------------ the datacenters


def renamed_and_edited() -> dict[str, Any]:
    """A head that differs from the example in every way a comparison can report."""
    data = raw_datacenter()
    data["name"] = "mini-datacenter-2"
    data["description"] = "The same racks, one year later."
    # components: one added with its parents, one modified, one removed, one renamed
    data["racks"].append(
        {
            "id": "rack-c",
            "power_capacity_kw": 3,
            "servers": [
                {
                    "id": "srv-c1",
                    "cpu_cores": 8,
                    "memory_gb": 32,
                    "power_kw": 0.5,
                    "services": [{"id": "redis", "cpu_cores": 2, "memory_gb": 8}],
                }
            ],
        }
    )
    rack_of(data, "rack-a")["power_capacity_kw"] = 3.2
    server_of(data, "srv-a1")["cpu_cores"] = 48
    server_of(data, "srv-a1")["services"][1]["description"] = "Event broker and log"
    services = server_of(data, "srv-b1")["services"]
    services[1]["id"] = "bi-dashboard"  # the same service under another name
    # dependencies: one added, one removed, one with another kind, one renamed with its service
    data["dependencies"] = [
        {"source": "api", "target": "redis", "kind": "network"},
        {"source": "api", "target": "customer-360", "kind": "data"},
        {"source": "bi-dashboard", "target": "revenue-daily", "kind": "data"},
        {"source": "spark", "target": "kafka", "kind": "data"},
    ]
    # pipelines: one removed while its consumer stays, one with a schema that breaks a consumer
    data["pipelines"] = [p for p in data["pipelines"] if p["id"] != "orders-enriched"]
    pipeline_of(data, "revenue-daily")["inputs"] = []
    ingest = pipeline_of(data, "orders-ingest")
    ingest["schema"] = {
        "name": "orders",
        "version": "1.3.0",
        "fields": [f for f in ingest["schema"]["fields"] if f["name"] != "amount"]
        + [{"name": "amount_cents", "type": "integer"}],
    }
    return data


def compatible_schema_change() -> dict[str, Any]:
    """A head where a pipeline gains an optional field: a change that breaks no consumer."""
    data = raw_datacenter()
    ingest = pipeline_of(data, "orders-ingest")
    ingest["schema"] = with_field(
        {**ingest["schema"], "version": "1.3.0"}, name="channel", type="string", nullable=True
    )
    return data


def inputs_changed() -> dict[str, Any]:
    """A head where the inputs of the pipelines change in each of the ways that are described."""
    data = raw_datacenter()
    ingest_fields = ["order_id", "coupon_code", "created_at"]
    pipeline_of(data, "orders-enriched")["inputs"] = [
        {"pipeline": "orders-ingest", "fields": ingest_fields}
    ]  # some fields out, one in
    pipeline_of(data, "customer-360")["inputs"] = [
        {"pipeline": "orders-ingest", "fields": ["order_id"]}
    ]  # from every field to some
    pipeline_of(data, "revenue-daily")["inputs"] = [
        {
            "pipeline": "orders-enriched",
            "fields": ["customer_segment", "amount_eur", "created_date"],
        },
        {"pipeline": "customer-360"},
    ]  # one input as it was, an upstream in
    return data


def inputs_listed_twice() -> dict[str, Any]:
    data = raw_datacenter()
    pipeline_of(data, "customer-360")["inputs"] = [
        {"pipeline": "orders-ingest", "fields": ["order_id"]},
        {"pipeline": "orders-ingest"},
    ]
    return data


def service_becomes_pipeline() -> dict[str, Any]:
    """The id of a service is reused by a pipeline: it is reported as removed and added."""
    data = raw_datacenter()
    services = server_of(data, "srv-b1")["services"]
    services[:] = [s for s in services if s["id"] != "dashboard"]
    data["dependencies"] = [d for d in data["dependencies"] if d["source"] != "dashboard"]
    data["pipelines"].append(
        {
            "id": "dashboard",
            "runs_on": "api",
            "inputs": ["revenue-daily"],
            "schema": {
                "name": "dashboard",
                "version": "1.0.0",
                "fields": [{"name": "x", "type": "string"}],
            },
        }
    )
    return data


def without_dependencies() -> dict[str, Any]:
    data = raw_datacenter()
    del data["dependencies"]
    return data


# --------------------------------------------------------------------------- the scenarios


def validate() -> tuple[Files, list[str]]:
    return {"base.yaml": raw_datacenter()}, ["validate", "base.yaml"]


def tree() -> tuple[Files, list[str]]:
    return {"base.yaml": raw_datacenter()}, ["graph", "base.yaml"]


def tree_without_dependencies() -> tuple[Files, list[str]]:
    return {"base.yaml": without_dependencies()}, ["graph", "base.yaml"]


def impact(schema: dict[str, Any]) -> Scenario:
    def build() -> tuple[Files, list[str]]:
        files = {"base.yaml": raw_datacenter(), "schema.yaml": schema}
        return files, ["impact", "base.yaml", "-p", "orders-ingest", "-s", "schema.yaml"]

    return build


def impact_on_a_leaf() -> tuple[Files, list[str]]:
    """The schema of a pipeline that no one reads and nothing depends on changes."""
    data = without_dependencies()
    schema = pipeline_of(data, "revenue-daily")["schema"]
    changed = with_field({**schema, "version": "2.2.0"}, name="note", type="string", nullable=True)
    return {"base.yaml": data, "schema.yaml": changed}, [
        "impact",
        "base.yaml",
        "-p",
        "revenue-daily",
        "-s",
        "schema.yaml",
    ]


def diff(head: dict[str, Any], base: dict[str, Any] | None = None) -> Scenario:
    def build() -> tuple[Files, list[str]]:
        files = {"base.yaml": raw_datacenter() if base is None else base, "head.yaml": head}
        return files, ["diff", "base.yaml", "head.yaml"]

    return build


def simulate(*options: str) -> Scenario:
    def build() -> tuple[Files, list[str]]:
        return {"base.yaml": raw_datacenter()}, ["simulate", "base.yaml", *options]

    return build


def example_v2() -> tuple[Files, list[str]]:
    head = yaml.safe_load((EXAMPLES / "mini_datacenter_v2.yaml").read_text(encoding="utf-8"))
    return diff(head)()


SCENARIOS: dict[str, Scenario] = {
    "validate": validate,
    "tree": tree,
    "tree_without_dependencies": tree_without_dependencies,
    "impact_breaking_change": impact(
        yaml.safe_load((EXAMPLES / "changes" / "orders_v2.yaml").read_text(encoding="utf-8"))
    ),
    "impact_no_change": impact(orders_schema()),
    "impact_compatible_change": impact(
        with_field(orders_schema(version="1.3.0"), name="channel", type="string", nullable=True)
    ),
    "impact_version_too_low": impact(
        with_field(orders_schema(version="1.2.1"), name="channel", type="string")
    ),
    "impact_on_a_leaf": impact_on_a_leaf,
    "simulate_default": simulate(),
    "simulate_overloaded_and_failed": simulate(
        "--load", "2.5", "--fail", "srv-a2", "--fail", "kafka"
    ),
    "simulate_failure_without_consequences": simulate("--load", "0.1", "--fail", "api"),
    "simulate_a_failure_inside_another": simulate("--fail", "srv-a2", "--fail", "spark"),
    "diff_identical": diff(raw_datacenter()),
    "diff_example_v2": example_v2,
    "diff_everything": diff(renamed_and_edited()),
    "diff_compatible_schema_change": diff(compatible_schema_change()),
    "diff_inputs_changed": diff(inputs_changed()),
    "diff_inputs_changed_back": diff(raw_datacenter(), base=inputs_changed()),
    "diff_inputs_listed_twice": diff(inputs_listed_twice()),
    "diff_service_becomes_pipeline": diff(service_becomes_pipeline()),
}


@pytest.mark.parametrize("name", SCENARIOS)
def test_what_the_command_prints(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files, args = SCENARIOS[name]()
    for file_name, document in files.items():
        (tmp_path / file_name).write_text(
            yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
        )
    monkeypatch.chdir(tmp_path)  # so that the file names in the output are the same everywhere
    result = runner.invoke(app, args, env={"COLUMNS": "110"})
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert_text_golden(f"display_{name}.txt", ANSI.sub("", result.stdout))


@pytest.mark.parametrize(
    ("attribute", "before", "after", "expected"),
    [
        ("cpu_cores", 32, 48, "cpu_cores: 32 → 48"),
        ("power_capacity_kw", 2.8, 3.0, "power_capacity_kw: 2.8 → 3"),
        ("description", "", "Event broker", "description: (empty) → Event broker"),
        ("description", "Event broker", "", "description: Event broker → (empty)"),
        ("name", "mini", "mini-2", "name: mini → mini-2"),
        ("tags", ["a", "b"], [], "tags: a, b → (none)"),
        ("note", "[bold]x[/]", "y", "note: \\[bold]x\\[/] → y"),  # markup is printed as it is
        ("schema.fields", [{"name": "a"}], [], "schema.fields: changed (see below)"),
        ("inputs", "old", "new", "inputs: old → new"),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a"]}],
            [{"pipeline": "p", "fields": None}],
            "inputs: p: a → all fields",
        ),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a"]}],
            [{"pipeline": "p", "fields": ["a"]}, {"pipeline": "q", "fields": None}],
            "inputs: +q",
        ),
        (
            "inputs",
            [{"pipeline": "p", "fields": ["a", "a"]}],
            [{"pipeline": "p", "fields": ["a"]}],
            "inputs: p: ",
        ),
    ],
)
def test_one_changed_attribute_is_described_in_a_line(
    attribute: str, before: object, after: object, expected: str
) -> None:
    assert _describe_change(AttributeChange(attribute, before, after)) == expected
