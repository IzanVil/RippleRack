"""The two version numbers in the JSON output are different things and stay independent.

``schemaVersion`` versions the JSON contract: it lives at the root of every envelope
document and is decided by RippleRack. ``dataSchemaVersion`` is the version of the data
schema a pipeline produces: it lives on pipeline nodes of the graph export and comes from
the user's datacenter file. See ``docs/output-formats.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import ripplerack.report as report_module
from ripplerack.cli import app
from ripplerack.graph import to_json
from ripplerack.parser import LoadedDatacenter, parse_datacenter
from ripplerack.report import SCHEMA_VERSION, error_to_dict, impact_to_dict
from tests.helpers import impact_report, raw_datacenter

runner = CliRunner()
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
PIPELINES = ["orders-ingest", "orders-enriched", "revenue-daily", "customer-360"]


def paths_of(value: Any, key: str, path: str = "$") -> Iterator[str]:
    """Yield the JSON path of every occurrence of ``key`` in a decoded document."""
    if isinstance(value, dict):
        for name, item in value.items():
            here = f"{path}.{name}"
            if name == key:
                yield here
            yield from paths_of(item, key, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from paths_of(item, key, f"{path}[{index}]")


def datacenter_data(data_version: str | None = None) -> dict[str, Any]:
    """The mini datacenter as raw data, with every pipeline's schema set to ``data_version``."""
    data = raw_datacenter()
    if data_version is not None:
        for pipeline in data["pipelines"]:
            pipeline["schema"]["version"] = data_version
    return data


def datacenter_with(data_version: str) -> LoadedDatacenter:
    return parse_datacenter(datacenter_data(data_version))


def impact_document(loaded: LoadedDatacenter) -> dict[str, Any]:
    return impact_to_dict(loaded.datacenter.name, impact_report(loaded))


def graph_document(loaded: LoadedDatacenter) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(to_json(loaded.graph))
    return document


def pipeline_nodes(graph_export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in graph_export["nodes"] if n["kind"] == "pipeline"}


