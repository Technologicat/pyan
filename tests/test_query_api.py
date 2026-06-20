"""Tests for the analyzer's query API.

These tests exercise the post-analysis API that callers use to interrogate
the graph — directional traversal, call-path enumeration, and depth-based
collapsing. They do not exercise AST recognition (see test_classes.py,
test_functions.py, and the other syntax-coverage files for that); they
assume an already-built graph and verify how it answers questions.

Covered:

- ``get_related_nodes(direction=...)`` — #95
- ``find_paths`` / ``format_paths`` — #12
- ``filter_by_depth`` — #80, including the dotted-module-name regression
"""

from glob import glob
import logging
import os

import pytest

from pyan.analyzer import CallGraphVisitor

TESTS_DIR = os.path.dirname(__file__)


@pytest.fixture
def v_multi():
    """Analyzer over the full test_code package (cross-module calls)."""
    filenames = glob(os.path.join(TESTS_DIR, "test_code/**/*.py"), recursive=True)
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


# --- Directional filtering (#95) ---

CALLER = "test_code.submodule2.test_2"        # calls test_func1
CALLEE = "test_code.submodule1.test_func1"     # called by test_2


def test_direction_down_finds_callees(v_multi):
    """direction='down' from test_2 should include test_func1 (a callee)."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="down")
    names = {n.get_name() for n in related}
    assert CALLEE in names


def test_direction_down_excludes_callers(v_multi):
    """direction='down' from test_func1 should NOT include test_2 (a caller)."""
    node = v_multi.get_node("test_code.submodule1", "test_func1")
    related = v_multi.get_related_nodes(node, direction="down")
    names = {n.get_name() for n in related}
    assert CALLER not in names


def test_direction_up_finds_callers(v_multi):
    """direction='up' from test_func1 should include test_2 (a caller)."""
    node = v_multi.get_node("test_code.submodule1", "test_func1")
    related = v_multi.get_related_nodes(node, direction="up")
    names = {n.get_name() for n in related}
    assert CALLER in names


def test_direction_up_excludes_callees(v_multi):
    """direction='up' from test_2 should NOT include test_func1 (a callee)."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="up")
    names = {n.get_name() for n in related}
    assert CALLEE not in names


def test_direction_both_finds_both(v_multi):
    """direction='both' from test_2 should include both callers and callees."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="both")
    names = {n.get_name() for n in related}
    assert CALLEE in names


# --- Call path listing (#12) ---

def test_find_paths_direct(v_multi):
    """find_paths should find a direct edge as a single-hop path."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node)
    path_strs = [" -> ".join(n.get_name() for n in p) for p in paths]
    assert any("test_2" in s and "test_func1" in s for s in path_strs)


def test_find_paths_multi_hop():
    """find_paths should find a two-hop path: Derived.baz -> Base.bar -> Base.foo."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    from_node = v.get_node("test_code.features.Derived", "baz")
    to_node = v.get_node("test_code.features.Base", "foo")
    paths = v.find_paths(from_node, to_node)
    assert len(paths) >= 1
    # The two-hop path should go through bar
    path_names = [[n.get_name() for n in p] for p in paths]
    assert any("test_code.features.Base.bar" in p for p in path_names)


def test_find_paths_no_path(v_multi):
    """find_paths should return empty list when no path exists."""
    # test_func1 does not call test_2
    from_node = v_multi.get_node("test_code.submodule1", "test_func1")
    to_node = v_multi.get_node("test_code.submodule2", "test_2")
    paths = v_multi.find_paths(from_node, to_node)
    assert paths == []


def test_find_paths_max_paths(v_multi):
    """find_paths respects max_paths limit."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node, max_paths=1)
    assert len(paths) <= 1


def test_format_paths(v_multi):
    """format_paths produces the expected text format."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node)
    text = v_multi.format_paths(paths)
    assert " -> " in text
    assert "test_2" in text
    assert "test_func1" in text


# --- Depth filtering (#80) ---

def test_depth_class_level_collapses_methods():
    """depth=1 should collapse methods into their class."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    v.filter_by_depth(1)

    # Methods should be gone
    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.features.Base.foo" not in names
    assert "test_code.features.Base.bar" not in names
    # Classes should remain
    assert "test_code.features.Base" in names
    assert "test_code.features.Derived" in names


