from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from ripplerack.graph import NodeKind
from ripplerack.impact import ImpactReport, analyze_schema_change
from ripplerack.mermaid import MermaidHighlight, to_mermaid
from ripplerack.parser import LoadedDatacenter, load_schema, parse_datacenter
from tests.conftest import EXAMPLES, assert_text_golden

RESERVED = {
    "end",
    "graph",
    "subgraph",
    "style",
    "class",
    "classDef",
    "click",
    "default",
    "linkStyle",
    "flowchart",
    "direction",
}

# The complete grammar the exporter is allowed to produce. Any other line is a bug.
SUBGRAPH = re.compile(r'^(?P<pad> *)subgraph (?P<id>\w+)\["(?P<label>[^"]*)"\]$')
END = re.compile(r"^ *end$")
NODE = re.compile(r'^(?P<pad> *)(?P<id>\w+)(?P<shape>\("[^"]*"\)|\["[^"]*"\]|\{\{"[^"]*"\}\})$')
EDGE = re.compile(r"^ +(?P<src>\w+) -->(?:\|(?P<label>[^|]*)\|)? (?P<dst>\w+)$")
CLASS_DEF = re.compile(r"^ +classDef (?P<name>\w+) (?P<style>\S+)$")
CLASS_USE = re.compile(r"^ +class (?P<ids>[\w,]+) (?P<name>\w+)$")
STYLE = re.compile(r"^ +style (?P<id>\w+) (?P<style>\S+)$")
LINK_STYLE = re.compile(r"^ +linkStyle (?P<indexes>[\d,]+) (?P<style>\S+)$")
COMMENT = re.compile(r"^ +%% ")


@dataclass
class Diagram:
    """A Mermaid diagram read back by a deliberately strict parser."""

    parent: dict[str, str | None] = field(default_factory=dict)
    subgraphs: list[str] = field(default_factory=list)
    nodes: dict[str, str] = field(default_factory=dict)  # id -> shape and label
    edges: list[tuple[str, str, str | None]] = field(default_factory=list)
    class_defs: dict[str, str] = field(default_factory=dict)
    node_class: dict[str, str] = field(default_factory=dict)
    styles: dict[str, str] = field(default_factory=dict)
    link_styles: dict[int, str] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    children: dict[str, int] = field(default_factory=dict)

    @property
    def declared(self) -> set[str]:
        return set(self.nodes) | set(self.subgraphs)


def parse(text: str) -> Diagram:
    assert text.endswith("\n")
    lines = text.splitlines()
    assert lines[0] == "flowchart LR"
    diagram = Diagram()
    stack: list[str] = []
    for line in lines[1:]:
        if match := SUBGRAPH.match(line):
            container = match["id"]
            assert container not in diagram.declared, f"duplicate id {container}"
            if stack:
                diagram.children[stack[-1]] = diagram.children.get(stack[-1], 0) + 1
            diagram.parent[container] = stack[-1] if stack else None
            diagram.subgraphs.append(container)
            diagram.children.setdefault(container, 0)
            stack.append(container)
        elif END.match(line):
            stack.pop()
        elif match := NODE.match(line):
            node = match["id"]
            assert node not in diagram.declared, f"duplicate id {node}"
            if stack:
                diagram.children[stack[-1]] = diagram.children.get(stack[-1], 0) + 1
            diagram.parent[node] = stack[-1] if stack else None
            diagram.nodes[node] = match["shape"]
        elif match := EDGE.match(line):
            diagram.edges.append((match["src"], match["dst"], match["label"]))
        elif match := CLASS_DEF.match(line):
            diagram.class_defs[match["name"]] = match["style"]
        elif match := CLASS_USE.match(line):
            for node in match["ids"].split(","):
                assert node not in diagram.node_class, f"{node} has two classes"
                diagram.node_class[node] = match["name"]
        elif match := STYLE.match(line):
            diagram.styles[match["id"]] = match["style"]
        elif match := LINK_STYLE.match(line):
            for index in match["indexes"].split(","):
                assert int(index) not in diagram.link_styles
                diagram.link_styles[int(index)] = match["style"]
        elif COMMENT.match(line):
            diagram.comments.append(line.strip())
        else:
            raise AssertionError(f"unexpected line: {line!r}")
    assert stack == [], "unbalanced subgraph/end"
    return diagram


