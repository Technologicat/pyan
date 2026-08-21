"""How modules are drawn when nodes are grouped into clusters (#140).

A grouped drawing represents a module twice over: as the cluster holding its
members, and as a node of its own. The cluster is the module, so the node
becomes the module's own body — the scope CPython calls ``<module>`` — and
moves inside. Containment that the box already states is not drawn again.
"""

import logging
import os

from pyan.analyzer import CallGraphVisitor
from pyan.visgraph import VisualGraph

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "test_code", "issue140")

BASE_OPTIONS = {
    "draw_defines": True,
    "draw_uses": True,
    "colored": False,
    "grouped_alt": False,
    "annotated": False,
}


def build(*relpaths, grouped=True):
    filenames = [os.path.join(FIXTURE_DIR, p) for p in relpaths]
    visitor = CallGraphVisitor(filenames, root=FIXTURE_DIR, logger=logging.getLogger())
    options = {**BASE_OPTIONS, "grouped": grouped, "nested_groups": False}
    return VisualGraph.from_visitor(visitor, options=options, logger=logging.getLogger())


def walk(graph):
    """Yield every subgraph in the tree, including the root."""
    yield graph
    for sub in graph.subgraphs:
        yield from walk(sub)


def cluster(graph, label):
    """The subgraph whose human-readable label is *label*."""
    found = [g for g in walk(graph) if g.label == label]
    assert len(found) == 1, f"expected exactly one cluster labelled {label!r}, got {len(found)}"
    return found[0]


def node_labels(graph):
    return {n.label for n in graph.nodes}


def all_node_labels(graph):
    return {n.label for g in walk(graph) for n in g.nodes}


def test_module_body_is_drawn_inside_its_own_cluster():
    graph = build("pkg/routes.py", "pkg/schemas.py")

    assert node_labels(cluster(graph, "pkg.routes")) == {"<module>", "login"}
    # ...and not as a second node beside the box, under its dotted path.
    assert "pkg.routes" not in all_node_labels(graph)


def test_module_with_no_uses_edges_is_left_to_its_box():
    """`pkg.schemas` only contains definitions; its body reaches nothing."""
    graph = build("pkg/routes.py", "pkg/schemas.py")

    assert "<module>" not in node_labels(cluster(graph, "pkg.schemas"))
    assert "pkg.schemas" not in all_node_labels(graph)


def test_a_module_with_no_members_is_a_box_too():
    """A module looks the same whether or not it contains anything.

    `pkg/__init__.py` is empty, so there is nothing for its box to hold but the
    body node — which is exactly why the body node stays: dropping it would
    leave an empty box, and drawing the module as a bare ellipse instead would
    make a module's appearance depend on its contents.
    """
    graph = build("pkg/__init__.py", "pkg/routes.py", "pkg/schemas.py")

    assert node_labels(cluster(graph, "pkg")) == {"<module>"}
    assert "pkg" not in all_node_labels(graph)


def test_containment_is_not_drawn_twice():
    """The box states that `login` is in `pkg.routes`, so no defines edge does."""
    graph = build("pkg/routes.py", "pkg/schemas.py")

    # Asserting the absence of a `<module> -> login` edge would prove nothing:
    # it is equally absent when no module body is drawn at all. What changes is
    # whether anything at all claims to define `login`.
    defines_login = [e.source.label for e in graph.edges if e.flavor == "defines" and e.target.label == "login"]
    assert not defines_login


def test_import_edge_targets_the_module_body():
    """An import is executed by the importing module's body, and binds the imported one."""
    graph = build("pkg/consumer.py", "pkg/routes.py", "pkg/schemas.py")

    uses = [(e.source.label, e.target.label) for e in graph.edges if e.flavor == "uses"]
    assert ("<module>", "<module>") in uses


def test_ungrouped_output_keeps_module_nodes_and_defines_edges():
    """Without clusters, the module node and its defines edges are the only containment shown."""
    graph = build("pkg/routes.py", "pkg/schemas.py", grouped=False)

    assert "pkg.routes" in all_node_labels(graph)
    assert "<module>" not in all_node_labels(graph)

    defines = [(e.source.label, e.target.label) for e in graph.edges if e.flavor == "defines"]
    assert ("pkg.routes", "login") in defines