def test_depth_class_level_collapses_edges():
    """depth=1 should collapse method→method edges to class→class edges."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    v.filter_by_depth(1)

    # Derived.baz → Base.bar should become Derived → Base
    derived_node = None
    base_node = None
    for nodes in v.nodes.values():
        for n in nodes:
            if n.get_name() == "test_code.features.Derived":
                derived_node = n
            if n.get_name() == "test_code.features.Base":
                base_node = n
    assert derived_node is not None
    assert base_node is not None
    assert derived_node in v.uses_edges
    target_names = {n.get_name() for n in v.uses_edges[derived_node]}
    assert "test_code.features.Base" in target_names


def test_depth_module_level():
    """depth=0 should show only modules, collapsing everything deeper."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    v.filter_by_depth(0)

    # Only the module itself should remain as a defined node
    defined_names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.features" in defined_names
    for name in defined_names:
        assert name in v.module_to_filename, f"Node {name} should be a module at depth 0"


def test_depth_module_level_cross_module(v_multi):
    """depth=0 with multi-module input should collapse function edges to module edges."""
    v_multi.filter_by_depth(0)

    # Functions should be gone, modules should remain
    names = {n.get_name() for nodes in v_multi.nodes.values() for n in nodes if n.defined}
    assert "test_code.submodule2" in names
    assert "test_code.submodule1" in names
    assert "test_code.submodule2.test_2" not in names

    # Uses edges should be remapped: test_2 → test_func1 becomes submodule2 → submodule1
    all_uses_targets = {}
    for src, tgts in v_multi.uses_edges.items():
        all_uses_targets[src.get_name()] = {t.get_name() for t in tgts}
    assert "test_code.submodule1" in all_uses_targets.get("test_code.submodule2", set()), \
        "Cross-module uses edge should survive depth collapsing"


def test_depth_dotted_module_uses_edges():
    """Uses edges must survive depth collapsing even when module names contain dots.

    The old implementation counted raw dots in the fully qualified name, so a
    class in ``pkg.mod`` was treated as depth 2 instead of depth 1. This caused
    the ancestor lookup to create phantom nodes (wrong namespace/name split),
    which had ``defined=False`` and were silently dropped by ``remap_edges``.
    """
    filenames = [
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_a.py"),
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_b.py"),
    ]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())

    # Depth 1: methods collapse into classes; classes and modules remain
    v.filter_by_depth(1)

    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.depth_pkg.mod_a.ClassA" in names
    assert "test_code.depth_pkg.mod_b.ClassB" in names
    assert "test_code.depth_pkg.mod_a.ClassA.method_a" not in names  # collapsed

    # The critical check: ClassA.method_a → ClassB should become ClassA → ClassB
    uses_map = {src.get_name(): {t.get_name() for t in tgts}
                for src, tgts in v.uses_edges.items()}
    assert "test_code.depth_pkg.mod_b.ClassB" in uses_map.get("test_code.depth_pkg.mod_a.ClassA", set()), \
        "Cross-module uses edge must survive depth collapsing with dotted module names"


def test_depth_dotted_module_depth_zero():
    """Depth 0 with dotted module names should collapse everything to modules."""
    filenames = [
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_a.py"),
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_b.py"),
    ]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    v.filter_by_depth(0)

    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.depth_pkg.mod_a" in names
    assert "test_code.depth_pkg.mod_b" in names
    assert "test_code.depth_pkg.mod_a.ClassA" not in names  # collapsed

    uses_map = {src.get_name(): {t.get_name() for t in tgts}
                for src, tgts in v.uses_edges.items()}
    assert "test_code.depth_pkg.mod_b" in uses_map.get("test_code.depth_pkg.mod_a", set()), \
        "Cross-module uses edge must survive depth-0 collapsing with dotted module names"


def test_depth_no_self_edges():
    """Collapsing should not create self-edges (e.g. Base.bar → Base.foo → Base)."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    v.filter_by_depth(1)

    for n, edges in v.uses_edges.items():
        assert n not in edges, f"Self-edge on {n.get_name()}"
