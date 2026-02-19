"""Tests for modvis.py — module-level import dependency analyzer."""

import logging
import os
import sys

import pytest

# modvis.py lives at repo root, not inside the pyan package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from modvis import (
    ImportVisitor,
    filename_to_module_name,
    main,
    resolve,
    split_module_name,
)


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

class TestFilenameToModuleName:
    def test_simple(self):
        assert filename_to_module_name("foo.py") == "foo"

    def test_nested(self):
        assert filename_to_module_name(os.path.join("some", "path", "module.py")) == "some.path.module"

    def test_strip_dot_slash(self):
        assert filename_to_module_name(os.path.join(".", "pkg", "mod.py")) == "pkg.mod"

    def test_init(self):
        assert filename_to_module_name(os.path.join("pkg", "__init__.py")) == "pkg.__init__"

    def test_rejects_non_py(self):
        with pytest.raises(ValueError, match="Expected a .py filename"):
            filename_to_module_name("module.txt")


class TestSplitModuleName:
    def test_dotted(self):
        assert split_module_name("fully.qualified.name") == ("fully.qualified", "name")

    def test_simple(self):
        assert split_module_name("name") == ("", "name")

    def test_single_dot(self):
        assert split_module_name("pkg.mod") == ("pkg", "mod")


class TestResolve:
    def test_absolute(self):
        assert resolve("anything", "os.path", 0) == "os.path"

    def test_relative_level1(self):
        assert resolve("pkg.sub.mod", "sibling", 1) == "pkg.sub.sibling"

    def test_relative_level2(self):
        assert resolve("pkg.sub.mod", "other", 2) == "pkg.other"

    def test_relative_level3_to_top(self):
        assert resolve("pkg.sub.mod", "top", 3) == ".top"

    def test_negative_level(self):
        with pytest.raises(ValueError, match="must be >= 0"):
            resolve("pkg.mod", "target", -1)

    def test_level_too_large(self):
        with pytest.raises(ValueError, match="too large"):
            resolve("pkg.mod", "target", 5)


# ---------------------------------------------------------------------------
# ImportVisitor
# ---------------------------------------------------------------------------

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "test_code_modvis")


def fixture_files():
    """Collect all .py files in the fixture directory."""
    result = []
    for root, _dirs, files in os.walk(FIXTURE_DIR):
        for f in files:
            if f.endswith(".py"):
                result.append(os.path.join(root, f))
    return sorted(result)


@pytest.fixture
def visitor():
    """Create an ImportVisitor over the modvis test fixtures."""
    logger = logging.getLogger("test_modvis")
    logger.setLevel(logging.WARNING)
    # ImportVisitor uses filename_to_module_name, which expects paths
    # relative to cwd. Run from fixture dir.
    old_cwd = os.getcwd()
    os.chdir(FIXTURE_DIR)
    try:
        files = fixture_files()
        rel_files = [os.path.relpath(f, FIXTURE_DIR) for f in files]
        v = ImportVisitor(rel_files, logger)
    finally:
        os.chdir(old_cwd)
    return v


class TestImportVisitor:
    def test_discovers_all_modules(self, visitor):
        expected = {
            "pkg_a.__init__",
            "pkg_a.alpha",
            "pkg_b.__init__",
            "pkg_b.beta",
            "pkg_b.gamma",
        }
        assert set(visitor.modules.keys()) == expected

    def test_absolute_import(self, visitor):
        # alpha.py: import pkg_b.beta
        assert "pkg_b.beta" in visitor.modules["pkg_a.alpha"]

    def test_from_import(self, visitor):
        # alpha.py: from pkg_b import gamma  →  registers pkg_b as dependency
        # (modvis tracks module-level deps, not individual symbols)
        assert "pkg_b" in visitor.modules["pkg_a.alpha"]

    def test_relative_import(self, visitor):
        # pkg_b/beta.py: from . import gamma
        assert "pkg_b.gamma" in visitor.modules["pkg_b.beta"]

    def test_relative_import_in_init(self, visitor):
        # pkg_a/__init__.py: from . import alpha
        assert "pkg_a.alpha" in visitor.modules["pkg_a.__init__"]

    def test_implicit_init_dependency(self, visitor):
        # alpha.py imports pkg_b.beta, so modvis adds pkg_b.__init__ as implicit dep
        assert "pkg_b.__init__" in visitor.modules["pkg_a.alpha"]

    def test_detect_cycles(self, visitor):
        cycles = visitor.detect_cycles()
        assert len(cycles) > 0
        # There should be a cycle involving alpha and gamma
        cycle_modules = set()
        for _prefix, cycle in cycles:
            cycle_modules.update(cycle)
        assert "pkg_a.alpha" in cycle_modules
        assert "pkg_b.gamma" in cycle_modules

    def test_prepare_graph_nodes(self, visitor):
        visitor.prepare_graph()
        assert "pkg_a.alpha" in visitor.nodes
        assert "pkg_b.beta" in visitor.nodes
        for name, node_list in visitor.nodes.items():
            assert len(node_list) == 1
            assert node_list[0].defined is True

    def test_prepare_graph_edges(self, visitor):
        visitor.prepare_graph()
        # Find the alpha node and check it has outgoing edges
        alpha_node = visitor.nodes["pkg_a.alpha"][0]
        assert alpha_node in visitor.uses_edges
        target_names = {n.get_name() for n in visitor.uses_edges[alpha_node]}
        assert "pkg_b.beta" in target_names or "pkg_b.gamma" in target_names


# ---------------------------------------------------------------------------
# CLI (smoke tests)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "approximate module" in captured.out

    def test_no_args_errors(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_dot_output(self, capsys):
        old_cwd = os.getcwd()
        os.chdir(FIXTURE_DIR)
        try:
            files = [os.path.relpath(f, FIXTURE_DIR)
                     for f in fixture_files()]
            main(files + ["--dot"])
        finally:
            os.chdir(old_cwd)
        captured = capsys.readouterr()
        assert "digraph G" in captured.out

    def test_cycles_output(self, capsys):
        old_cwd = os.getcwd()
        os.chdir(FIXTURE_DIR)
        try:
            files = [os.path.relpath(f, FIXTURE_DIR)
                     for f in fixture_files()]
            main(files + ["--cycles"])
        finally:
            os.chdir(old_cwd)
        captured = capsys.readouterr()
        assert "import cycles" in captured.out.lower() or "cycle" in captured.out.lower()
