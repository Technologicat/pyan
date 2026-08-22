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

from .anutils import ANON_SCOPE_NAMES, enclosing_namespaces, parent_namespace
from .node import Flavor

__all__ = [
    "postprocess",
    "resolve_imports",
    "contract_nonexistents",
    "expand_unknowns",
    "collapse_inner",
    "cull_subsumed",
]


def postprocess(visitor, cull_subsumed_edges=True):
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

    Subsumption culling runs last, so that it sees the edges
    :func:`collapse_inner` folds into their parent Nodes. Pass
    ``cull_subsumed_edges=False`` to keep the raw edge set.
    """
    resolve_imports(visitor)
    contract_nonexistents(visitor)
    expand_unknowns(visitor)
    collapse_inner(visitor)
    if cull_subsumed_edges:
        cull_subsumed(visitor)


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

    # Walk up from from_node's namespace, ending at the module-level one (which
    # may be the module name itself, with no dots if it's a top-level module).
    return any(visitor.namespace_imports.get(ns, set()) & target_ancestors
               for ns in enclosing_namespaces(from_node.get_name()))


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


def collapse_inner(visitor):
    """Combine lambda and comprehension Nodes with their parent Nodes to reduce visual noise.
    Also mark those original nodes as undefined, so that they won't be visualized."""
    # Lambdas and comprehensions do not define any names in the enclosing
    # scope, so we only need to treat the uses edges.

    # BUG: resolve relative imports causes (RuntimeError: dictionary changed size during iteration)
    # temporary solution is adding list to force a copy of 'visitor.nodes'
    anon_nodes = [n for name in list(visitor.nodes) if name.partition(".")[0] in ANON_SCOPE_NAMES
                  for n in visitor.nodes[name]]

    # Deepest first. An anonymous scope inside another must hand its uses up
    # before the one holding it does the same, or the inner scope's calls land
    # on a node that is itself about to be marked undefined and stop there —
    # so a lambda returning a lambda lost every edge out of the inner one.
    anon_nodes.sort(key=lambda n: n.get_name().count("."), reverse=True)

    for n in anon_nodes:
        pn = visitor.get_parent_node(n)
        if n in visitor.uses_edges:
            for n2 in visitor.uses_edges[n]:  # outgoing uses edges
                if n2 is pn:  # a closure referring to its own enclosing scope
                    continue
                visitor.logger.info(f"Collapsing inner from {n} to {pn}, uses {n2}")
                visitor.add_uses_edge(pn, n2)
        n.defined = False


def cull_subsumed(visitor):
    """Drop uses edges that a more specific edge already conveys (#140).

    An edge ``S -> T`` is subsumed when either ``S`` is a module and something
    defined in its own file also uses ``T``, or ``T`` is a module and ``S``
    also uses something anywhere under it.

    Only a module stands in for its contents. An edge whose target is a
    module came from an ``import``, and says nothing a finer edge into that
    module does not already say; an edge whose target is a class is a
    constructor call, and stands on its own. The same asymmetry holds on the
    source side: a module's edge duplicates its members' edges, where a
    function's does not.
    """
    # A bare `import b` yields a uses edge whether or not the name is ever
    # referenced, so a module node accumulates one edge per imported name on
    # top of whatever its body actually does. Those are the edges that make a
    # grouped graph unreadable: they run parallel to the members' own edges,
    # from a node drawn right beside them.
    #
    # What this must not do is remove the last evidence of a dependency. It
    # cannot: an edge is dropped only when the subsuming edge runs between the
    # same two subtrees, so collapsing to module granularity (--depth 0)
    # recovers exactly the same pair.
    #
    # The two ends need different notions of "inside", because a package's
    # dotted-name descendants are its submodules — separate files. A sibling
    # module importing something says nothing about what `__init__.py` imports,
    # so the source side counts only what the module's own file defines, while
    # the target side counts everything under the package.
    all_nodes = [n for items in visitor.nodes.values() for n in items]
    modules = {n.get_name() for n in all_nodes if n.flavor == Flavor.MODULE}
    members = {name: set() for name in modules}  # defined in that module's own file
    within = {name: set() for name in modules}  # anywhere under that dotted path
    for node in all_nodes:
        enclosing_module_seen = False
        for ns in enclosing_namespaces(parent_namespace(node.get_name())):
            if ns in modules:
                within[ns].add(node)
                if not enclosing_module_seen:
                    enclosing_module_seen = True
                    if node.flavor != Flavor.MODULE:
                        members[ns].add(node)

    def is_subsumed(from_node, to_node):
        """Is there a finer edge carrying the same dependency?

        Exactly one end stands in for its contents per test. Letting both
        stand in at once would accept an edge between two unrelated nodes as
        evidence for this one: for a package importing its own subpackage,
        ``S`` contains ``T``, so a module inside the subpackage importing its
        neighbour would qualify — an edge that is not ``S``'s code and does
        not reach ``T``.
        """
        source_contents = members[from_node.get_name()] if from_node.flavor == Flavor.MODULE else ()
        target_contents = within[to_node.get_name()] if to_node.flavor == Flavor.MODULE else ()
        return (
            # something in the module's own file reaches the same target
            any(to_node in visitor.uses_edges.get(s, ()) for s in source_contents) or
            # this same source reaches somewhere inside the module
            any(t in target_contents for t in visitor.uses_edges.get(from_node, ()))
        )

    # Decide against the original graph, then remove; culling as we go would
    # make the result depend on iteration order. Deciding up front cannot empty
    # a chain of subsumptions: each one points at an edge strictly deeper on one
    # end, so the relation is well-founded and the finest edge always survives.
    removed_uses_edges = [
        (from_node, to_node)
        for from_node, to_nodes in visitor.uses_edges.items()
        for to_node in to_nodes
        if is_subsumed(from_node, to_node)
    ]

    for from_node, to_node in removed_uses_edges:
        visitor.logger.info(f"Removing subsumed edge from {from_node} to {to_node}")
        visitor.remove_uses_edge(from_node, to_node)
