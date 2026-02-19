"""Tests for pyan.modvis — module-level import dependency analyzer."""

import logging
import os

import pytest

from pyan.modvis import (
    ImportVisitor,
    _infer_root,
    create_modulegraph,
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

    def test_root_strips_prefix(self):
        # Absolute path + root → correct relative module name
        abspath = os.path.join("/project", "src", "pkg", "mod.py")
        assert filename_to_module_name(abspath, root="/project/src") == "pkg.mod"

    def test_root_with_absolute_init(self):
        abspath = os.path.join("/project", "pkg", "__init__.py")
        assert filename_to_module_name(abspath, root="/project") == "pkg.__init__"

    def test_root_with_relative_paths(self):
        # Even when both are relative, root normalizes correctly
        relpath = os.path.join("src", "pkg", "mod.py")
        assert filename_to_module_name(relpath, root="src") == "pkg.mod"


class TestInferRoot:
    def test_infers_fixture_dir(self):
        # Given absolute paths inside the fixture packages,
        # inference should land on FIXTURE_DIR.
        files = fixture_files()
        assert os.path.abspath(_infer_root(files)) == os.path.abspath(FIXTURE_DIR)

    def test_single_file_in_package(self):
        f = os.path.join(FIXTURE_DIR, "pkg_a", "alpha.py")
        # pkg_a has __init__.py, so root should be its parent (FIXTURE_DIR)
        assert os.path.abspath(_infer_root([f])) == os.path.abspath(FIXTURE_DIR)

    def test_single_top_level_file(self, tmp_path):
        # A lone .py file with no __init__.py → root is its directory
        f = tmp_path / "standalone.py"
        f.write_text("")
        assert _infer_root([str(f)]) == str(tmp_path)


class TestSplitModuleName:
    def test_dotted(self):
        assert split_module_name("fully.qualified.name") == ("fully.qualified", "name")

    def test_simple(self):
        assert split_module_name("name") == ("", "name")

    def test_single_dot(self):
        assert split_module_name("pkg.mod") == ("pkg", "mod")


class TestResolve:
    def test_absolute(self):
        assert resolve(current="anything", target="os.path", level=0) == "os.path"

    def test_relative_level1(self):
        assert resolve(current="pkg.sub.mod", target="sibling", level=1) == "pkg.sub.sibling"

    def test_relative_level2(self):
        assert resolve(current="pkg.sub.mod", target="other", level=2) == "pkg.other"

    def test_relative_level3_to_top(self):
        assert resolve(current="pkg.sub.mod", target="top", level=3) == ".top"

    def test_negative_level(self):
        with pytest.raises(ValueError, match="must be >= 0"):
            resolve(current="pkg.mod", target="target", level=-1)

    def test_level_too_large(self):
        with pytest.raises(ValueError, match="too large"):
            resolve(current="pkg.mod", target="target", level=5)


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
    return ImportVisitor(fixture_files(), logger, root=FIXTURE_DIR)


class TestImportVisitor:
    def test_root_inference_matches_explicit(self):
        """ImportVisitor with inferred root produces the same modules as with explicit root."""
        logger = logging.getLogger("test_modvis")
        logger.setLevel(logging.WARNING)
        files = fixture_files()
        v_explicit = ImportVisitor(files, logger, root=FIXTURE_DIR)
        v_inferred = ImportVisitor(files, logger)  # root=None → inferred
        assert set(v_inferred.modules.keys()) == set(v_explicit.modules.keys())

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

    def test_from_import_module(self, visitor):
        # alpha.py: from pkg_b import gamma  →  gamma is a submodule,
        # so both pkg_b and pkg_b.gamma should appear as dependencies
        deps = visitor.modules["pkg_a.alpha"]
        assert "pkg_b" in deps
        assert "pkg_b.gamma" in deps

    def test_from_import_symbol(self, visitor):
        # alpha.py: from pkg_b.gamma import MY_CONST  →  MY_CONST is a symbol,
        # not a module. pkg_b.gamma should appear as the base module dep.
        # The speculative dep "pkg_b.gamma.MY_CONST" will also be in the raw
        # dep set (that's harmless by design — see test_from_import_symbol_no_graph_edge).
        deps = visitor.modules["pkg_a.alpha"]
        assert "pkg_b.gamma" in deps

    def test_from_import_symbol_no_graph_edge(self, visitor):
        # The speculative dep "pkg_b.gamma.MY_CONST" is added to the raw dep
        # set (that's fine), but prepare_graph must not create an edge for it
        # since no module by that name exists in the analyzed set.
        visitor.prepare_graph()
        all_edge_targets = set()
        for targets in visitor.uses_edges.values():
            for t in targets:
                all_edge_targets.add(t.get_name())
        assert "pkg_b.gamma.MY_CONST" not in all_edge_targets

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
        main(fixture_files() + ["--dot", "--root", FIXTURE_DIR])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out

    def test_cycles_output(self, capsys):
        main(fixture_files() + ["--cycles", "--root", FIXTURE_DIR])
        captured = capsys.readouterr()
        assert "import cycles" in captured.out.lower() or "cycle" in captured.out.lower()

    def test_text_output(self, capsys):
        main(fixture_files() + ["--text", "--root", FIXTURE_DIR])
        captured = capsys.readouterr()
        assert "[U]" in captured.out
        # Should not contain spurious deps (prepare_graph filters them)
        assert "MY_CONST" not in captured.out


# ---------------------------------------------------------------------------
# CLI integration (--module-level dispatch through pyan.main)
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    def test_module_level_help(self, capsys):
        """pyan3 --module-level --help dispatches to modvis help."""
        from pyan.main import main as pyan_main
        with pytest.raises(SystemExit) as exc_info:
            pyan_main(["--module-level", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "approximate module" in captured.out

    def test_module_level_dot(self, capsys):
        """pyan3 --module-level produces dot output."""
        from pyan.main import main as pyan_main
        pyan_main(["--module-level"] + fixture_files() + ["--dot", "--root", FIXTURE_DIR])
        captured = capsys.readouterr()
        assert "digraph G" in captured.out


# ---------------------------------------------------------------------------
# Library API
# ---------------------------------------------------------------------------

class TestCreateModulegraph:
    def test_dot_format(self):
        result = create_modulegraph(fixture_files(), root=FIXTURE_DIR, format="dot")
        assert "digraph G" in result

    def test_tgf_format(self):
        result = create_modulegraph(fixture_files(), root=FIXTURE_DIR, format="tgf")
        assert "#" in result  # TGF separator

    def test_yed_format(self):
        result = create_modulegraph(fixture_files(), root=FIXTURE_DIR, format="yed")
        assert "graphml" in result.lower()

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="unknown"):
            create_modulegraph(["nonexistent.py"], format="bogus")

    def test_importable_from_pyan(self):
        """create_modulegraph is re-exported from the pyan package."""
        from pyan import create_modulegraph as cg
        assert callable(cg)