class TestBothKeysExist:
    def test_the_contract_version_is_at_the_root_of_every_envelope_document(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        documents = [
            impact_document(mini_dc),
            error_to_dict("impact", "unknown_pipeline", "unknown pipeline 'x'"),
        ]
        for document in documents:
            assert list(paths_of(document, "schemaVersion")) == ["$.schemaVersion"]
            assert document["schemaVersion"] == SCHEMA_VERSION

    def test_the_data_version_is_on_every_pipeline_node_of_the_graph_export(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        export = graph_document(mini_dc)
        nodes = pipeline_nodes(export)
        assert sorted(nodes) == sorted(PIPELINES)
        for pipeline_id, node in nodes.items():
            declared = mini_dc.datacenter.pipeline(pipeline_id).schema_.version
            assert node["dataSchemaVersion"] == declared
        others = [n for n in export["nodes"] if n["kind"] != "pipeline"]
        assert others
        assert all("dataSchemaVersion" not in node for node in others)

    def test_both_are_produced_by_the_command_line(self, examples_dir: Path) -> None:
        datacenter = str(examples_dir / "mini_datacenter.yaml")
        impact = runner.invoke(
            app,
            [
                "impact",
                datacenter,
                "-p",
                "orders-ingest",
                "-s",
                str(examples_dir / "changes" / "orders_v2.yaml"),
                "-F",
                "json",
            ],
        )
        graph = runner.invoke(app, ["graph", datacenter, "-F", "json"])
        assert impact.exit_code == graph.exit_code == 0
        assert json.loads(impact.stdout)["schemaVersion"] == 1
        nodes = pipeline_nodes(json.loads(graph.stdout))
        assert nodes["orders-ingest"]["dataSchemaVersion"] == "1.2.0"


class TestTheyAreDistinct:
    def test_the_graph_export_has_no_envelope_and_so_no_contract_version(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        export = graph_document(mini_dc)
        assert list(paths_of(export, "schemaVersion")) == []
        assert list(paths_of(export, "dataSchemaVersion")) != []

    def test_envelope_documents_carry_data_versions_under_other_names(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        document = impact_document(mini_dc)
        assert list(paths_of(document, "dataSchemaVersion")) == []
        schema = document["schema"]
        assert (schema["oldVersion"], schema["newVersion"]) == ("1.2.0", "2.0.0")
        assert schema["suggestedVersion"] == "2.0.0"

    def test_their_types_cannot_be_confused(self, mini_dc: LoadedDatacenter) -> None:
        contract = impact_document(mini_dc)["schemaVersion"]
        assert isinstance(contract, int)
        assert not isinstance(contract, bool)
        assert SEMVER.match(str(contract)) is None
        for node in pipeline_nodes(graph_document(mini_dc)).values():
            assert isinstance(node["dataSchemaVersion"], str)
            assert SEMVER.match(node["dataSchemaVersion"])

    @pytest.mark.parametrize("data_version", ["0.0.1", "1.2.0", "9.9.9", "10.0.0"])
    def test_a_data_version_is_never_mistaken_for_the_contract_version(
        self, data_version: str
    ) -> None:
        loaded = datacenter_with(data_version)
        contract = impact_document(loaded)["schemaVersion"]
        assert contract != data_version
        for node in pipeline_nodes(graph_document(loaded)).values():
            assert node["dataSchemaVersion"] != contract


class TestTheyAreIndependent:
    @pytest.mark.parametrize("data_version", ["0.0.1", "1.2.0", "9.9.9", "10.0.0"])
    def test_changing_the_data_versions_leaves_the_contract_version_alone(
        self, data_version: str
    ) -> None:
        loaded = datacenter_with(data_version)

        nodes = pipeline_nodes(graph_document(loaded))
        assert {node["dataSchemaVersion"] for node in nodes.values()} == {data_version}

        document = impact_document(loaded)
        assert document["schema"]["oldVersion"] == data_version
        assert document["schemaVersion"] == SCHEMA_VERSION == 1

    def test_bumping_a_pipelines_version_is_a_data_change_only(self) -> None:
        before = datacenter_data()
        after = datacenter_data()
        for data, version in ((before, "1.2.0"), (after, "2.0.0")):
            next(p for p in data["pipelines"] if p["id"] == "orders-ingest")["schema"][
                "version"
            ] = version
        old = impact_document(parse_datacenter(before))
        new = impact_document(parse_datacenter(after))
        assert old["schemaVersion"] == new["schemaVersion"] == 1
        assert old["schema"]["oldVersion"] == "1.2.0"
        assert new["schema"]["oldVersion"] == "2.0.0"
        old_node = pipeline_nodes(graph_document(parse_datacenter(before)))["orders-ingest"]
        new_node = pipeline_nodes(graph_document(parse_datacenter(after)))["orders-ingest"]
        assert (old_node["dataSchemaVersion"], new_node["dataSchemaVersion"]) == ("1.2.0", "2.0.0")

    def test_changing_the_contract_version_leaves_the_data_versions_alone(
        self, mini_dc: LoadedDatacenter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        data_before = impact_document(mini_dc)["schema"]
        export_before = graph_document(mini_dc)

        monkeypatch.setattr(report_module, "SCHEMA_VERSION", 2)

        document = impact_document(mini_dc)
        assert document["schemaVersion"] == 2
        assert document["schema"] == data_before
        assert error_to_dict("impact", "file_not_found", "x")["schemaVersion"] == 2
        assert graph_document(mini_dc) == export_before

    def test_a_breaking_change_to_the_data_does_not_make_the_contract_unstable(
        self, mini_dc: LoadedDatacenter
    ) -> None:
        # A major data change (critical impact) and a compatible one produce documents
        # with the same contract version.
        schemas = ("orders_v2.yaml", "orders_v1_3_0.yaml", "orders_sneaky_patch.yaml")
        versions = set()
        for name in schemas:
            report = impact_report(mini_dc, name.removesuffix(".yaml"))
            versions.add(impact_to_dict("dc", report)["schemaVersion"])
        assert versions == {1}
