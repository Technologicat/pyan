"""Tests for the sans-IO from_sources API (#101)."""

import ast

from pyan.analyzer import CallGraphVisitor
from pyan.main import create_callgraph
from pyan.modvis import ImportVisitor, create_modulegraph

SOURCE_A = """\
import mod_b

def greet(name):
    return hello(name)

def hello(name):
    return f"Hello, {name}!"
"""

SOURCE_B = """\
from mod_a import greet

def main():
    greet("world")
"""

ENUM_SOURCE = """\
from enum import Enum

class Color(Enum):
    RED = 1

def use_color():
    return Color.RED
"""


class TestFromSourcesBasic:
    def test_single_module_text(self):
        """Analyze a single module from source text."""
        v = CallGraphVisitor.from_sources([
            (SOURCE_A, "mod_a"),
        ])
        names = {n.get_name() for ns in v.nodes.values() for n in ns if n.defined}
        assert "mod_a.greet" in names
        assert "mod_a.hello" in names

    def test_single_module_ast(self):
        """Analyze a single module from a pre-parsed AST."""
        tree = ast.parse(SOURCE_A)
        v = CallGraphVisitor.from_sources([
            (tree, "mod_a"),
        ])
        names = {n.get_name() for ns in v.nodes.values() for n in ns if n.defined}
        assert "mod_a.greet" in names
        assert "mod_a.hello" in names

    def test_uses_edges(self):
        """Uses edges should be detected from source text."""
        v = CallGraphVisitor.from_sources([
            (SOURCE_A, "mod_a"),
        ])
        greet_uses = {n.get_name() for n in v.uses_edges.get(
            v.get_node("mod_a", "greet"), []
        )}
        assert "mod_a.hello" in greet_uses


class TestFromSourcesMultiModule:
    def test_cross_module_edge(self):
        """Cross-module uses edges should work with from_sources."""
        v = CallGraphVisitor.from_sources([
            (SOURCE_A, "mod_a"),
            (SOURCE_B, "mod_b"),
        ])
        main_uses = {n.get_name() for n in v.uses_edges.get(
            v.get_node("mod_b", "main"), []
        )}
        assert "mod_a.greet" in main_uses


class TestFromSourcesMixedInput:
    def test_mixed_text_and_ast(self):
        """Accept a mix of source text and AST objects."""
        tree_a = ast.parse(SOURCE_A)
        v = CallGraphVisitor.from_sources([
            (tree_a, "mod_a"),
            (SOURCE_B, "mod_b"),
        ])
        names = {n.get_name() for ns in v.nodes.values() for n in ns if n.defined}
        assert "mod_a.greet" in names
        assert "mod_b.main" in names


class TestCreateCallgraphSources:
    def test_text_output(self):
        """create_callgraph(sources=...) should produce text output."""
        result = create_callgraph(
            sources=[(SOURCE_A, "mod_a")],
            format="text",
        )
        assert "greet" in result
        assert "hello" in result

    def test_dot_output(self):
        """create_callgraph(sources=...) should produce DOT output."""
        result = create_callgraph(
            sources=[(SOURCE_A, "mod_a")],
            format="dot",
            nested_groups=False,
            grouped=False,
        )
        assert "digraph G" in result

    def test_sources_overrides_filenames(self):
        """When sources is given, filenames is ignored."""
        result = create_callgraph(
            filenames="nonexistent/**/*.py",
            sources=[(SOURCE_A, "mod_a")],
            format="text",
        )
        assert "greet" in result


# --- Module-graph from_sources ---

class TestImportVisitorFromSources:
    def test_discovers_imports(self):
        """ImportVisitor.from_sources should detect import dependencies."""
        v = ImportVisitor.from_sources([
            (SOURCE_A, "mod_a"),
            (SOURCE_B, "mod_b"),
        ])
        assert "mod_a" in v.modules.get("mod_b", set())

    def test_ast_input(self):
        """ImportVisitor.from_sources should accept ast.Module objects."""
        tree = ast.parse(SOURCE_B)
        v = ImportVisitor.from_sources([
            (SOURCE_A, "mod_a"),
            (tree, "mod_b"),
        ])
        assert "mod_a" in v.modules.get("mod_b", set())


    def test_relative_import(self):
        """Relative imports (from . import ...) should resolve correctly in source mode."""
        src_alpha = "def greet(): pass\n"
        src_beta = "from . import alpha\ndef main(): alpha.greet()\n"
        v = ImportVisitor.from_sources([
            (src_alpha, "pkg.alpha"),
            (src_beta, "pkg.beta"),
        ])
        assert "pkg.alpha" in v.modules.get("pkg.beta", set())


class TestCreateModulegraphSources:
    def test_text_output(self):
        """create_modulegraph(sources=...) should produce text output."""
        # Both modules must have imports to appear as nodes in the module graph.
        result = create_modulegraph(
            sources=[(SOURCE_A, "mod_a"), (SOURCE_B, "mod_b")],
            format="text",
        )
        # mod_b imports mod_a, so mod_b appears; mod_a has no imports
        # of its own, so only mod_b is a key in self.modules.
        assert "mod_b" in result

    def test_sources_overrides_filenames(self):
        """When sources is given, filenames is ignored."""
        result = create_modulegraph(
            filenames="nonexistent/**/*.py",
            sources=[(SOURCE_A, "mod_a"), (SOURCE_B, "mod_b")],
            format="text",
        )
        assert "mod_b" in result