def load_variant(mutate: Callable[[dict[str, Any]], None]) -> LoadedDatacenter:
    """Load the mini datacenter after applying ``mutate`` to its raw YAML data."""
    data: dict[str, Any] = yaml.safe_load((EXAMPLES / "mini_datacenter.yaml").read_text())
    mutate(data)
    return parse_datacenter(data)


def srv_b1(data: dict[str, Any]) -> dict[str, Any]:
    server: dict[str, Any] = data["racks"][1]["servers"][0]
    assert server["id"] == "srv-b1"
    return server


def impact_report(
    mini_dc: LoadedDatacenter, examples_dir: Path, change: str = "orders_v2"
) -> ImpactReport:
    schema = load_schema(examples_dir / "changes" / f"{change}.yaml")
    return analyze_schema_change(mini_dc.datacenter, mini_dc.graph, "orders-ingest", schema)


class TestStructure:
    def test_every_line_belongs_to_the_expected_grammar(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        assert diagram.comments == ["%% mini-datacenter"]

    def test_racks_and_servers_are_nested_subgraphs(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        assert diagram.parent["svc_kafka"] == "srv_srv_a1"
        assert diagram.parent["svc_spark"] == "srv_srv_a2"
        assert diagram.parent["srv_srv_a1"] == "rack_rack_a"
        assert diagram.parent["rack_rack_a"] is None
        assert diagram.parent["svc_api"] == "srv_srv_b1"
        assert diagram.parent["srv_srv_b1"] == "rack_rack_b"

    def test_pipelines_are_grouped(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        pipelines = [n for n in diagram.nodes if n.startswith("pl_")]
        assert len(pipelines) == 4
        assert {diagram.parent[n] for n in pipelines} == {"grp_pipelines"}

    def test_shapes_follow_the_kind_of_component(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        assert diagram.nodes["svc_kafka"] == '("kafka")'
        assert diagram.nodes["pl_orders_ingest"].startswith('{{"orders-ingest')

    def test_pipelines_show_the_version_of_their_schema(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        assert diagram.nodes["pl_orders_ingest"] == '{{"orders-ingest<br/>schema 1.2.0"}}'

    def test_hosting_is_expressed_by_nesting_not_by_arrows(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        expected = [
            (u, v) for u, v, d in mini_dc.graph.edges(data=True) if d["relation"] != "hosts"
        ]
        assert len(diagram.edges) == len(expected) == 11
        assert {label for _, _, label in diagram.edges} == {
            "runs",
            "feeds",
            "runtime",
            "data",
            "network",
        }

    def test_arrows_follow_the_direction_of_impact(self, mini_dc: LoadedDatacenter) -> None:
        edges = parse(to_mermaid(mini_dc.graph)).edges
        assert ("svc_kafka", "pl_orders_ingest", "runs") in edges
        assert ("pl_orders_ingest", "pl_orders_enriched", "feeds") in edges
        # "api depends on postgres" is drawn from the provider to its dependent
        assert ("svc_postgres", "svc_api", "runtime") in edges

    def test_everything_that_is_referenced_is_declared(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        for source, target, _ in diagram.edges:
            assert {source, target} <= diagram.declared
        assert set(diagram.node_class) <= set(diagram.nodes)
        assert set(diagram.styles) <= set(diagram.subgraphs)

    def test_one_class_per_leaf_and_a_style_per_container(self, mini_dc: LoadedDatacenter) -> None:
        diagram = parse(to_mermaid(mini_dc.graph))
        assert set(diagram.node_class) == set(diagram.nodes)
        assert set(diagram.node_class.values()) == {"service", "pipeline"}
        assert set(diagram.styles) == {
            "rack_rack_a",
            "rack_rack_b",
            "srv_srv_a1",
            "srv_srv_a2",
            "srv_srv_b1",
        }
        assert diagram.link_styles == {}

    def test_output_is_deterministic(self, mini_dc: LoadedDatacenter) -> None:
        assert to_mermaid(mini_dc.graph) == to_mermaid(mini_dc.graph)

    def test_golden(self, mini_dc: LoadedDatacenter) -> None:
        assert_text_golden("mermaid_mini_datacenter.mmd", to_mermaid(mini_dc.graph))


class TestMermaidPitfalls:
    def test_no_statement_ends_with_a_semicolon_after_a_colour(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        # Mermaid reads "#" + word characters + ";" as an HTML entity: "fill:#f00;" breaks.
        highlight = MermaidHighlight.from_impact(impact_report(mini_dc, examples_dir))
        for text in (to_mermaid(mini_dc.graph), to_mermaid(mini_dc.graph, highlight)):
            assert set(re.findall(r"#\w+;", text)) <= {"#quot;", "#lt;", "#gt;"}
            assert not any(line.endswith(";") for line in text.splitlines())

    def test_hostile_ids_cannot_break_the_diagram(self, mini_dc: LoadedDatacenter) -> None:
        names = [
            "end",
            "graph",
            "subgraph",
            "style",
            "class",
            "classDef",
            "click",
            "default",
            "linkStyle",
            "flowchart",
            "direction",
            "a.b",
            "a-b",
            "a_b",
            "0",
            "o",
            "x",
        ]

        def mutate(data: dict[str, Any]) -> None:
            srv_b1(data)["services"].extend(
                {"id": name, "cpu_cores": 0, "memory_gb": 0} for name in names
            )

        graph = load_variant(mutate).graph
        diagram = parse(to_mermaid(graph))
        generated = set(diagram.declared)
        assert generated.isdisjoint(RESERVED)
        assert all(re.fullmatch(r"(rack|srv|svc|pl)_\w+|grp_pipelines", i) for i in generated)
        # the three ids that collapse to the same text stay distinct, and keep their labels
        collisions = [i for i in diagram.nodes if i.startswith("svc_a_b")]
        assert len(collisions) == 3
        assert {diagram.nodes[i] for i in collisions} == {'("a.b")', '("a-b")', '("a_b")'}

    def test_empty_containers_are_drawn_as_nodes(self, mini_dc: LoadedDatacenter) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["racks"].append({"id": "rack-empty", "power_capacity_kw": 1})
            data["racks"][1]["servers"].append(
                {"id": "srv-empty", "cpu_cores": 1, "memory_gb": 1, "power_kw": 0}
            )

        diagram = parse(to_mermaid(load_variant(mutate).graph))
        assert diagram.nodes["rack_rack_empty"] == '["rack-empty"]'
        assert diagram.nodes["srv_srv_empty"] == '["srv-empty"]'
        assert diagram.node_class["rack_rack_empty"] == "rack"
        assert diagram.node_class["srv_srv_empty"] == "server"
        assert all(count > 0 for count in diagram.children.values())

    def test_a_datacenter_without_pipelines_has_no_pipeline_group(self) -> None:
        def mutate(data: dict[str, Any]) -> None:
            data["pipelines"] = []
            data["dependencies"] = [d for d in data["dependencies"] if d["target"] == "postgres"]

        diagram = parse(to_mermaid(load_variant(mutate).graph))
        assert "grp_pipelines" not in diagram.subgraphs

    def test_labels_are_escaped(self) -> None:
        graph: nx.DiGraph[str] = nx.DiGraph(name="x")
        graph.add_node('say "hi" <b>', kind=NodeKind.SERVICE)
        text = to_mermaid(graph)
        assert "#quot;hi#quot; #lt;b#gt;" in text
        parse(text)

    def test_the_name_comment_stays_on_one_line(self) -> None:
        graph: nx.DiGraph[str] = nx.DiGraph(name="first\nsecond   line")
        graph.add_node("a", kind=NodeKind.SERVICE)
        assert parse(to_mermaid(graph)).comments == ["%% first second line"]

    def test_a_graph_without_names_or_nodes_is_still_valid(self) -> None:
        diagram = parse(to_mermaid(nx.DiGraph()))
        assert diagram.nodes == {}
        assert diagram.edges == []
        assert diagram.comments == []


class TestImpactHighlight:
    def classes(self, mini_dc: LoadedDatacenter, examples_dir: Path, change: str) -> dict[str, str]:
        report = impact_report(mini_dc, examples_dir, change)
        diagram = parse(to_mermaid(mini_dc.graph, MermaidHighlight.from_impact(report)))
        return diagram.node_class

    def test_changed_broken_and_at_risk_nodes_get_their_own_class(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        classes = self.classes(mini_dc, examples_dir, "orders_v2")
        assert classes["pl_orders_ingest"] == "changed"
        assert {classes[n] for n in ("pl_orders_enriched", "pl_customer_360")} == {"broken"}
        assert {classes[n] for n in ("svc_api", "svc_dashboard", "pl_revenue_daily")} == {"atRisk"}
        # nothing upstream of the change is highlighted
        assert classes["svc_kafka"] == "service"
        assert classes["svc_postgres"] == "service"

    def test_a_compatible_change_only_marks_what_is_reachable(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        classes = self.classes(mini_dc, examples_dir, "orders_v1_3_0")
        assert classes["pl_orders_ingest"] == "changed"
        assert {classes[n] for n in ("pl_orders_enriched", "svc_api", "svc_dashboard")} == {
            "affected"
        }
        assert "broken" not in classes.values()
        assert "atRisk" not in classes.values()

    def test_a_partial_break_does_not_color_what_is_unaffected(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        classes = self.classes(mini_dc, examples_dir, "orders_sneaky_patch")
        assert classes["pl_customer_360"] == "broken"
        assert classes["svc_api"] == "atRisk"
        assert classes["pl_orders_enriched"] == "affected"

    def test_arrows_on_impact_paths_are_styled_by_the_status_of_their_target(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        report = impact_report(mini_dc, examples_dir)
        diagram = parse(to_mermaid(mini_dc.graph, MermaidHighlight.from_impact(report)))
        styled = {diagram.edges[i][:2]: style for i, style in diagram.link_styles.items()}
        assert set(styled) == {
            ("pl_orders_ingest", "pl_orders_enriched"),
            ("pl_orders_ingest", "pl_customer_360"),
            ("pl_orders_enriched", "pl_revenue_daily"),
            ("pl_revenue_daily", "svc_dashboard"),
            ("pl_customer_360", "svc_api"),
        }
        red, orange = "stroke:#c62828,stroke-width:3px", "stroke:#ef6c00,stroke-width:3px"
        assert styled[("pl_orders_ingest", "pl_orders_enriched")] == red
        assert styled[("pl_orders_ingest", "pl_customer_360")] == red
        assert styled[("pl_orders_enriched", "pl_revenue_daily")] == orange
        assert styled[("pl_customer_360", "svc_api")] == orange

    def test_link_indexes_refer_to_the_arrows_that_are_drawn(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        report = impact_report(mini_dc, examples_dir)
        diagram = parse(to_mermaid(mini_dc.graph, MermaidHighlight.from_impact(report)))
        assert diagram.link_styles
        assert all(0 <= index < len(diagram.edges) for index in diagram.link_styles)

    def test_the_comment_states_the_severity(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        report = impact_report(mini_dc, examples_dir)
        diagram = parse(to_mermaid(mini_dc.graph, MermaidHighlight.from_impact(report)))
        assert "%% impact of changing orders-ingest: critical" in diagram.comments

    def test_the_highlighted_diagram_has_the_same_shape_as_the_plain_one(
        self, mini_dc: LoadedDatacenter, examples_dir: Path
    ) -> None:
        report = impact_report(mini_dc, examples_dir)
        plain = parse(to_mermaid(mini_dc.graph))
        highlighted = parse(to_mermaid(mini_dc.graph, MermaidHighlight.from_impact(report)))
        assert plain.edges == highlighted.edges
        assert plain.parent == highlighted.parent
        assert plain.nodes == highlighted.nodes

    def test_golden(self, mini_dc: LoadedDatacenter, examples_dir: Path) -> None:
        highlight = MermaidHighlight.from_impact(impact_report(mini_dc, examples_dir))
        assert_text_golden("mermaid_impact_orders_v2.mmd", to_mermaid(mini_dc.graph, highlight))
