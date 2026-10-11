from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ripplerack import __version__
from ripplerack.diff import DatacenterDiff, WarningCode, diff_datacenters
from ripplerack.graph import to_json
from ripplerack.impact import ImpactReport, analyze_schema_change
from ripplerack.models import Schema
from ripplerack.parser import ErrorCode, LoadedDatacenter, load_datacenter, load_schema
from ripplerack.report import (
    SCHEMA_VERSION,
    diff_to_dict,
    dumps,
    error_to_dict,
    impact_to_dict,
    schema_diff_to_dict,
)
from ripplerack.semver import ChangeKind, diff_schemas
from tests.conftest import (
    EXAMPLES,
    assert_json_golden,
    load_variant,
    make_schema,
    pipeline_of,
    server_of,
)

CAMEL_CASE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
CHANGE_FILES = ["orders_v1_3_0", "orders_v2", "orders_sneaky_patch"]
SEVERITIES = {"none", "low", "medium", "high", "critical"}
LEVELS = {"none", "patch", "minor", "major"}


def all_keys(value: Any) -> Iterator[str]:
    """Yield every object key found anywhere in a decoded JSON document."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from all_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_keys(item)


def make_report(mini_dc: LoadedDatacenter, examples_dir: Path, change: str) -> ImpactReport:
    schema = load_schema(examples_dir / "changes" / f"{change}.yaml")
    return analyze_schema_change(mini_dc.datacenter, mini_dc.graph, "orders-ingest", schema)


@pytest.fixture
def v2_payload(mini_dc: LoadedDatacenter, examples_dir: Path) -> dict[str, Any]:
    report = make_report(mini_dc, examples_dir, "orders_v2")
    return impact_to_dict(mini_dc.datacenter.name, report)


class TestEnvelope:
    def test_fields(self, v2_payload: dict[str, Any]) -> None:
        assert v2_payload["schemaVersion"] == SCHEMA_VERSION == 1
        assert v2_payload["tool"] == {"name": "ripplerack", "version": __version__}
        assert v2_payload["command"] == "impact"

    def test_error_document_shares_the_envelope(self) -> None:
        payload = error_to_dict("impact", ErrorCode.FILE_NOT_FOUND, "file not found: x.yaml")
        assert set(payload) == {"schemaVersion", "tool", "command", "error"}
        assert payload["error"] == {"code": "file_not_found", "message": "file not found: x.yaml"}
        assert payload["tool"] == {"name": "ripplerack", "version": __version__}


class TestImpactPayload:
    def test_top_level_keys_are_exact(self, v2_payload: dict[str, Any]) -> None:
        assert list(v2_payload) == [
            "schemaVersion",
            "tool",
            "command",
            "datacenter",
            "pipeline",
            "severity",
            "schema",
            "brokenConsumers",
            "atRisk",
            "affected",
            "summary",
        ]

    def test_nested_keys_are_exact(self, v2_payload: dict[str, Any]) -> None:
        assert list(v2_payload["schema"]) == [
            "name",
            "oldVersion",
            "newVersion",
            "level",
            "suggestedVersion",
            "versionConsistent",
            "changes",
        ]
        assert list(v2_payload["schema"]["changes"][0]) == [
            "kind",
            "level",
            "field",
            "message",
            "breaksReaders",
        ]
        assert list(v2_payload["brokenConsumers"][0]) == ["pipeline", "fields", "changes"]
        assert list(v2_payload["affected"][0]) == ["id", "kind", "distance", "path", "status"]
        assert list(v2_payload["summary"]) == ["affected", "broken", "atRisk", "breakingChanges"]

    @pytest.mark.parametrize("change", CHANGE_FILES)
    def test_enumerations_are_lowercase_strings(
        self, mini_dc: LoadedDatacenter, examples_dir: Path, change: str
    ) -> None:
        payload = impact_to_dict("dc", make_report(mini_dc, examples_dir, change))
        assert payload["severity"] in SEVERITIES
        assert payload["schema"]["level"] in LEVELS
        for item in payload["schema"]["changes"]:
            assert item["level"] in LEVELS
            assert item["kind"] in {kind.value for kind in ChangeKind}
        for node in payload["affected"]:
            assert node["status"] in {"broken", "at_risk", "affected"}
            assert node["kind"] in {"rack", "server", "service", "pipeline"}

    def test_affected_status_labels(self, v2_payload: dict[str, Any]) -> None:
        statuses = {node["id"]: node["status"] for node in v2_payload["affected"]}
        assert statuses == {
            "customer-360": "broken",
            "orders-enriched": "broken",
            "api": "at_risk",
            "revenue-daily": "at_risk",
            "dashboard": "at_risk",
        }

    def test_compatible_change_marks_everything_as_merely_affected(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        payload = impact_to_dict("dc", make_report(mini_dc, examples_dir, "orders_v1_3_0"))
        assert payload["severity"] == "low"
        assert payload["brokenConsumers"] == []
        assert payload["atRisk"] == []
        assert {node["status"] for node in payload["affected"]} == {"affected"}

    def test_no_change(self, mini_dc: LoadedDatacenter, orders_schema: Schema) -> None:
        report = analyze_schema_change(
            mini_dc.datacenter, mini_dc.graph, "orders-ingest", orders_schema
        )
        payload = impact_to_dict("dc", report)
        assert payload["severity"] == "none"
        assert payload["schema"]["level"] == "none"
        assert payload["schema"]["changes"] == []
        assert payload["summary"]["breakingChanges"] == 0

    def test_understated_version_is_reported(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        payload = impact_to_dict("dc", make_report(mini_dc, examples_dir, "orders_sneaky_patch"))
        assert payload["schema"]["newVersion"] == "1.2.1"
        assert payload["schema"]["suggestedVersion"] == "2.0.0"
        assert payload["schema"]["versionConsistent"] is False

    def test_changes_are_sorted_major_first_then_by_field(self) -> None:
        # Fields are deliberately declared out of alphabetical order.
        old = make_schema("1.0.0", {"name": "b"}, {"name": "a"}, {"name": "c"})
        new = make_schema(
            "2.0.0", {"name": "z", "nullable": True}, {"name": "c", "type": "integer"}
        )
        # b and a removed (major), c retyped (major), z added optional (minor)
        changes = schema_diff_to_dict(diff_schemas(old, new))["changes"]
        assert [(c["level"], c["field"]) for c in changes] == [
            ("major", "a"),
            ("major", "b"),
            ("major", "c"),
            ("minor", "z"),
        ]

    def test_summary_matches_the_lists(self, v2_payload: dict[str, Any]) -> None:
        summary = v2_payload["summary"]
        assert summary["affected"] == len(v2_payload["affected"])
        assert summary["broken"] == len(v2_payload["brokenConsumers"])
        assert summary["atRisk"] == len(v2_payload["atRisk"])
        assert summary["breakingChanges"] == 2

    def test_lists_are_sorted(self, v2_payload: dict[str, Any]) -> None:
        broken = [item["pipeline"] for item in v2_payload["brokenConsumers"]]
        assert broken == sorted(broken)
        assert v2_payload["atRisk"] == sorted(v2_payload["atRisk"])
        order = [(node["distance"], node["id"]) for node in v2_payload["affected"]]
        assert order == sorted(order)

    @pytest.mark.parametrize("change", CHANGE_FILES)
    def test_golden(self, mini_dc: LoadedDatacenter, examples_dir: Path, change: str) -> None:
        payload = impact_to_dict(
            mini_dc.datacenter.name, make_report(mini_dc, examples_dir, change)
        )
        assert_json_golden(f"impact_{change}.json", payload)


class TestKeyStyle:
    """All JSON produced by RippleRack uses camelCase keys."""

    @pytest.mark.parametrize("change", CHANGE_FILES)
    def test_impact_keys(self, mini_dc: LoadedDatacenter, examples_dir: Path, change: str) -> None:
        payload = impact_to_dict("dc", make_report(mini_dc, examples_dir, change))
        assert all(CAMEL_CASE.match(key) for key in all_keys(payload)), set(all_keys(payload))

    def test_error_keys(self) -> None:
        payload = error_to_dict("impact", "validation_failed", "boom")
        assert all(CAMEL_CASE.match(key) for key in all_keys(payload))

    def test_graph_export_keys(self, mini_dc: LoadedDatacenter) -> None:
        document = json.loads(to_json(mini_dc.graph))
        keys = set(all_keys(document))
        assert all(CAMEL_CASE.match(key) for key in keys), keys
        assert "schema_version" not in keys

    def test_graph_export_pipeline_nodes_expose_the_data_schema_version(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        nodes = {node["id"]: node for node in json.loads(to_json(mini_dc.graph))["nodes"]}
        assert nodes["orders-ingest"]["dataSchemaVersion"] == "1.2.0"
        assert "dataSchemaVersion" not in nodes["kafka"]
        assert "schemaVersion" not in nodes["orders-ingest"]


class TestDumps:
    def test_output_is_canonical_and_ends_with_newline(self, v2_payload: dict[str, Any]) -> None:
        text = dumps(v2_payload)
        assert text.endswith("}\n")
        assert text == json.dumps(json.loads(text), indent=2) + "\n"

    def test_output_is_ascii_only(self) -> None:
        text = dumps({"name": "Centro de datos ñ"})
        assert text.isascii()
        assert json.loads(text) == {"name": "Centro de datos ñ"}

    def test_output_is_deterministic(self, mini_dc: LoadedDatacenter, examples_dir: Path) -> None:
        first = dumps(impact_to_dict("dc", make_report(mini_dc, examples_dir, "orders_v2")))
        second = dumps(impact_to_dict("dc", make_report(mini_dc, examples_dir, "orders_v2")))
        assert first == second


def kitchen_sink(data: dict[str, Any]) -> None:
    """Touch every section of the diff document at once."""
    data["name"] = "mini-datacenter-next"
    data["description"] = "Kitchen sink."

    # kafka is renamed to broker, and everything that pointed at it follows
    for service in server_of(data, "srv-a1")["services"]:
        if service["id"] == "kafka":
            service["id"] = "broker"
    pipeline_of(data, "orders-ingest")["runs_on"] = "broker"
    for dependency in data["dependencies"]:
        if dependency["target"] == "kafka":
            dependency["target"] = "broker"

    # a breaking change shipped as a patch: coupon_code disappears in 1.2.1
    schema = pipeline_of(data, "orders-ingest")["schema"]
    schema["version"] = "1.2.1"
    schema["fields"] = [f for f in schema["fields"] if f["name"] != "coupon_code"]

    # the dashboard service becomes a pipeline, and a redis service is added
    server = server_of(data, "srv-b1")
    server["services"] = [s for s in server["services"] if s["id"] != "dashboard"]
    server["services"].append({"id": "redis", "cpu_cores": 2, "memory_gb": 8})
    data["pipelines"].append(
        {
            "id": "dashboard",
            "runs_on": "spark",
            "schema": {"name": "dashboard", "version": "1.0.0", "fields": []},
        }
    )
    data["dependencies"].append({"source": "api", "target": "redis", "kind": "runtime"})


@pytest.fixture
def example_diff(mini_dc: LoadedDatacenter) -> DatacenterDiff:
    return diff_datacenters(mini_dc, load_datacenter(EXAMPLES / "mini_datacenter_v2.yaml"))


@pytest.fixture
def sink_diff(mini_dc: LoadedDatacenter) -> DatacenterDiff:
    return diff_datacenters(mini_dc, load_variant(kitchen_sink))


class TestDiffPayload:
    def test_envelope(self, example_diff: DatacenterDiff) -> None:
        payload = diff_to_dict(example_diff)
        assert payload["schemaVersion"] == 1
        assert payload["tool"] == {"name": "ripplerack", "version": __version__}
        assert payload["command"] == "diff"

    def test_keys_are_exact(self, sink_diff: DatacenterDiff) -> None:
        payload = diff_to_dict(sink_diff)
        assert list(payload) == [
            "schemaVersion",
            "tool",
            "command",
            "base",
            "head",
            "severity",
            "summary",
            "metadata",
            "components",
            "dependencies",
            "schemaChanges",
            "removedWithDependents",
            "possibleRenames",
            "warnings",
        ]
        assert list(payload["base"]) == ["name"]
        assert list(payload["summary"]) == [
            "added",
            "removed",
            "modified",
            "dependenciesAdded",
            "dependenciesRemoved",
            "dependenciesModified",
            "schemaChanges",
            "brokenConsumers",
            "warnings",
        ]
        assert list(payload["metadata"][0]) == ["attribute", "before", "after"]
        assert list(payload["components"]) == ["added", "removed", "modified"]
        assert list(payload["components"]["added"][0]) == ["id", "kind", "parent"]
        assert list(payload["components"]["modified"][0]) == ["id", "kind", "changes"]
        assert list(payload["components"]["modified"][0]["changes"][0]) == [
            "attribute",
            "before",
            "after",
        ]
        assert list(payload["dependencies"]) == ["added", "removed", "modified"]
        assert list(payload["dependencies"]["added"][0]) == ["source", "target", "kind"]
        assert list(payload["schemaChanges"][0]) == [
            "pipeline",
            "severity",
            "schema",
            "brokenConsumers",
            "atRisk",
            "affected",
            "summary",
        ]
        assert list(payload["removedWithDependents"][0]) == ["id", "kind", "dependents"]
        assert list(payload["possibleRenames"][0]) == ["kind", "from", "to"]
        assert list(payload["warnings"][0]) == ["code", "message"]

    def test_modified_dependencies_have_before_and_after(
        self, example_diff: DatacenterDiff
    ) -> None:
        payload = diff_to_dict(example_diff)
        assert payload["dependencies"]["modified"] == [
            {"source": "spark", "target": "kafka", "before": "network", "after": "data"}
        ]

    def test_summary_matches_the_lists(self, sink_diff: DatacenterDiff) -> None:
        payload = diff_to_dict(sink_diff)
        summary = payload["summary"]
        assert summary["added"] == len(payload["components"]["added"]) == 3
        assert summary["removed"] == len(payload["components"]["removed"]) == 2
        assert summary["modified"] == len(payload["components"]["modified"]) == 1
        assert summary["dependenciesAdded"] == len(payload["dependencies"]["added"])
        assert summary["dependenciesRemoved"] == len(payload["dependencies"]["removed"])
        assert summary["schemaChanges"] == len(payload["schemaChanges"]) == 1
        assert summary["brokenConsumers"] == 1
        assert summary["warnings"] == len(payload["warnings"]) == 3

    def test_enumerations(self, sink_diff: DatacenterDiff) -> None:
        payload = diff_to_dict(sink_diff)
        assert payload["severity"] in SEVERITIES
        kinds = {"rack", "server", "service", "pipeline"}
        for ref in [*payload["components"]["added"], *payload["components"]["removed"]]:
            assert ref["kind"] in kinds
        for dependency in [*payload["dependencies"]["added"], *payload["dependencies"]["removed"]]:
            assert dependency["kind"] in {"runtime", "data", "network"}
        assert {w["code"] for w in payload["warnings"]} == {code.value for code in WarningCode}

    def test_nothing_to_report(self, mini_dc: LoadedDatacenter) -> None:
        payload = diff_to_dict(diff_datacenters(mini_dc, mini_dc))
        assert payload["severity"] == "none"
        assert set(payload["summary"].values()) == {0}
        assert payload["metadata"] == payload["schemaChanges"] == payload["warnings"] == []
        assert payload["components"] == {"added": [], "removed": [], "modified": []}

    def test_is_valid_strict_json(self, sink_diff: DatacenterDiff) -> None:
        json.dumps(diff_to_dict(sink_diff), allow_nan=False)

    def test_is_deterministic(self, mini_dc: LoadedDatacenter) -> None:
        first = dumps(diff_to_dict(diff_datacenters(mini_dc, load_variant(kitchen_sink))))
        second = dumps(diff_to_dict(diff_datacenters(mini_dc, load_variant(kitchen_sink))))
        assert first == second

    def test_keys_are_camel_case(
        self, example_diff: DatacenterDiff, sink_diff: DatacenterDiff
    ) -> None:
        for diff in (example_diff, sink_diff):
            keys = set(all_keys(diff_to_dict(diff)))
            assert all(CAMEL_CASE.match(key) for key in keys), keys

    def test_golden_example(self, example_diff: DatacenterDiff) -> None:
        assert_json_golden("diff_mini_datacenter_v2.json", diff_to_dict(example_diff))

    def test_golden_kitchen_sink(self, sink_diff: DatacenterDiff) -> None:
        assert_json_golden("diff_kitchen_sink.json", diff_to_dict(sink_diff))
