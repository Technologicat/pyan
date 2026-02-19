"""Tests for output format writers (DOT, TGF, yEd GraphML, SVG, HTML)."""

import io
import logging
import shutil
import xml.etree.ElementTree as ET
from glob import glob
import os

import pytest

from pyan.analyzer import CallGraphVisitor
from pyan.visgraph import VisualGraph
from pyan.writers import DotWriter, HTMLWriter, SVGWriter, TgfWriter, YedWriter


has_dot = shutil.which("dot") is not None


@pytest.fixture
def graph():
    """Build a VisualGraph from the standard test_code fixtures."""
    filenames = glob(os.path.join(os.path.dirname(__file__), "test_code/**/*.py"), recursive=True)
    visitor = CallGraphVisitor(filenames, logger=logging.getLogger())
    options = {
        "draw_defines": True,
        "draw_uses": True,
        "colored": True,
        "grouped_alt": False,
        "grouped": True,
        "nested_groups": True,
        "annotated": False,
    }
    return VisualGraph.from_visitor(visitor, options=options, logger=logging.getLogger())


# ---------------------------------------------------------------------------
# DOT
# ---------------------------------------------------------------------------

class TestDotWriter:
    def test_valid_structure(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, options=["rankdir=TB"], output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert dot.startswith("digraph G {")
        assert dot.rstrip().endswith("}")

    def test_contains_nodes(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        # Should contain at least one node with a label
        assert "label=" in dot

    def test_contains_edges(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert "->" in dot

    def test_defines_edges_dashed(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert 'style="dashed"' in dot

    def test_uses_edges_solid(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert 'style="solid"' in dot

    def test_subgraphs_when_grouped(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert "subgraph cluster_" in dot

    def test_rankdir_option(self, graph):
        buf = io.StringIO()
        writer = DotWriter(graph, options=["rankdir=LR"], output=buf, logger=logging.getLogger())
        writer.run()
        dot = buf.getvalue()
        assert "rankdir=LR" in dot


# ---------------------------------------------------------------------------
# TGF
# ---------------------------------------------------------------------------

class TestTgfWriter:
    def test_valid_structure(self, graph):
        buf = io.StringIO()
        writer = TgfWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        tgf = buf.getvalue()
        lines = tgf.strip().split("\n")
        # TGF has nodes, then a "#" separator, then edges
        separator_indices = [i for i, line in enumerate(lines) if line.strip() == "#"]
        assert len(separator_indices) == 1

    def test_nodes_before_separator(self, graph):
        buf = io.StringIO()
        writer = TgfWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        tgf = buf.getvalue()
        lines = tgf.strip().split("\n")
        sep_idx = next(i for i, line in enumerate(lines) if line.strip() == "#")
        # Node lines should have "id label" format
        for line in lines[:sep_idx]:
            parts = line.strip().split(None, 1)
            assert len(parts) == 2
            assert parts[0].isdigit()

    def test_edges_after_separator(self, graph):
        buf = io.StringIO()
        writer = TgfWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        tgf = buf.getvalue()
        lines = tgf.strip().split("\n")
        sep_idx = next(i for i, line in enumerate(lines) if line.strip() == "#")
        edge_lines = [l for l in lines[sep_idx + 1:] if l.strip()]
        assert len(edge_lines) > 0
        # Edge lines: "source_id target_id flavor"
        for line in edge_lines:
            parts = line.strip().split()
            assert len(parts) == 3
            assert parts[0].isdigit()
            assert parts[1].isdigit()
            assert parts[2] in ("U", "D")


# ---------------------------------------------------------------------------
# yEd GraphML
# ---------------------------------------------------------------------------

class TestYedWriter:
    def test_valid_xml(self, graph):
        buf = io.StringIO()
        writer = YedWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        xml_str = buf.getvalue()
        # Should parse as valid XML
        root = ET.fromstring(xml_str)
        assert root.tag.endswith("graphml")

    def test_contains_nodes_and_edges(self, graph):
        buf = io.StringIO()
        writer = YedWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        xml_str = buf.getvalue()
        root = ET.fromstring(xml_str)
        # Use namespace-agnostic search
        all_tags = {elem.tag.split("}")[-1] for elem in root.iter()}
        assert "node" in all_tags
        assert "edge" in all_tags


# ---------------------------------------------------------------------------
# SVG (requires graphviz `dot` binary)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not has_dot, reason="graphviz dot not installed")
class TestSVGWriter:
    def test_valid_svg_xml(self, graph):
        buf = io.StringIO()
        writer = SVGWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        svg = buf.getvalue()
        root = ET.fromstring(svg)
        assert root.tag.endswith("svg")

    def test_contains_graph_elements(self, graph):
        buf = io.StringIO()
        writer = SVGWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        svg = buf.getvalue()
        # SVG from dot contains <g> groups and <text> elements
        assert "<g" in svg
        assert "<text" in svg


# ---------------------------------------------------------------------------
# HTML (requires graphviz `dot` binary)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not has_dot, reason="graphviz dot not installed")
class TestHTMLWriter:
    def test_valid_html_structure(self, graph):
        buf = io.StringIO()
        writer = HTMLWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        html = buf.getvalue()
        assert "<html" in html.lower()
        assert "<svg" in html.lower()
        assert "</html>" in html.lower()

    def test_contains_embedded_svg(self, graph):
        buf = io.StringIO()
        writer = HTMLWriter(graph, output=buf, logger=logging.getLogger())
        writer.run()
        html = buf.getvalue()
        # The SVG should contain graph content (not just an empty SVG)
        assert "<text" in html
