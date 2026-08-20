"""Edge subsumption: a more specific edge makes a less specific one redundant (#140).

A uses edge ``S -> T`` is subsumed when the graph also holds ``S' -> T'``, where
``S'`` is ``S`` or a descendant of ``S``, ``T'`` is ``T`` or a descendant of ``T``,
and ``(S', T') != (S, T)``.

The two halves are separately reachable: a module's import-derived edge is
subsumed on the *source* side when one of its own members uses the same target,
and on the *target* side when the importer reaches into the imported module.
"""

import logging
import os

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "test_code", "issue140")


def analyze(*relpaths, cull_subsumed_edges=True):
    filenames = [os.path.join(FIXTURE_DIR, p) for p in relpaths]
    return CallGraphVisitor(filenames, root=FIXTURE_DIR, logger=logging.getLogger(),
                            cull_subsumed_edges=cull_subsumed_edges)


def names(nodes):
    return {node.get_name() for node in nodes}


def test_module_edge_subsumed_by_member_use():
    """Source side: `login` uses the imported names, so the module's edges are redundant."""
    v = analyze("pkg/routes.py", "pkg/schemas.py")

    uses = names(get_in_dict(v.uses_edges, "pkg.routes"))
    assert "pkg.schemas.LoginRequest" not in uses
    assert "pkg.schemas.TokenResponse" not in uses

    # The subsuming edges themselves must survive.
    member_uses = names(get_in_dict(v.uses_edges, "pkg.routes.login"))
    assert "pkg.schemas.LoginRequest" in member_uses
    assert "pkg.schemas.TokenResponse" in member_uses


def test_module_edge_subsumed_by_use_inside_target():
    """Target side: `caller -> callee` is subsumed by `caller -> callee.dostuff`."""
    v = analyze("caller.py", "callee.py")

    uses = names(get_in_dict(v.uses_edges, "caller"))
    assert "callee" not in uses
    assert "callee.dostuff" in uses


def test_module_level_use_survives():
    """`router = make_router()` runs at module scope; no member reproduces that edge."""
    v = analyze("pkg/routes.py", "pkg/schemas.py")

    uses = names(get_in_dict(v.uses_edges, "pkg.routes"))
    assert "pkg.schemas.make_router" in uses


def test_bare_import_edge_survives():
    """An import whose name is never referenced is the only record of the dependency."""
    v = analyze("pkg/consumer.py", "pkg/routes.py", "pkg/schemas.py")

    uses = names(get_in_dict(v.uses_edges, "pkg.consumer"))
    assert "pkg.routes" in uses


def test_module_level_call_in_own_module_survives():
    """`callee` calls its own `dostuff` at import time — nothing subsumes that."""
    v = analyze("caller.py", "callee.py")

    uses = names(get_in_dict(v.uses_edges, "callee"))
    assert "callee.dostuff" in uses


def test_constructor_call_survives():
    """`f` both instantiates `Thing` and calls a method on it.

    Subsumption stops at the class boundary: `f -> Thing` is the constructor
    call, which a call graph exists to show, where `a -> b` between modules is
    an import and carries nothing the finer edge doesn't.
    """
    v = analyze("construct.py")

    uses = names(get_in_dict(v.uses_edges, "construct.f"))
    assert "construct.Thing" in uses
    assert "construct.Thing.method" in uses


def test_defines_edges_untouched():
    """Subsumption is defined over uses edges; containment is a separate relation."""
    v = analyze("caller.py", "callee.py")
    get_node(get_in_dict(v.defines_edges, "callee"), "callee.dostuff")

    v = analyze("pkg/routes.py", "pkg/schemas.py")
    get_node(get_in_dict(v.defines_edges, "pkg.routes"), "pkg.routes.login")


def test_culling_can_be_switched_off():
    """Both halves of the rule are disabled together by `cull_subsumed_edges=False`."""
    v = analyze("caller.py", "callee.py", cull_subsumed_edges=False)
    assert "callee" in names(get_in_dict(v.uses_edges, "caller"))

    v = analyze("pkg/routes.py", "pkg/schemas.py", cull_subsumed_edges=False)
    uses = names(get_in_dict(v.uses_edges, "pkg.routes"))
    assert "pkg.schemas.LoginRequest" in uses
    assert "pkg.schemas.TokenResponse" in uses


def test_module_level_view_survives_culling():
    """Subsumption never removes the last evidence of a dependency.

    At depth 0 the graph is modules only, and `caller -> callee` is the whole of
    it. Culling the module edge must not empty that view: the subsuming edge
    collapses back onto the same pair.
    """
    v = analyze("caller.py", "callee.py")
    graph = v.graph.filter_by_depth(0)

    uses = names(get_in_dict(graph.uses_edges, "caller"))
    assert uses == {"callee"}
