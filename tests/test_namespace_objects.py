"""Tests for module-level NAME Nodes and the NAMESPACE_OBJECT overlay (#129).

Two related concerns share this file because they form one design arc
(the "every named entity reachable from outside its definition site is a Node"
principle introduced in v2.6.0):

- Module-level name binding tests verify that ``mymod.x = ...`` at module
  scope produces a defined ``Flavor.NAME`` Node, and that function-locals
  do not. (The prequisite for #129.)
- NAMESPACE_OBJECT tests verify constructor-based recognition of runtime
  namespaces (``unpythonic.env``, ``types.SimpleNamespace``,
  ``argparse.Namespace``, plus user-extensible registry).

See ``briefs/namespace-objects-brief.md`` for the design rationale.
"""

import logging
import os

from pyan.analyzer import CallGraphVisitor
from pyan.node import Flavor

TESTS_DIR = os.path.dirname(__file__)


# --- Module-level NAME Node-ification ---
#
# Every named entity reachable from outside its definition site is a Node.
# Module-level and class-level bindings are reachable; function-locals are not.

def _name_nodes_at(visitor, namespace):
    """Return defined NAME-flavored Nodes at *namespace*."""
    return [
        n for ns in visitor.nodes.values() for n in ns
        if n.defined and n.flavor == Flavor.NAME and n.namespace == namespace
    ]


def test_module_level_assignment_creates_defined_name_node():
    """``mymod.x = ...`` at module level produces a defined ``Flavor.NAME``
    Node at ``mymod.x``, with a defines edge from the module Node."""
    v = CallGraphVisitor.from_sources([
        ("CONSTANT = 42\nLOGGER = object()\n", "mymod"),
    ])
    name_nodes = {n.name for n in _name_nodes_at(v, "mymod")}
    assert "CONSTANT" in name_nodes
    assert "LOGGER" in name_nodes


def test_function_local_does_not_create_name_node():
    """Function-local bindings stay as scope-only ``set_value`` and do not
    produce graph Nodes — they aren't externally addressable and would
    only clutter the graph."""
    v = CallGraphVisitor.from_sources([
        ("def f():\n    local = 1\n    return local\n", "mymod"),
    ])
    name_nodes = {n.name for n in _name_nodes_at(v, "mymod.f")}
    assert "local" not in name_nodes


def test_cross_module_constant_import_resolves_to_name_node():
    """``from mymod import CONSTANT`` should bind to the actual NAME Node
    at ``mymod.CONSTANT``, not contract to a wildcard. This is the
    precision win from making module-level bindings addressable Nodes."""
    v = CallGraphVisitor.from_sources([
        ("CONSTANT = 42\n", "constants"),
        ("from constants import CONSTANT\n\ndef use():\n    return CONSTANT\n", "consumer"),
    ])
    use_uses = {n.get_name() for n in v.uses_edges.get(
        v.get_node("consumer", "use"), set()
    )}
    assert "constants.CONSTANT" in use_uses


def test_visgraph_suppresses_edgeless_name_nodes():
    """NAME Nodes with no incoming or outgoing uses edges should not appear
    in the visgraph output (visual-density default). The Node still exists
    in the analyzer's graph for cross-module resolution; only the rendered
    output filters it."""
    from pyan.visgraph import VisualGraph
    v = CallGraphVisitor.from_sources([
        # UNUSED has no uses edges anywhere; USED is imported by consumer.
        ("UNUSED = 1\nUSED = 2\n", "constants"),
        ("from constants import USED\n\ndef f():\n    return USED\n", "consumer"),
    ])
    vg = VisualGraph.from_visitor(v, options={"draw_defines": True, "draw_uses": True})

    def collect(graph, out):
        for n in graph.nodes:
            out.add(n.label)
        for sg in graph.subgraphs:
            collect(sg, out)
    labels = set()
    collect(vg, labels)
    assert any("USED" in lab for lab in labels), f"USED should appear; saw {labels}"
    assert not any("UNUSED" in lab for lab in labels), (
        f"UNUSED has no uses edges and should be suppressed; saw {labels}"
    )


# --- NAMESPACE_OBJECT (constructor-based namespace recognition, #129) ---

def _namespace_object_node(visitor, fqn):
    """Locate the NAMESPACE_OBJECT-flavored Node at *fqn*, or None."""
    namespace, _, name = fqn.rpartition(".")
    for n in visitor.nodes.get(name, []):
        if n.namespace == namespace and n.flavor == Flavor.NAMESPACE_OBJECT:
            return n
    return None


def _scope_defs(visitor, fqn):
    """Return defs dict of the scope at *fqn*, or empty dict if absent."""
    sc = visitor.scopes.get(fqn)
    return sc.defs if sc else {}


# Each of the four built-in constructors gets at least one fixture.

