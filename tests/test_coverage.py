"""Tests targeting coverage gaps in node.py, main.py, and __init__.py."""

import ast
import io
import logging
import os

import pytest

from pyan.main import main as pyan_main
from pyan.node import Flavor, Node, make_safe_label

TESTS_DIR = os.path.dirname(__file__)
FIXTURE = os.path.join(TESTS_DIR, "test_code/features.py")
FIXTURE_DIR = os.path.join(TESTS_DIR, "test_code_modvis")


# ---------------------------------------------------------------------------
# node.py coverage
# ---------------------------------------------------------------------------

class TestNodeLabels:
    """Cover get_short_name, get_annotated_name, get_long_annotated_name
    for wildcard (namespace=None) and top-level (namespace='') nodes."""

    def test_short_name_wildcard(self):
        n = Node(None, "foo", None, "test.py", Flavor.UNKNOWN)
        assert n.get_short_name() == "*.foo"

    def test_short_name_normal(self):
        n = Node("pkg", "foo", None, "test.py", Flavor.FUNCTION)
        assert n.get_short_name() == "foo"

    def test_annotated_name_wildcard(self):
        n = Node(None, "foo", None, "test.py", Flavor.UNKNOWN)
        assert n.get_annotated_name() == "*.foo"

    def test_annotated_name_with_ast_node(self):
        ast_node = ast.parse("pass").body[0]
        n = Node("pkg.mod", "foo", ast_node, "test.py", Flavor.FUNCTION)
        result = n.get_annotated_name()
        assert "foo" in result
        assert "test.py" in result

    def test_annotated_name_top_level(self):
        n = Node("", "foo", None, "test.py", Flavor.FUNCTION)
        assert n.get_annotated_name() == "foo"

    def test_long_annotated_name_wildcard(self):
        n = Node(None, "foo", None, "test.py", Flavor.UNKNOWN)
        assert n.get_long_annotated_name() == "*.foo"

    def test_long_annotated_name_with_ast_node(self):
        ast_node = ast.parse("pass").body[0]
        n = Node("pkg.mod", "foo", ast_node, "test.py", Flavor.FUNCTION)
        result = n.get_long_annotated_name()
        assert "foo" in result
        assert "test.py" in result
        assert "pkg.mod" in result

    def test_long_annotated_name_without_ast_node(self):
        n = Node("pkg.mod", "foo", None, "test.py", Flavor.FUNCTION)
        result = n.get_long_annotated_name()
        assert "foo" in result
        assert "pkg.mod" in result

    def test_long_annotated_name_top_level(self):
        n = Node("", "foo", None, "test.py", Flavor.FUNCTION)
        assert n.get_long_annotated_name() == "foo"


class TestNodeNamespace:
    """Cover get_toplevel_namespace edge cases."""

    def test_toplevel_ns_wildcard(self):
        n = Node(None, "foo", None, "test.py", Flavor.UNKNOWN)
        assert n.get_toplevel_namespace() == "*"

    def test_toplevel_ns_empty(self):
        n = Node("", "foo", None, "test.py", Flavor.MODULE)
        assert n.get_toplevel_namespace() == ""

    def test_toplevel_ns_dotted(self):
        n = Node("pkg.sub.mod", "foo", None, "test.py", Flavor.FUNCTION)
        assert n.get_toplevel_namespace() == "pkg"

    def test_toplevel_ns_single(self):
        n = Node("pkg", "foo", None, "test.py", Flavor.FUNCTION)
        assert n.get_toplevel_namespace() == "pkg"


# ---------------------------------------------------------------------------
# main.py CLI coverage
# ---------------------------------------------------------------------------

