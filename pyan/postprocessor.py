#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Postprocessing pipeline for the call graph.

Runs after the analyzer's two visitor passes complete. Each function
takes the :class:`~pyan.analyzer.CallGraphVisitor` and mutates its
``nodes`` / ``defines_edges`` / ``uses_edges`` to produce the final
graph the writers consume.

Use :func:`postprocess` to run the full pipeline; the individual stages
are exposed for testing and reuse.
"""

from .anutils import ANON_SCOPE_NAMES
from .node import Flavor

__all__ = [
    "postprocess",
    "resolve_imports",
    "contract_nonexistents",
    "expand_unknowns",
    "cull_inherited",
    "collapse_inner",
]


def postprocess(visitor):
    """Run the full postprocessing pipeline.

    First resolve imports (remap IMPORTEDITEM nodes to their targets),
    then contract unresolved references to wildcards (``*.name``), then
    expand wildcards — but only to targets whose module is actually
    imported by the source (#88).

    Historical note: the original Pyan used contract-then-expand, which
    produced spurious edges because expansion was unconstrained. A later
    change switched to expand-then-contract to limit the blast radius.
    Now that :func:`expand_unknowns` checks import relationships, we can
    safely return to contract-then-expand, which is the correct order:
    wildcards must exist before expansion can act on them.
    """
    resolve_imports(visitor)
    contract_nonexistents(visitor)
    expand_unknowns(visitor)
    cull_inherited(visitor)
    collapse_inner(visitor)


def resolve_imports(visitor):
    """Resolve relative imports and remap nodes."""
    # first find all imports and map to themselves. we will then remap those that are currently pointing
    # to duplicates or into the void
    imports_to_resolve = {n for items in visitor.nodes.values() for n in items if n.flavor == Flavor.IMPORTEDITEM}
    # map real definitions
    import_mapping = {}
    while len(imports_to_resolve) > 0:
        from_node = imports_to_resolve.pop()
        if from_node in import_mapping:
            continue
        to_uses = visitor.uses_edges.get(from_node, {from_node})
        assert len(to_uses) == 1
        to_node = to_uses.pop()  # resolve alias
        # resolve namespace and get module
        if to_node.namespace == "":
            module_node = to_node
        else:
            assert from_node.name == to_node.name
            module_node = visitor.get_node("", to_node.namespace)
        module_uses = visitor.uses_edges.get(module_node)
        if module_uses is not None:
            # check if in module item exists and if yes, map to it
            for candidate_to_node in module_uses:
                if candidate_to_node.name == from_node.name:
                    to_node = candidate_to_node
                    import_mapping[from_node] = to_node
                    if to_node.flavor == Flavor.IMPORTEDITEM and from_node is not to_node:  # avoid self-recursion
                        imports_to_resolve.add(to_node)
                    break

    # set previously undefined nodes to defined
    # go through undefined attributes
    attribute_import_mapping = {}
    for nodes in visitor.nodes.values():
        for node in nodes:
            if not node.defined and node.flavor == Flavor.ATTRIBUTE:
                # try to resolve namespace and find imported item mapping
                for from_node, to_node in import_mapping.items():
                    if (
                        f"{from_node.namespace}.{from_node.name}" == node.namespace and
                        from_node.flavor == Flavor.IMPORTEDITEM
                    ):
                        # use define edges as potential candidates
                        for candidate_to_node in visitor.defines_edges.get(to_node, []):
                            if candidate_to_node.name == node.name:
                                attribute_import_mapping[node] = candidate_to_node
                                break
    import_mapping.update(attribute_import_mapping)

    # remap nodes based on import mapping
    visitor.nodes = {name: [import_mapping.get(n, n) for n in items] for name, items in visitor.nodes.items()}
    visitor.uses_edges = {
        import_mapping.get(from_node, from_node): {import_mapping.get(to_node, to_node) for to_node in to_nodes}
        for from_node, to_nodes in visitor.uses_edges.items()
        if len(to_nodes) > 0
    }
    visitor.defines_edges = {
        import_mapping.get(from_node, from_node): {import_mapping.get(to_node, to_node) for to_node in to_nodes}
        for from_node, to_nodes in visitor.defines_edges.items()
        if len(to_nodes) > 0
    }


def contract_nonexistents(visitor):
    """For all use edges to non-existent (i.e. not defined nodes) X.name, replace with edge to *.name."""
    new_uses_edges = []
    removed_uses_edges = []
    for n in visitor.uses_edges:
        for n2 in visitor.uses_edges[n]:
            if n2.namespace is not None and not n2.defined:
                n3 = visitor.get_node(None, n2.name, n2.ast_node)
                n3.defined = False
                new_uses_edges.append((n, n3))
                removed_uses_edges.append((n, n2))
                visitor.logger.info(f"Contracting non-existent from {n} to {n2} as {n3}")

    for from_node, to_node in new_uses_edges:
        visitor.add_uses_edge(from_node, to_node)

    for from_node, to_node in removed_uses_edges:
        visitor.remove_uses_edge(from_node, to_node)


def _has_import_to(visitor, from_node, target_ns):
    """Check whether `from_node`'s namespace (or any ancestor) imports a module
    that is `target_ns` or a parent of it.

    Walks up the namespace chain from `from_node`, checking
    ``visitor.namespace_imports`` at each level. This means a module-level
    import is visible to all children, while a function-level import is
    only visible in that function.

    Returns True if an import relationship exists, or if `from_node` and
    the target are in the same module (intra-module references are always
    allowed).

    Examples::

        # from_node = pkg.mod.func, target_ns = pkg.mod.MyClass
        #   → True (same module pkg.mod)
        #
        # from_node = pkg.mod_a.func, target_ns = pkg.mod_b
        #   → True only if pkg.mod_a (or func) imports pkg.mod_b
        #
        # from_node = pkg.mod.caller (has `from other import foo`),
        # from_node = pkg.mod.non_caller (no import)
        #   → caller: True; non_caller: False
    """
    # Intra-module: always allowed.
    # Find from_node's module by matching against module_to_filename.
    from_ns = from_node.get_name()
    from_module = from_ns
    for mod in visitor.module_to_filename:
        if from_ns == mod or from_ns.startswith(mod + "."):
            from_module = mod
            break
    if target_ns == from_module or target_ns.startswith(from_module + "."):
        return True

    # Build the set of ancestor namespaces of target_ns.
    # For "foo.bar.baz", this is {"foo", "foo.bar", "foo.bar.baz"}.
    target_parts = target_ns.split(".")
    target_ancestors = {".".join(target_parts[:i + 1]) for i in range(len(target_parts))}

    # Walk up from from_node's namespace.
    ns = from_node.get_name()
    while True:
        imports = visitor.namespace_imports.get(ns, set())
        if imports & target_ancestors:
            return True
        if "." not in ns:
            break
        ns = ns.rsplit(".", 1)[0]

    # Also check the module-level namespace (which may be the module name itself,
    # with no dots if it's a top-level module).
    imports = visitor.namespace_imports.get(ns, set())
    return bool(imports & target_ancestors)


def _name_referenced_in_scope(visitor, from_node, name):
    """Whether `name` occurs as a bare name in from_node's own scope.

    symtable records bare-name references — including globals/frees such as an
    imported `foo` used as `foo()` — but never attribute leaves: `othermod.cache()`
    never puts `cache` in the scope's identifiers. So this distinguishes a genuine
    name reference (may legitimately resolve to a module-level `name`) from an
    attribute access on something else (must not). No scope entry → default True,
    keeping the previous expand behaviour.
    """
    src_scope = visitor.scopes.get(from_node.get_name())
    return src_scope is None or name in src_scope.defs


def expand_unknowns(visitor):
    """For each unknown node *.name, replace all its incoming edges with edges to X.name for all possible Xs.

    Only expands to targets whose module is imported by (or is the same as)
    the source node's module, to avoid spurious cross-module edges (#88).

    Also mark all unknown nodes as not defined (so that they won't be visualized)."""
    new_defines_edges = []
    for n in visitor.defines_edges:
        for n2 in visitor.defines_edges[n]:
            if n2.namespace is None:
                for n3 in visitor.nodes[n2.name]:
                    if (n3.namespace is not None and n3.defined and
                        _name_referenced_in_scope(visitor, n, n2.name) and
                        _has_import_to(visitor, n, n3.namespace)):
                        new_defines_edges.append((n, n3))

    for from_node, to_node in new_defines_edges:
        visitor.add_defines_edge(from_node, to_node)
        visitor.logger.info(f"Expanding unknowns: new defines edge from {from_node} to {to_node}")

    new_uses_edges = []
    for n in visitor.uses_edges:
        for n2 in visitor.uses_edges[n]:
            if n2.namespace is None:
                for n3 in visitor.nodes[n2.name]:
                    if (n3.namespace is not None and n3.defined and
                        _name_referenced_in_scope(visitor, n, n2.name) and
                        _has_import_to(visitor, n, n3.namespace)):
                        new_uses_edges.append((n, n3))

    for from_node, to_node in new_uses_edges:
        visitor.add_uses_edge(from_node, to_node)
        visitor.logger.info(f"Expanding unknowns: new uses edge from {from_node} to {to_node}")

    for name in visitor.nodes:
        for n in visitor.nodes[name]:
            if n.namespace is None:
                n.defined = False


def cull_inherited(visitor):
    """For each use edge from W to X.name, if it also has an edge to W to Y.name where
    Y is used by X, then remove the first edge.
    """
    removed_uses_edges = []
    for n in visitor.uses_edges:
        for n2 in visitor.uses_edges[n]:
            inherited = False
            for n3 in visitor.uses_edges[n]:
                if (
                    n3.name == n2.name and
                    n2.namespace is not None and
                    n3.namespace is not None and
                    n3.namespace != n2.namespace
                ):
                    pn2 = visitor.get_parent_node(n2)
                    pn3 = visitor.get_parent_node(n3)
                    # if pn3 in visitor.uses_edges and pn2 in visitor.uses_edges[pn3]:
                    # remove the second edge W to Y.name (TODO: add an option to choose this)
                    if pn2 in visitor.uses_edges and pn3 in visitor.uses_edges[pn2]:  # remove the first edge W to X.name
                        inherited = True

            if inherited and n in visitor.uses_edges:
                removed_uses_edges.append((n, n2))
                visitor.logger.info(f"Removing inherited edge from {n} to {n2}")

    for from_node, to_node in removed_uses_edges:
        visitor.remove_uses_edge(from_node, to_node)


def collapse_inner(visitor):
    """Combine lambda and comprehension Nodes with their parent Nodes to reduce visual noise.
    Also mark those original nodes as undefined, so that they won't be visualized."""
    # Lambdas and comprehensions do not define any names in the enclosing
    # scope, so we only need to treat the uses edges.

    # BUG: resolve relative imports causes (RuntimeError: dictionary changed size during iteration)
    # temporary solution is adding list to force a copy of 'visitor.nodes'
    for name in list(visitor.nodes):
        if name.partition(".")[0] in ANON_SCOPE_NAMES:
            for n in visitor.nodes[name]:
                pn = visitor.get_parent_node(n)
                if n in visitor.uses_edges:
                    for n2 in visitor.uses_edges[n]:  # outgoing uses edges
                        visitor.logger.info(f"Collapsing inner from {n} to {pn}, uses {n2}")
                        visitor.add_uses_edge(pn, n2)
                n.defined = False
