from glob import glob
import logging
import os

import pytest

from pyan.analyzer import CallGraphVisitor
from pyan.anutils import enclosing_namespaces, parent_namespace, split_qualified_name


def _test_code_filenames():
    return glob(os.path.join(os.path.dirname(__file__), "test_code/**/*.py"), recursive=True)


@pytest.fixture
def callgraph():
    v = CallGraphVisitor(_test_code_filenames(), root=os.path.dirname(__file__), logger=logging.getLogger())
    return v


@pytest.fixture
def callgraph_raw():
    """The same graph, with subsumed edges kept.

    An import that a function in the same module also uses leaves no edge on
    the module node once subsumption culling has run, so whether the import
    *resolved* is no longer observable there. Tests about resolution itself
    need the raw edge set.
    """
    v = CallGraphVisitor(_test_code_filenames(), root=os.path.dirname(__file__),
                         logger=logging.getLogger(), cull_subsumed_edges=False)
    return v


def get_node(nodes, name):
    filtered_nodes = [node for node in nodes if node.get_name() == name]
    assert len(filtered_nodes) == 1, f"Node with name {name} should exist"
    return filtered_nodes[0]


def get_in_dict(node_dict, name):
    return node_dict[get_node(node_dict.keys(), name)]


def test_resolve_import_as(callgraph_raw):
    imports = get_in_dict(callgraph_raw.uses_edges, "test_code.submodule2")
    get_node(imports, "test_code.submodule1")
    assert len(imports) == 1, "only one effective import"

    imports = get_in_dict(callgraph_raw.uses_edges, "test_code.submodule1")
    get_node(imports, "test_code.subpackage1.submodule1.A")
    get_node(imports, "test_code.subpackage1")


def test_import_relative(callgraph_raw):
    imports = get_in_dict(callgraph_raw.uses_edges, "test_code.subpackage1.submodule1")
    get_node(imports, "test_code.submodule2.test_2")


def test_resolve_use_in_class(callgraph):
    uses = get_in_dict(callgraph.uses_edges, "test_code.subpackage1.submodule1.A.__init__")
    get_node(uses, "test_code.submodule2.test_2")


def test_resolve_use_in_function(callgraph):
    uses = get_in_dict(callgraph.uses_edges, "test_code.submodule2.test_2")
    get_node(uses, "test_code.submodule1.test_func1")
    get_node(uses, "test_code.submodule1.test_func2")


def test_resolve_package_without___init__(callgraph):
    defines = get_in_dict(callgraph.defines_edges, "test_code.subpackage2.submodule_hidden1")
    get_node(defines, "test_code.subpackage2.submodule_hidden1.test_func1")


def test_resolve_package_with_known_root():
    dirname = os.path.dirname(__file__)
    filenames = glob(os.path.join(dirname, "test_code/**/*.py"), recursive=True)
    callgraph = CallGraphVisitor(filenames, logger=logging.getLogger(), root=dirname)
    # Root directory itself is not part of the module name (like sys.path).
    defines = get_in_dict(callgraph.defines_edges, "test_code.subpackage2.submodule_hidden1")
    get_node(defines, "test_code.subpackage2.submodule_hidden1.test_func1")


# --- Qualified-name splitting ---
#
# An anonymous scope is named in two dotted pieces, so these cannot be
# `rsplit(".", 1)`; that is the whole reason the helpers exist.

@pytest.mark.parametrize("qualified, expected", [
    ("mod", ("", "mod")),
    ("pkg.mod", ("pkg", "mod")),
    ("pkg.mod.Cls.meth", ("pkg.mod.Cls", "meth")),
    ("pkg.mod.f.lambda.0", ("pkg.mod.f", "lambda.0")),
    ("pkg.mod.f.listcomp.1.lambda.0", ("pkg.mod.f.listcomp.1", "lambda.0")),
    # A digit that is not an anonymous-scope index still reads as a name.
    ("pkg.mod.weird.0", ("pkg.mod.weird", "0")),
])
def test_split_qualified_name(qualified, expected):
    assert split_qualified_name(qualified) == expected
    assert parent_namespace(qualified) == expected[0]


def test_enclosing_namespaces_walks_outward():
    assert list(enclosing_namespaces("pkg.mod.f.lambda.0")) == [
        "pkg.mod.f.lambda.0", "pkg.mod.f", "pkg.mod", "pkg",
    ]


def test_enclosing_namespaces_of_a_top_level_name():
    assert list(enclosing_namespaces("mod")) == ["mod"]