def test_namespace_object_unpythonic_env_canonical_form():
    """``from unpythonic.env import env; config = env(thingy=baa)`` —
    canonical FQN ``"unpythonic.env.env"``."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None, "config should be a NAMESPACE_OBJECT Node"
    assert "thingy" in _scope_defs(v, "mymod.config"), "kwarg 'thingy' should register in config's scope"


def test_namespace_object_unpythonic_env_top_level_reexport():
    """``from unpythonic import env; config = env(thingy=baa)`` —
    top-level re-export FQN ``"unpythonic.env"`` (the module shadows
    the class — historical naming)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic import env\n\nconfig = env(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.config")


def test_namespace_object_simplenamespace():
    """``import types; ns = types.SimpleNamespace(thingy=baa)`` — Attribute
    func, FQN reconstructed from the dotted AST path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nimport types\n\nns = types.SimpleNamespace(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.ns")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.ns")


def test_namespace_object_argparse_namespace():
    """``import argparse; cfg = argparse.Namespace(thingy=baa)``."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nimport argparse\n\ncfg = argparse.Namespace(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.cfg")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.cfg")


# Each of the four binding sites.

def test_namespace_object_recognized_in_annotated_assign():
    """``config: Env = env(...)`` — AnnAssign path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig: env = env(thingy=baa)\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None


def test_namespace_object_recognized_in_walrus():
    """``(config := env(...))`` — NamedExpr path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\n_ = (config := env(thingy=baa))\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None


def test_namespace_object_recognized_in_with_statement():
    """``with env(...) as config:`` — `_visit_with` routes through
    `analyze_binding`, same recognition path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nwith env(thingy=baa) as config:\n    pass\n", "mymod"),
    ])
    # In a with-statement at module scope, the binding still creates a
    # module-level NAME Node that gets upgraded to NAMESPACE_OBJECT.
    assert _namespace_object_node(v, "mymod.config") is not None


# Cross-module attribute resolution — the headline use case.

def test_namespace_object_cross_module_attr_resolves():
    """External ``config.thingy`` resolves to the kwarg's target Node,
    bypassing #127's module-level fallback entirely."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env(thingy=baa)\n", "lib"),
        ("from lib import config\n\ndef use():\n    return config.thingy\n", "consumer"),
    ])
    use_uses = {n.get_name() for n in v.uses_edges.get(v.get_node("consumer", "use"), set())}
    assert "lib.baa" in use_uses, f"config.thingy should resolve to lib.baa; saw {use_uses}"


# Staged form: point 4 in the design brief.

def test_namespace_object_attribute_write_after_construction():
    """``config = env(); config.a = baa`` — the attribute write goes
    through ``_bind_target``'s Attribute branch and ``set_attribute``,
    which writes into the NAMESPACE_OBJECT's scope (created at
    construction time, even when no kwargs were passed)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nconfig.a = baa\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None
    assert "a" in _scope_defs(v, "mymod.config"), "later attribute write should populate the scope"


# setattr — three levels.

def test_namespace_object_setattr_level1_literal_string():
    """``setattr(config, "a", baa)`` — literal-string name."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nsetattr(config, 'a', baa)\n", "mymod"),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_level2_scope_local_literal():
    """``k = "a"; setattr(config, k, baa)`` — name-bound literal in same
    scope. Module-level binding chain only (function-local literals not
    tracked, by design — see ``_maybe_register_name_literal``)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nKEY = 'a'\nsetattr(config, KEY, baa)\n", "mymod"),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_level3_cross_module_imported_literal():
    """``from constants import KEY; setattr(config, KEY, baa)`` — KEY
    traces back through an import to a string literal in another module."""
    v = CallGraphVisitor.from_sources([
        ("KEY = 'a'\n", "constants"),
        (
            "def baa():\n    pass\n\n"
            "from unpythonic.env import env\n"
            "from constants import KEY\n\n"
            "config = env()\n"
            "setattr(config, KEY, baa)\n",
            "mymod",
        ),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_dynamic_key_is_no_op():
    """``for k in keys: setattr(config, k, baa)`` — k is loop-bound and
    not statically a string literal. Recognition gracefully no-ops; no
    spurious bindings are registered."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "from unpythonic.env import env\n\n"
            "config = env()\n"
            "for k in ('a', 'b'):\n"
            "    setattr(config, k, baa)\n",
            "mymod",
        ),
    ])
    # The constructor recognition still creates the NAMESPACE_OBJECT,
    # but no individual kwarg names get registered from the loop.
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    defs = _scope_defs(v, "mymod.config")
    assert "a" not in defs and "b" not in defs


# User-extensible registry.

def test_user_extensible_namespace_constructor():
    """``namespace_constructors=["mylib.MyNS"]`` extends the registry."""
    v = CallGraphVisitor.from_sources(
        [(
            "def baa():\n    pass\n\n"
            "from mylib import MyNS\n\n"
            "config = MyNS(thingy=baa)\n",
            "mymod",
        )],
        namespace_constructors=["mylib.MyNS"],
    )
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.config")


# Negative: don't over-fire.

def test_factory_returned_namespace_not_recognized():
    """``config = make_config()`` where ``make_config`` is a regular
    function — not in the registry, so no upgrade. Falls through to
    #127's module-level fallback as the right floor."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "def make_config():\n    return None\n\n"
            "config = make_config()\n",
            "mymod",
        ),
    ])
    assert _namespace_object_node(v, "mymod.config") is None


def test_unrecognized_constructor_no_op():
    """Calling a non-registered constructor doesn't accidentally upgrade."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "class MyClass:\n    pass\n\n"
            "config = MyClass()\n",
            "mymod",
        ),
    ])
    assert _namespace_object_node(v, "mymod.config") is None
