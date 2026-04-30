#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The call graph: state container and post-analysis query API.

A :class:`CallGraph` owns the four state dicts that pyan's static
analysis populates:

- ``nodes`` — short name → list of :class:`~pyan.node.Node` in
  different namespaces (a "name bucket")
- ``defines_edges`` — Node → set of Nodes it defines
- ``uses_edges`` — Node → set of Nodes it uses
- ``module_to_filename`` — module name → source filename

During analysis, :class:`~pyan.analyzer.CallGraphVisitor` mutates a
graph in place via :meth:`get_node`, :meth:`add_uses_edge` (still on
the visitor), and friends. After analysis, callers query the graph
via :meth:`filter`, :meth:`filter_by_depth`, :meth:`get_related_nodes`,
:meth:`find_paths`, and :meth:`format_paths`.

The visitor exposes the same queries via thin shims for back-compat.
"""

from collections import defaultdict
import logging

from .node import Flavor, Node

__all__ = ["CallGraph"]


class CallGraph:
    """Pyan's analysis result: graph state plus queries against it."""

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.nodes = {}               # short name → list[Node]
        self.defines_edges = {}       # Node → set[Node]
        self.uses_edges = {}          # Node → set[Node]
        self.module_to_filename = {}  # module name → source filename

    ###########################################################################
    # Graph construction primitives

    def get_node(self, namespace, name, ast_node=None, flavor=Flavor.UNSPECIFIED, default_filename=None):
        """Return the unique node matching the namespace and name.
        Create a new node if one doesn't already exist.

        To associate the node with a syntax object in the analyzed source code,
        an AST node can be passed in. This only takes effect if a new Node
        is created.

        To associate an AST node to an existing graph node,
        see :meth:`~pyan.analyzer.CallGraphVisitor.associate_node`.

        Flavor describes the kind of object the node represents.
        See the :class:`pyan.node.Flavor` enum for currently supported values.

        For existing nodes, flavor overwrites if the given flavor is
        (strictly) more specific than the node's existing one.
        See :meth:`pyan.node.Flavor.specificity`.

        ``default_filename`` is the fallback used when *namespace* is not in
        ``module_to_filename`` — the visitor passes its own ``self.filename``
        so newly-created Nodes for the file currently being analyzed get the
        right source location.

        !!!
        In :class:`~pyan.analyzer.CallGraphVisitor`, always use
        :meth:`get_node` to create nodes, because it also sets some important
        auxiliary information. Do not call the Node constructor directly.
        !!!
        """
        if name in self.nodes:
            for n in self.nodes[name]:
                if n.namespace == namespace:
                    if Flavor.specificity(flavor) > Flavor.specificity(n.flavor):
                        n.flavor = flavor
                    return n

        # Try to figure out which source file this Node belongs to
        # (for annotated output).
        #
        # Other parts of the analyzer may change the filename later,
        # if a more authoritative source (e.g. a definition site) is found,
        # so the filenames should be trusted only after the analysis is
        # complete.
        #
        # If the namespace is one of the modules being analyzed,
        # the Node belongs to the corresponding file; otherwise fall back
        # to *default_filename* (typically the visitor's current file).
        filename = self.module_to_filename.get(namespace, default_filename)

        n = Node(namespace, name, ast_node, filename, flavor)

        # Add to the list of nodes that have this short name.
        if name in self.nodes:
            self.nodes[name].append(n)
        else:
            self.nodes[name] = [n]

        return n

    ###########################################################################
    # Queries

    def filter(self, node: None | Node = None, namespace: str | None = None,
               max_iter: int = 1000, direction: str = "both"):
        """Filter the graph to nodes related to *node* or in *namespace*.

        Mutates this graph in place; returns ``self`` for chaining.
        """
        filtered_nodes = self.get_related_nodes(node, namespace=namespace,
                                                max_iter=max_iter, direction=direction)

        self.nodes = {name: [node for node in nodes if node in filtered_nodes] for name, nodes in self.nodes.items()}
        self.uses_edges = {
            node: {n for n in nodes if n in filtered_nodes}
            for node, nodes in self.uses_edges.items()
            if node in filtered_nodes
        }
        self.defines_edges = {
            node: {n for n in nodes if n in filtered_nodes}
            for node, nodes in self.defines_edges.items()
            if node in filtered_nodes
        }
        return self

    def filter_by_depth(self, max_depth):
        """Collapse the graph to at most *max_depth* nesting levels.

        Depth is relative to each node's containing module, so the
        result is consistent regardless of how many dots are in the
        module's fully qualified name (e.g. ``pkg.sub.mod``).

        Nodes deeper than *max_depth* are removed. Edges involving
        removed nodes are redirected to their ancestor at *max_depth*,
        with self-edges suppressed.

        Args:
            max_depth: maximum nesting level within a module
                (0 = modules only, 1 = + classes/top-level functions,
                2 = + methods, etc.).

        Returns:
            self
        """
        known_modules = set(self.module_to_filename)

        def module_relative_depth(node):
            """Return ``(module_name, depth_within_module)``."""
            full = node.get_name()
            if full in known_modules:
                return full, 0
            # Find the longest module name that is a prefix.
            best = ""
            for mod in known_modules:
                if full.startswith(mod + ".") and len(mod) > len(best):
                    best = mod
            if best:
                remainder = full[len(best) + 1:]
                return best, 1 + remainder.count(".")
            return None, node.get_level()  # fallback (external nodes)

        def ancestor_at_depth(node, mod_name):
            """Return the ancestor ``Node`` of *node* at *max_depth*."""
            if max_depth == 0:
                return self.get_node("", mod_name, None)
            remainder = node.get_name()[len(mod_name) + 1:]
            parts = remainder.split(".")
            ancestor_suffix = ".".join(parts[:max_depth])
            ancestor_full = mod_name + "." + ancestor_suffix
            idx = ancestor_full.rfind(".")
            return self.get_node(ancestor_full[:idx], ancestor_full[idx + 1:], None)

        # Build a mapping: deep node → ancestor at max_depth.
        # A "deep node" is one whose module-relative depth exceeds max_depth.
        ancestor_of = {}
        for node_list in self.nodes.values():
            for n in node_list:
                if n.namespace is not None and n.defined:
                    mod, depth = module_relative_depth(n)
                    if depth > max_depth:
                        ancestor_of[n] = ancestor_at_depth(n, mod)

        # Remap edges: redirect deep endpoints to their ancestor.
        def remap_edges(edge_dict):
            new = defaultdict(set)
            for src, targets in edge_dict.items():
                src2 = ancestor_of.get(src, src)
                if src2.namespace is None or not src2.defined:
                    continue
                for tgt in targets:
                    tgt2 = ancestor_of.get(tgt, tgt)
                    if tgt2.namespace is None or not tgt2.defined:
                        continue
                    if tgt2 != src2:  # suppress self-edges
                        new[src2].add(tgt2)
            return dict(new)

        self.uses_edges = remap_edges(self.uses_edges)
        self.defines_edges = remap_edges(self.defines_edges)

        # Remove deep nodes.
        self.nodes = {
            name: [n for n in node_list if n not in ancestor_of]
            for name, node_list in self.nodes.items()
        }

        return self

    def get_related_nodes(
        self, node: None | Node = None, namespace: str | None = None,
        max_iter: int = 1000, direction: str = "both",
    ) -> set:
        """Get nodes related to *node* or in *namespace*.

        Args:
            node: starting node. If None, filter only by namespace.
            namespace: namespace to search in. If None, determined from *node*.
            max_iter: maximum BFS iterations.
            direction: ``"both"`` (follow edges in both directions),
                ``"down"`` (forward edges only — callees/children),
                ``"up"`` (reverse edges only — callers/parents).

        Returns:
            Set of related nodes including *node* itself.
        """
        if direction not in ("both", "down", "up"):
            raise ValueError(f"direction must be 'both', 'down', or 'up'; got {direction!r}")

        if node is None:
            queue = []
            if namespace is None:
                new_nodes = {n for items in self.nodes.values() for n in items}
            else:
                new_nodes = {
                    n
                    for items in self.nodes.values()
                    for n in items
                    if n.namespace is not None and namespace in n.namespace
                }
        else:
            new_nodes = set()
            if namespace is None:
                namespace = node.namespace.strip(".").split(".", 1)[0]
            queue = [node]

        # Build reverse-edge indices for upward traversal.
        follow_up = direction in ("both", "up")
        if follow_up:
            rev_uses = {}  # target → set of sources
            for src, targets in self.uses_edges.items():
                for tgt in targets:
                    rev_uses.setdefault(tgt, set()).add(src)
            rev_defines = {}
            for src, targets in self.defines_edges.items():
                for tgt in targets:
                    rev_defines.setdefault(tgt, set()).add(src)

        follow_down = direction in ("both", "down")

        def in_namespace(n):
            return n.namespace is not None and namespace in n.namespace

        # BFS: follow edges in the requested direction(s).
        i = max_iter
        while len(queue) > 0:
            item = queue.pop()
            if item not in new_nodes:
                new_nodes.add(item)
                i -= 1
                if i < 0:
                    break
                if follow_down:
                    queue.extend(
                        n for n in self.uses_edges.get(item, [])
                        if n not in new_nodes and in_namespace(n)
                    )
                    queue.extend(
                        n for n in self.defines_edges.get(item, [])
                        if n not in new_nodes and in_namespace(n)
                    )
                if follow_up:
                    queue.extend(
                        n for n in rev_uses.get(item, [])
                        if n not in new_nodes and in_namespace(n)
                    )
                    queue.extend(
                        n for n in rev_defines.get(item, [])
                        if n not in new_nodes and in_namespace(n)
                    )

        return new_nodes

    def find_paths(self, from_node, to_node, max_paths=10):
        """Find simple paths from *from_node* to *to_node* via uses edges.

        Uses DFS; results are sorted shortest-first after collection.
        Note that DFS discovers paths in arbitrary order, so with a low
        *max_paths* the shortest path may not be among those found.

        Args:
            from_node: starting Node.
            to_node: target Node.
            max_paths: stop after finding this many paths.

        Returns:
            List of paths, where each path is a list of Nodes.
            Sorted shortest-first (among those found).
        """
        results = []

        def dfs(current, target, visited):
            if len(results) >= max_paths:
                return
            if current == target:
                results.append(list(visited))
                return
            for neighbor in self.uses_edges.get(current, []):
                if neighbor not in visited:
                    visited.append(neighbor)
                    dfs(neighbor, target, visited)
                    visited.pop()

        dfs(from_node, to_node, [from_node])
        results.sort(key=len)
        return results

    @staticmethod
    def format_paths(paths):
        """Format a list of paths (from :meth:`find_paths`) as human-readable text.

        Returns one path per line, ``->`` delimited, shortest first.
        """
        lines = []
        for path in paths:
            names = [n.name for n in path]
            lines.append(" -> ".join(names))
        return "\n".join(lines)