class TestPyanCLI:
    """Cover CLI code paths in main.py."""

    def test_version(self, capsys):
        pyan_main(["--version"])
        captured = capsys.readouterr()
        assert "pyan3" in captured.out

    def test_no_args_errors(self):
        with pytest.raises(SystemExit) as exc_info:
            pyan_main([])
        assert exc_info.value.code != 0

    def test_dot_output(self, capsys):
        pyan_main([FIXTURE, "--dot"])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out

    def test_tgf_output(self, capsys):
        pyan_main([FIXTURE, "--tgf"])
        captured = capsys.readouterr()
        assert "#" in captured.out

    def test_yed_output(self, capsys):
        pyan_main([FIXTURE, "--yed"])
        captured = capsys.readouterr()
        assert "graphml" in captured.out.lower()

    def test_text_output(self, capsys):
        pyan_main([FIXTURE, "--text"])
        captured = capsys.readouterr()
        assert "[U]" in captured.out or "[D]" in captured.out

    def test_paths_from_to(self, capsys):
        pyan_main([
            FIXTURE, "--paths-from", "test_code.features.Derived.baz",
            "--paths-to", "test_code.features.Base.foo",
        ])
        captured = capsys.readouterr()
        assert "baz" in captured.out
        assert "foo" in captured.out

    def test_paths_no_result(self, capsys):
        pyan_main([
            FIXTURE, "--paths-from", "test_code.features.Base.foo",
            "--paths-to", "test_code.features.Derived.baz",
        ])
        captured = capsys.readouterr()
        assert "No paths found" in captured.out

    def test_paths_from_without_to_errors(self):
        with pytest.raises(SystemExit) as exc_info:
            pyan_main([FIXTURE, "--paths-from", "test_code.features.Base.foo"])
        assert exc_info.value.code != 0

    def test_depth_flag(self, capsys):
        pyan_main([FIXTURE, "--dot", "--depth", "2"])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out

    def test_depth_max(self, capsys):
        pyan_main([FIXTURE, "--dot", "--depth", "max"])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out

    def test_concentrate_flag(self, capsys):
        pyan_main([FIXTURE, "--dot", "--concentrate"])
        captured = capsys.readouterr()
        assert "concentrate=true" in captured.out

    def test_direction_flag(self, capsys):
        pyan_main([
            FIXTURE, "--dot", "--function", "test_code.features.Base.bar",
            "--direction", "down",
        ])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out


# ---------------------------------------------------------------------------
# __init__.py coverage
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# create_callgraph() format dispatch
# ---------------------------------------------------------------------------

class TestCreateCallgraphFormats:
    """Cover all format branches in create_callgraph()."""

    def test_html_format(self):
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="html")
        assert "<html" in result.lower() or "<svg" in result.lower()

    def test_svg_format(self):
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="svg")
        assert "<svg" in result.lower()

    def test_tgf_format(self):
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="tgf")
        assert "#" in result

    def test_yed_format(self):
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="yed")
        assert "graphml" in result.lower()

    def test_text_format(self):
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="text")
        assert "[U]" in result or "[D]" in result

    def test_unknown_format_raises(self):
        from pyan import create_callgraph
        with pytest.raises(ValueError, match="Unknown format"):
            create_callgraph(FIXTURE, format="bogus")


# ---------------------------------------------------------------------------
# __init__.py / __main__.py
# ---------------------------------------------------------------------------

def test_version_available():
    from pyan import __version__
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_main_module_runnable():
    """pyan.__main__ should be importable."""
    import pyan.__main__  # noqa: F401


# ---------------------------------------------------------------------------
# visgraph.py: annotated labels + nested groups
# ---------------------------------------------------------------------------

class TestVisgraphAnnotated:
    def test_annotated_grouped(self):
        """Annotated + grouped uses get_annotated_name for labels."""
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="dot", annotated=True, grouped=True)
        assert "digraph G" in result

    def test_annotated_ungrouped(self):
        """Annotated + ungrouped uses get_long_annotated_name for labels."""
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="dot", annotated=True, grouped=False)
        assert "digraph G" in result

    def test_nested_groups(self):
        """Nested groups creates nested subgraph clusters."""
        from pyan import create_callgraph
        result = create_callgraph(FIXTURE, format="dot", nested_groups=True)
        assert "digraph G" in result
        assert 'subgraph "cluster_' in result
