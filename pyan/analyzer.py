#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The AST visitor."""

import ast
import builtins as _builtins_module
from collections import defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
import logging
import symtable

from .anutils import (
    ANON_SCOPE_NAMES,
    NAMESPACE_CONSTRUCTORS,
    ExecuteInInnerScope,
    Scope,
    UnresolvedSuperCallError,
    canonize_exprs,
    format_alias,
    get_ast_node_name,
    get_module_name,
    infer_root,
    resolve_import,
    resolve_method_resolution_order,
    tail,
)
from .node import Flavor, Node
from .postprocessor import postprocess

# PEP 695 (Python 3.12+) type-parameter scope type identifiers.
# On 3.12, symtable.get_type() returns the raw string 'type parameter';
# on 3.13+, it returns SymbolTableType.TYPE_PARAMETERS (value='type parameters').
_TYPE_PARAMS_SCOPE_TYPES = frozenset({"type parameter", "type parameters"})


def _is_type_params_scope(table):
    """Return True if *table* is a PEP 695 type-parameter scope."""
    tp = table.get_type()
    return getattr(tp, "value", tp) in _TYPE_PARAMS_SCOPE_TYPES

# TODO: add Cython support (strip type annotations in a preprocess step, then treat as Python)
# TODO: built-in functions (range(), enumerate(), zip(), iter(), ...):
#       add to a special scope "built-in" in analyze_scopes() (or ignore altogether)
# TODO: support Node-ifying ListComp et al, List, Tuple
# TODO: make the analyzer smarter (see individual TODOs below)

# Note the use of the term "node" for two different concepts:
#
#  - AST nodes (the "node" argument of CallGraphVisitor.visit_*())
#
#  - The Node class that mainly stores auxiliary information about AST nodes,
#    for the purposes of generating the call graph.
#
#    Namespaces also get a Node (with no associated AST node).

# These tables were useful for porting the visitor to Python 3:
#
# https://docs.python.org/2/library/compiler.html#module-compiler.ast
# https://docs.python.org/3/library/ast.html#abstract-grammar
#


class CallGraphVisitor(ast.NodeVisitor):
    """A visitor that can be walked over a Python AST, and will derive
    information about the objects in the AST and how they use each other.

    A single CallGraphVisitor object can be run over several ASTs (from a
    set of source files).  The resulting information is the aggregate from
    all files.  This way use information between objects in different files
    can be gathered."""

    def __init__(self, filenames, root: str = None, logger=None,
                 namespace_constructors: Iterable[str] | None = None):
        """Construct a CallGraphVisitor and analyze *filenames*.

        Args:
            filenames: list of ``.py`` file paths to analyze.
            root: project root directory.  When ``None``, inferred from
                *filenames* via :func:`infer_root`.
            logger: optional ``logging.Logger`` instance.
            namespace_constructors: extra fully-qualified constructor names
                to recognize beyond the built-in
                :data:`~pyan.anutils.NAMESPACE_CONSTRUCTORS`.  When the rhs
                of a binding is ``Call(func=...)`` whose resolved import
                origin matches one of these (built-in ∪ user), the LHS is
                upgraded to ``Flavor.NAMESPACE_OBJECT`` and its scope is
                populated with the call's keyword arguments (#129).  Each
                entry should be the canonical dotted import path
                (e.g. ``"my.lib.MyNamespace"``).
        """
        self._init_common(logger, namespace_constructors)

        # Infer root from filenames when not explicitly given.
        # This ensures namespace packages (directories without __init__.py)
        # get correct dotted module names.  See #117.
        if root is None:
            root = infer_root(filenames)
        self.root = root

        # full module names for all given files
        for filename in filenames:
            mod_name = get_module_name(filename, root=self.root)
            self.module_to_filename[mod_name] = filename
        self.filenames = filenames

        # Analyze.
        self.process()

    @classmethod
    def from_sources(cls, sources, logger=None,
                     namespace_constructors: Iterable[str] | None = None):
        """Create a CallGraphVisitor from in-memory sources (no file I/O).

        Args:
            sources: iterable of ``(source, module_name)`` pairs, where
                *source* is either a ``str`` (source text) or an
                ``ast.Module`` (parsed AST — will be unparsed via
                ``ast.unparse`` to obtain source text for ``symtable``).
                *module_name* must be the fully qualified dotted name
                (e.g. ``"pkg.sub.mod"``, not just ``"mod"``), matching
                how Python's import system identifies the module.
                For package ``__init__`` modules, append ``.__init__``
                (e.g. ``"pkg.sub.__init__"``) so that relative imports
                resolve correctly.
            logger: optional ``logging.Logger`` instance.
            namespace_constructors: see ``CallGraphVisitor.__init__``.

        Returns:
            A fully analyzed ``CallGraphVisitor``.
        """
        self = cls.__new__(cls)
        self._init_common(logger, namespace_constructors)
        self.root = ""

        # Normalize sources: unparse ASTs, store source text.
        self._source_texts = {}  # module_name → source text
        for source, module_name in sources:
            if isinstance(source, ast.AST):
                source = ast.unparse(source)
            self._source_texts[module_name] = source
            self.module_to_filename[module_name] = module_name  # use module name as stand-in
            # For __init__ modules, also register the stripped package name
            # so that import resolution can find e.g. "pkg.sub" when other
            # modules do `from . import sub`.
            if module_name.endswith(".__init__"):
                pkg_name = module_name.removesuffix(".__init__")
                self.module_to_filename[pkg_name] = module_name
        self.filenames = list(self._source_texts.keys())  # module names as "filenames"

        self.process()
        return self

    def _init_common(self, logger, namespace_constructors: Iterable[str] | None = None):
        """Shared initialization for both constructors.

        *namespace_constructors* — see ``CallGraphVisitor.__init__``.  The
        merged set (built-in registry ∪ user-supplied) is stored on
        ``self.namespace_constructors`` for the recognition path to read.
        """
        self.logger = logger or logging.getLogger(__name__)

        # Merged set of namespace-constructor FQNs (built-in + user-supplied).
        # Read by `_maybe_register_namespace_object` to upgrade the LHS of a
        # recognized binding from `Flavor.NAME` to `Flavor.NAMESPACE_OBJECT`.
        self.namespace_constructors: set[str] = NAMESPACE_CONSTRUCTORS | set(namespace_constructors or ())

        # Per-namespace map of names bound to string-literal constants.
        # Populated by `_bind_target` whenever the rhs is a string `Constant`.
        # Read by `_resolve_name_to_string_literal` for `setattr` recognition
        # when the second argument is a `Name` that has to trace back to a
        # literal. Cross-module lookups follow the same module_to_filename
        # path that import resolution uses.
        # Structure: {namespace: {name: literal_string}}
        self.name_literals = {}

        # Stack of sets; while non-empty, ``add_uses_edge`` records each edge's
        # to_node into the top set. Used by visit_FunctionDef to capture uses
        # coming from decorator arguments (#125) even when those edges already
        # exist on the enclosing module's adjacency set.
        self._decorator_use_recorders = []

        # data gathered from analysis
        self.module_to_filename = {}  # module name → filename (or module name itself in source mode)
        self.defines_edges = {}
        self.uses_edges = {}
        self.nodes = {}  # Node name: list of Node objects (in possibly different namespaces)
        self.scopes = {}  # fully qualified name of namespace: Scope object

        self.class_base_ast_nodes = {}  # pass 1: class Node: list of AST nodes
        self.class_base_nodes = {}  # pass 2: class Node: list of Node objects (local bases, no recursion)
        self.mro = {}  # pass 2: class Node: list of Node objects in Python's MRO order

        # namespace → set of module names imported in that namespace.
        # Populated by visit_Import / visit_ImportFrom.
        # Used by expand_unknowns to constrain wildcard expansion.
        self.namespace_imports = {}  # e.g. {"mymod.func": {"os", "foo.bar"}}

        # module name → set of names exposed by `from module import *`.
        # A value of None means __all__ was present but in a form we don't
        # parse (augmented, dynamic, etc.) — callers should fall back to the
        # public-names rule via ``_module_public_exports``.
        # Populated by visit_Module when a literal __all__ assignment is seen.
        self.module_all = {}  # e.g. {"pkg": {"fn1", "fn2"}}

        # current context for analysis
        self.module_name = None
        self.filename = None
        self.name_stack = []  # for building namespace name, node naming
        self.scope_stack = []  # the Scope objects currently in scope
        self.class_stack = []  # Nodes for class definitions currently in scope
        self.context_stack = []  # for detecting which FunctionDefs are methods
        self._anon_scope_idx = {}  # (parent_ns, scope_type) → next index

    def process(self):
        """Analyze the set of files, twice so that any forward-references are picked up."""
        # Prescan: populate self.scopes and self.module_all for every file
        # before the main visitor passes. This lets cross-module lookups
        # (wildcard desugaring, chiefly) succeed in pass 1 regardless of
        # the order in which filenames were given.
        for filename in self.filenames:
            self._prescan_one(filename)
        for pas in range(2):
            for filename in self.filenames:
                self.logger.info(f"========== pass {pas + 1}, file '{filename}' ==========")
                self.process_one(filename)
            if pas == 0:
                self.resolve_base_classes()  # must be done only after all files seen
        self.postprocess()

    def _prescan_one(self, filename):
        """Populate self.scopes and self.module_all for a single file.

        Reads content, runs symtable-based scope analysis, and extracts any
        literal ``__all__``. Does **not** run the main AST visitor — this is
        strictly metadata collection so that cross-module lookups during the
        subsequent visitor passes find what they need.
        """
        if hasattr(self, "_source_texts"):
            content = self._source_texts[filename]
            display_name = filename.removesuffix(".__init__") if filename.endswith(".__init__") else filename
        else:
            with open(filename, encoding="utf-8") as f:
                content = f.read()
            display_name = get_module_name(filename, root=self.root)

        saved_module_name = self.module_name
        self.module_name = display_name
        try:
            self.analyze_scopes(content, filename)
            tree = ast.parse(content, filename)
            self._extract_dunder_all(tree.body)
        finally:
            self.module_name = saved_module_name

    def process_one(self, filename):
        """Analyze one source unit (file path, or module name in source mode).

        In source mode, module names must be fully qualified; specifically,
        they must match what you passed to `from_sources` (which see).
        """
        if filename not in self.filenames:
            raise ValueError(
                f"Filename '{filename}' has not been preprocessed (was not given to __init__, which got {self.filenames})"
            )
        # In source mode, _source_texts holds the code; in file mode, read from disk.
        #
        # module_name:          display name for node naming (no __init__)
        # _import_module_name:  name for import resolution (with __init__
        #                       when applicable, matching CPython's __name__)
        if hasattr(self, "_source_texts"):
            content = self._source_texts[filename]
            self.filename = filename  # module name as stand-in
            if filename.endswith(".__init__"):
                self.module_name = filename.removesuffix(".__init__")
                self._import_module_name = filename
            else:
                self.module_name = filename
                self._import_module_name = filename
        else:
            with open(filename, encoding="utf-8") as f:
                content = f.read()
            self.filename = filename
            self.module_name = get_module_name(filename, root=self.root)
            if filename.endswith("__init__.py"):
                self._import_module_name = self.module_name + ".__init__"
            else:
                self._import_module_name = self.module_name
        self._anon_scope_idx = {}  # reset per source unit — must match between analyze_scopes and visitor
        self.analyze_scopes(content, self.filename)  # add to the currently known scopes
        self.visit(ast.parse(content, self.filename))
        self.module_name = None
        self.filename = None

    def resolve_base_classes(self):
        """Resolve base classes from AST nodes to Nodes.

        Run this between pass 1 and pass 2 to pick up inherited methods.
        Currently, this can parse ast.Names and ast.Attributes as bases.
        """
        self.logger.debug("Resolving base classes")
        assert len(self.scope_stack) == 0  # only allowed between passes
        for node in self.class_base_ast_nodes:  # Node: list of AST nodes
            self.class_base_nodes[node] = []
            for ast_node in self.class_base_ast_nodes[node]:
                # perform the lookup in the scope enclosing the class definition
                self.scope_stack.append(self.scopes[node.namespace])

                if isinstance(ast_node, ast.Name):
                    baseclass_node = self.get_value(ast_node.id)
                elif isinstance(ast_node, ast.Attribute):
                    _, baseclass_node = self.get_attribute(ast_node)  # don't care about obj, just grab attr
                else:  # give up
                    baseclass_node = None

                self.scope_stack.pop()

                if isinstance(baseclass_node, Node) and baseclass_node.namespace is not None:
                    self.class_base_nodes[node].append(baseclass_node)

        self.logger.debug(f"All base classes (non-recursive, local level only): {self.class_base_nodes}")

        self.logger.debug("Resolving method resolution order (MRO) for all analyzed classes")
        self.mro = resolve_method_resolution_order(self.class_base_nodes, self.logger)
        self.logger.debug(f"Method resolution order (MRO) for all analyzed classes: {self.mro}")

    def postprocess(self):
        """Finalize the analysis. Pipeline lives in :mod:`pyan.postprocessor`."""
        postprocess(self)

    ###########################################################################
    # visitor methods

    # In visit_*(), the "node" argument refers to an AST node.

    # Python docs:
    # https://docs.python.org/3/library/ast.html#abstract-grammar

    def filter(self, node: None | Node = None, namespace: str | None = None,
               max_iter: int = 1000, direction: str = "both"):
        """Filter the graph to nodes related to `node` or in `namespace`.

        Args:
            node: pyan node for which related nodes should be found.
                If None, filter only by namespace.
            namespace: namespace to search in (name of top level module).
                If None, determined from `node`.
            max_iter: maximum number of iterations and nodes to iterate.
            direction: traversal direction — ``"both"`` (default),
                ``"down"`` (callees: what does this node call?),
                or ``"up"`` (callers: what calls this node?).

        Returns:
            self
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
        """Collapse the graph to at most `max_depth` nesting levels.

        Depth is relative to each node's containing module, so the
        result is consistent regardless of how many dots are in the
        module's fully qualified name (e.g. ``pkg.sub.mod``).

        Nodes deeper than `max_depth` are removed. Edges involving
        removed nodes are redirected to their ancestor at `max_depth`,
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
            """Return the ancestor ``Node`` of `node` at `max_depth`."""
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
        """Get nodes related to `node` or in `namespace`.

        Args:
            node: starting node. If None, filter only by namespace.
            namespace: namespace to search in. If None, determined from `node`.
            max_iter: maximum BFS iterations.
            direction: ``"both"`` (follow edges in both directions),
                ``"down"`` (forward edges only — callees/children),
                ``"up"`` (reverse edges only — callers/parents).

        Returns:
            Set of related nodes including `node` itself.
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
        """Find simple paths from `from_node` to `to_node` via uses edges.

        Uses DFS; results are sorted shortest-first after collection.
        Note that DFS discovers paths in arbitrary order, so with a low
        ``max_paths`` the shortest path may not be among those found.

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
        """Format a list of paths (from `find_paths`) as human-readable text.

        Returns one path per line, ``->`` delimited, shortest first.
        """
        lines = []
        for path in paths:
            names = [n.name for n in path]
            lines.append(" -> ".join(names))
        return "\n".join(lines)

    def visit_Module(self, node):
        self.logger.debug(f"Module {self.module_name}, {self.filename}")

        # Modules live in the top-level namespace, ''.
        module_node = self.get_node("", self.module_name, node, flavor=Flavor.MODULE)
        self.associate_node(module_node, node, filename=self.filename)

        # Extract __all__ so that `from module import *` can desugar against it
        # (or against the public-names rule when absent). Done at module entry,
        # before visiting children, so the data is available if this module is
        # itself visited later during the same pass — see visit_ImportFrom.
        self._extract_dunder_all(node.body)

        with self._module_scope(self.module_name):
            self.generic_visit(node)  # visit the **children** of node

        if self.add_defines_edge(module_node, None):
            self.logger.info(f"Def Module {node}")

    def _extract_dunder_all(self, module_body):
        """Record the current module's ``__all__`` in ``self.module_all``.

        Parses only the simple literal forms::

            __all__ = ["a", "b"]
            __all__ = ("a", "b")
            __all__: list[str] = ["a", "b"]   # PEP 526 annotated assignment

        Anything else — augmented assignment (``__all__ += [...]``), calls
        (``__all__ = _compute()``), or non-string elements — is skipped with
        a debug log, leaving callers to fall back to the public-names rule.

        Multiple top-level ``__all__`` assignments: the last one wins, matching
        Python's own binding semantics.
        """
        names = None
        saw_unparseable = False
        for stmt in module_body:
            target_value = None
            if isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                        target_value = stmt.value
                        break
            elif isinstance(stmt, ast.AnnAssign):
                if (isinstance(stmt.target, ast.Name)
                        and stmt.target.id == "__all__"
                        and stmt.value is not None):
                    target_value = stmt.value
            elif isinstance(stmt, ast.AugAssign):  # noqa: SIM102 -- outer dispatches on stmt type, inner checks target name
                if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__":
                    saw_unparseable = True
                    continue

            if target_value is None:
                continue

            if isinstance(target_value, (ast.List, ast.Tuple)) and all(
                isinstance(e, ast.Constant) and isinstance(e.value, str)
                for e in target_value.elts
            ):
                names = {e.value for e in target_value.elts}
            else:
                saw_unparseable = True
                names = None  # discard any prior literal — last assignment wins

        if saw_unparseable and names is None:
            self.logger.debug(
                f"__all__ in module '{self.module_name}' uses a form pyan does not parse "
                f"(augmented/dynamic); falling back to the public-names rule"
            )
        if names is not None:
            self.module_all[self.module_name] = names

    def visit_ClassDef(self, node):
        self.logger.debug(f"ClassDef {node.name}, {self.filename}:{node.lineno}")

        # Visit decorators in the enclosing scope (Python evaluates them there
        # at definition time), recording every use target touched. We replay
        # those as uses of the decorated class below (#125).
        decorator_uses = set()
        self._decorator_use_recorders.append(decorator_uses)
        try:
            for deco in node.decorator_list:
                self.visit(deco)
        finally:
            self._decorator_use_recorders.pop()

        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name, node, flavor=Flavor.CLASS)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info(f"Def from {from_node} to Class {to_node}")

        # The graph Node may have been created earlier by a FromImport,
        # in which case its AST node points to the site of the import.
        #
        # Change the AST node association of the relevant graph Node
        # to this AST node (the definition site) to get the correct
        # source line number information in annotated output.
        #
        self.associate_node(to_node, node, self.filename)

        # Bind the name specified by the AST node to the graph Node
        # in the current scope.
        #
        self.set_value(node.name, to_node)

        # PEP 695 (#123): the type-parameter closure scope (if any) sits
        # between the enclosing scope and the class scope on scope_stack,
        # matching Python's actual lexical structure for generic classes.
        with (self._type_params_scope(node.name),
              self._class_scope(node, to_node)):
            self.class_base_ast_nodes[to_node] = []
            for b in node.bases:
                # gather info for resolution of inherited attributes in pass 2 (see get_attribute())
                self.class_base_ast_nodes[to_node].append(b)
                # mark uses from a derived class to its bases (via names appearing in a load context).
                self.visit(b)

            # Re-emit decorator-argument uses from the class node (same
            # rationale as in visit_FunctionDef).
            for tgt in decorator_uses:
                self.add_uses_edge(to_node, tgt)

            for stmt in node.body:
                self.visit(stmt)

    def visit_FunctionDef(self, node):
        self.logger.debug(f"FunctionDef {node.name}, {self.filename}:{node.lineno}")

        # To begin with:
        #
        # - Analyze decorators. They belong to the surrounding scope,
        #   so we must analyze them before entering the function scope.
        #   Record every use target touched during that analysis (#125);
        #   see the re-attribution below.
        #
        # - Determine whether this definition is for a function, an (instance)
        #   method, a static method or a class method.
        #
        # - Grab the name representing "self", if this is either an instance
        #   method or a class method. (For a class method, it represents cls,
        #   but Pyan only cares about types, not instances.)
        #
        decorator_uses = set()
        self._decorator_use_recorders.append(decorator_uses)
        try:
            self_name, flavor = self.analyze_functiondef(node)
        finally:
            self._decorator_use_recorders.pop()

        # Now we can create the Node.
        #
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name, node, flavor=flavor)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info(f"Def from {from_node} to Function {to_node}")

        # Same remarks as for ClassDef above.
        #
        self.associate_node(to_node, node, self.filename)
        self.set_value(node.name, to_node)

        # Visit default values in the enclosing scope.
        #
        # Python evaluates defaults at function *definition* time in the
        # enclosing scope, so any lambdas or calls they contain belong
        # to the enclosing scope's symtable children — not the function's.
        #
        default_values = self._visit_function_defaults(node.args)

        # PEP 695 (#123): the type-parameter closure scope (if any) sits
        # between the enclosing and function scopes.  Defaults are visited
        # above in the enclosing scope (matching Python's evaluation
        # semantics).
        with (self._type_params_scope(node.name),
              self._function_scope(node) as inner_ns):

            # Capture which names correspond to function args.
            #
            self.generate_args_nodes(node.args, inner_ns)

            # self_name is just an ordinary name in the method namespace, except
            # that its value is implicitly set by Python when the method is called.
            #
            # Bind self_name in the function namespace to its initial value,
            # i.e. the current class. (Class, because Pyan cares only about
            # object types, not instances.)
            #
            # After this point, self_name behaves like any other name.
            #
            if self_name is not None:
                class_node = self.get_current_class()
                self.scopes[inner_ns].defs[self_name] = class_node
                self.logger.info(f'Method def: setting self name "{self_name}" to {class_node}')

            # Bind args to the default values that were already visited above.
            self._bind_function_defaults(node.args, default_values)

            # Supplement uses edges: defaults were visited in the enclosing scope
            # (for symtable correctness), but the function itself also "uses" the
            # names referenced in its defaults — e.g. `def f(cb=some_func)` should
            # show `f → some_func`.
            self._record_default_uses_in_function(node.args)

            # Same treatment for decorator arguments (#125). Decorators are
            # visited in the enclosing scope (Python evaluates them there at
            # definition time), but the decorated function is meaningfully tied
            # to whatever names the decorator references — e.g.
            # `@app.get("/x", dependencies=[Depends(Guard())])` should show
            # the function using Depends and Guard, not just the module.
            for tgt in decorator_uses:
                self.add_uses_edge(to_node, tgt)

            # Visit type annotations to create uses edges for referenced types.
            #
            # NOTE: Strictly, Python evaluates annotations in the *enclosing*
            # scope (like defaults), so visiting them here — inside the function
            # scope — is technically wrong. We do it anyway because attributing
            # annotation uses edges to the function (rather than the module) is
            # far more useful in the call graph. This works because annotations
            # rarely contain expressions that trigger scope lookups (lambdas,
            # comprehensions). If an edge case surfaces, defaults show the
            # pattern: visit in enclosing scope, bind inside.
            self._visit_function_annotations(node)

            # Analyze the function body
            #
            for stmt in node.body:
                self.visit(stmt)

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)  # TODO: alias for now; tag async functions in output in a future version?

    def visit_Lambda(self, node):
        self.logger.debug(f"Lambda, {self.filename}:{node.lineno}")
        numbered_label = self._next_anon_scope_name("lambda", node)
        with ExecuteInInnerScope(self, numbered_label) as scope_ctx:
            self.generate_args_nodes(node.args, scope_ctx.inner_ns)
            self.analyze_arguments(node.args)
            self.visit(node.body)  # single expr
        return scope_ctx.inner_scope_node

    def generate_args_nodes(self, ast_args, inner_ns):
        """Capture which names correspond to function args.

        In the function scope, set them to a nonsense Node,
        to prevent leakage of identifiers of matching name
        from the enclosing scope (due to the local value being None
        until we set it to this nonsense Node).

        ast_args: node.args from a FunctionDef or Lambda
        inner_ns: namespace of the function or lambda, for scope lookup
        """
        sc = self.scopes[inner_ns]
        # As the name of the nonsense node, we can use any string that
        # is not a valid Python identifier.
        #
        # It has no sensible flavor, so we leave its flavor unspecified.
        nonsense_node = self.get_node(inner_ns, "^^^argument^^^", None)
        # args, vararg (*args), kwonlyargs, kwarg (**kwargs)
        for a in ast_args.args:  # positional
            sc.defs[a.arg] = nonsense_node
        if ast_args.vararg is not None:  # *args if present
            sc.defs[ast_args.vararg] = nonsense_node
        for a in ast_args.kwonlyargs:  # any after *args or *
            sc.defs[a.arg] = nonsense_node
        if ast_args.kwarg is not None:  # **kwargs if present
            sc.defs[ast_args.kwarg] = nonsense_node

    def analyze_arguments(self, ast_args):
        """Analyze an arguments node of the AST.

        Record bindings of args to the given default values, if present.

        Used for analyzing FunctionDefs and Lambdas."""
        # https://greentreesnakes.readthedocs.io/en/latest/nodes.html?highlight=functiondef#arguments
        if ast_args.defaults:
            n = len(ast_args.defaults)
            for tgt, val in zip(ast_args.args[-n:], ast_args.defaults, strict=False):
                targets = canonize_exprs(tgt)
                values = canonize_exprs(val)
                self.analyze_binding(targets, values)
        if ast_args.kw_defaults:
            n = len(ast_args.kw_defaults)
            for tgt, val in zip(ast_args.kwonlyargs, ast_args.kw_defaults, strict=False):
                if val is not None:
                    targets = canonize_exprs(tgt)
                    values = canonize_exprs(val)
                    self.analyze_binding(targets, values)

    def _visit_function_defaults(self, ast_args):
        """Visit default value expressions and return the resolved Nodes.

        Called in the enclosing scope, before entering the function scope,
        because Python evaluates defaults at definition time.

        Returns a (pos_defaults, kw_defaults) pair of lists, parallel to
        ``ast_args.defaults`` and ``ast_args.kw_defaults``.
        """
        pos = [self.visit(val) for val in ast_args.defaults] if ast_args.defaults else []
        kw = [self.visit(val) if val is not None else None
              for val in ast_args.kw_defaults] if ast_args.kw_defaults else []
        return pos, kw

    def _bind_function_defaults(self, ast_args, default_values):
        """Bind function args to their pre-visited default values.

        Called inside the function scope. ``default_values`` is the pair
        returned by ``_visit_function_defaults``.
        """
        pos, kw = default_values
        if pos:
            n = len(pos)
            for tgt, val in zip(ast_args.args[-n:], pos, strict=False):
                self._bind_target(tgt, val)
        if kw:
            for tgt, val in zip(ast_args.kwonlyargs, kw, strict=False):
                if val is not None:
                    self._bind_target(tgt, val)

    def _record_default_uses_in_function(self, ast_args):
        """Record uses edges from the current function to names in default values.

        Default value expressions are visited in the enclosing scope (by
        ``_visit_function_defaults``) because Python evaluates them at definition
        time. But for call-graph purposes, the function *uses* those names —
        e.g. ``def f(cb=some_func)`` should show ``f → some_func``.

        This walks default value ASTs and adds supplementary uses edges from the
        function (the current namespace) without re-triggering the full visitor
        (which would conflict with symtable scope expectations).
        """
        from_node = self.get_node_of_current_namespace()
        defaults = list(ast_args.defaults or [])
        defaults.extend(v for v in (ast_args.kw_defaults or []) if v is not None)
        for val in defaults:
            for ast_node in ast.walk(val):
                if isinstance(ast_node, ast.Name) and isinstance(ast_node.ctx, ast.Load):
                    to_node = self.get_value(ast_node.id)
                    if not isinstance(to_node, Node):
                        if ast_node.id in self.scope_stack[-1].locals:
                            continue
                        to_node = self.get_node(None, ast_node.id, ast_node, flavor=Flavor.UNKNOWN)
                    self.add_uses_edge(from_node, to_node)

    def _visit_function_annotations(self, node):
        """Visit type annotations on a FunctionDef in the current (enclosing) scope."""
        if node.returns is not None:
            self.visit(node.returns)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)

    def _record_import(self, target_module):
        """Record that the current namespace imports from `target_module`.

        Stores both the literal import name and, if it can be resolved
        against the known module set, the fully qualified module name.
        This handles cases where import statements use short names but
        the analyzer's internal names are fully qualified.
        """
        ns = self.get_node_of_current_namespace().get_name()
        imports = self.namespace_imports.setdefault(ns, set())
        imports.add(target_module)
        # Also record the fully qualified form if the short name is a suffix
        # of a known module (e.g. "defines_myfunc" → "pkg.defines_myfunc").
        for fq_name in self.module_to_filename:
            if fq_name == target_module or fq_name.endswith("." + target_module):
                imports.add(fq_name)

    def visit_Import(self, node):
        self.logger.debug(f"Import {[format_alias(x) for x in node.names]}, {self.filename}:{node.lineno}")

        # TODO: add support for relative imports (path may be like "....something.something")
        # https://www.python.org/dev/peps/pep-0328/#id10

        for import_item in node.names:  # the names are modules
            self._record_import(import_item.name)
            self.analyze_module_import(import_item, node)

    def visit_ImportFrom(self, node):
        self.logger.debug(
            f"ImportFrom: from {node.module} import {[format_alias(x) for x in node.names]}, {self.filename}:{node.lineno}"
        )
        # Pyan needs to know the package structure, and how the program
        # being analyzed is actually going to be invoked (!), to be able to
        # resolve relative imports correctly.
        #
        # As a solution, we register imports here and later, when all files have been parsed, resolve them.
        from_node = self.get_node_of_current_namespace()
        if node.module is None:  # "from . import foo" — node.module is None
            self.logger.debug(
                "ImportFrom (original) from {} import {}, {}:{}".format("." * node.level, [format_alias(x) for x in node.names], self.filename, node.lineno)
            )
            tgt_name = resolve_import(current=self._import_module_name, target="", level=node.level, logger=self.logger)
            self.logger.debug(
                f"ImportFrom (resolved): from {tgt_name} import {[format_alias(x) for x in node.names]}, {self.filename}:{node.lineno}"
            )
        elif node.level != 0:  # "from ..module import foo"
            self.logger.debug(
                f"ImportFrom (original): from {node.module} import {[format_alias(x) for x in node.names]}, {self.filename}:{node.lineno}"
            )
            tgt_name = resolve_import(current=self._import_module_name, target=node.module, level=node.level, logger=self.logger)
            self.logger.debug(
                f"ImportFrom (resolved): from {tgt_name} import {[format_alias(x) for x in node.names]}, {self.filename}:{node.lineno}"
            )
        else:
            tgt_name = node.module  # normal from module.submodule import foo

        self._record_import(tgt_name)

        # Desugar `from tgt_name import *` against the target module's public
        # exports (__all__ if literal, otherwise the public-names rule). If the
        # target wasn't analyzed — or hasn't been visited yet in this pass —
        # we leave the wildcard alone; pass 2 (or expand_unknowns) will handle
        # what it can. See _module_public_exports for the lookup rules.
        names = node.names
        if len(names) == 1 and names[0].name == "*":
            exports = self._module_public_exports(tgt_name)
            if exports is not None:
                self.logger.debug(
                    f"Desugaring 'from {tgt_name} import *' to {sorted(exports)}, "
                    f"{self.filename}:{node.lineno}"
                )
                # Synthesize aliases for each exported name. asname=None because
                # star-import can't rebind (there's no `as` clause on `*`).
                names = [ast.alias(name=n, asname=None) for n in exports]

        # link each import separately
        for alias in names:
            # check if import is module
            if tgt_name + "." + alias.name in self.module_to_filename:
                to_node = self.get_node("", tgt_name + "." + alias.name, node, flavor=Flavor.MODULE)
            else:
                to_node = self.get_node(tgt_name, alias.name, node, flavor=Flavor.IMPORTEDITEM)
            # if there is alias, add extra edge between alias and node
            alias_name = alias.asname if alias.asname is not None else alias.name
            self.set_value(alias_name, to_node)  # set node to be discoverable in module
            self.logger.info(f"From setting name {alias_name} to {to_node}")

            self.logger.debug(f"Use from {from_node} to ImportFrom {to_node}")
            if self.add_uses_edge(from_node, to_node):
                self.logger.info(f"New edge added for Use from {from_node} to ImportFrom {to_node}")

    def _module_public_exports(self, module_name):
        """Return the set of names exposed by ``from module_name import *``.

        If the module declares a literal ``__all__`` (see ``_extract_dunder_all``),
        that set is authoritative — even a leading-underscore name counts if listed.
        Otherwise the public-names rule applies: every name bound at module scope
        whose identifier does not start with an underscore.

        *module_name* may be a short name from an import statement
        (``"common"``) or a fully qualified one (``"pkg.sub.common"``); both are
        resolved against the analyzer's known module set, mirroring what
        ``_record_import`` does for ``namespace_imports``.

        Returns ``None`` when no matching analyzed module is found.
        Callers are expected to fall back to the current wildcard-IMPORTEDITEM
        behavior in that case.
        """
        for candidate in self._module_name_candidates(module_name):
            if candidate in self.module_all:
                return self.module_all[candidate]
            scope = self.scopes.get(candidate)
            if scope is not None:
                return {n for n in scope.defs if not n.startswith("_")}
        return None

    def _module_name_candidates(self, module_name):
        """Yield fully qualified module names that could match *module_name*.

        First yields *module_name* itself (handles the fully qualified case),
        then any analyzed module whose FQ name ends in ``"." + module_name``
        (handles short names from absolute imports where the project root adds
        extra prefix components, e.g. ``from common import *`` matching
        ``tests.fixtures.common``).
        """
        yield module_name
        suffix = "." + module_name
        for fq_name in self.module_to_filename:
            if fq_name.endswith(suffix) and fq_name != module_name:
                yield fq_name

    def analyze_module_import(self, import_item, ast_node):
        """Analyze a names AST node inside an Import or ImportFrom AST node.

        This handles the case where the objects being imported are modules.

        import_item: an item of ast_node.names
        ast_node: for recording source location information
        """
        src_name = import_item.name  # what is being imported

        # mark the use site
        #
        # where it is being imported to, i.e. the **user**
        from_node = self.get_node_of_current_namespace()
        # the thing **being used** (under the asname, if any)
        mod_node = self.get_node("", src_name, ast_node, flavor=Flavor.MODULE)
        # if there is alias, add extra edge between alias and node
        alias_name = import_item.asname if import_item.asname is not None else mod_node.name
        self.add_uses_edge(from_node, mod_node)
        self.logger.info(f"New edge added for Use import {mod_node} in {from_node}")
        self.set_value(alias_name, mod_node)  # set node to be discoverable in module
        self.logger.info(f"From setting name {alias_name} to {mod_node}")

    # Edmund Horner's original post has info on what this fixed in Python 2.
    # https://ejrh.wordpress.com/2012/01/31/call-graphs-in-python-part-2/
    #
    # Essentially, this should make '.'.join(...) see str.join.
    # Pyan3 currently handles that in resolve_attribute() and get_attribute().
    #
    # Python 3.4 does not have ast.Constant, but 3.6 does.
    # TODO: actually test this with Python 3.6 or later.
    #
    def visit_Constant(self, node):
        self.logger.debug(f"Constant {node.value}, {self.filename}:{node.lineno}")
        t = type(node.value)
        ns = self.get_node_of_current_namespace().get_name()
        tn = t.__name__
        return self.get_node(ns, tn, node, flavor=Flavor.ATTRIBUTE)

    # attribute access (node.ctx is ast.Load/Store/Del)
    # Store context: handled by _bind_target
    # Del context: handled by visit_Delete (protocol method edges)
    def visit_Attribute(self, node):
        objname = get_ast_node_name(node.value)
        self.logger.debug(
            f"Attribute {node.attr} of {objname} in context {type(node.ctx)}, {self.filename}:{node.lineno}"
        )

        if isinstance(node.ctx, ast.Load):
            try:
                obj_node, attr_node = self.get_attribute(node)
            except UnresolvedSuperCallError:
                # Avoid adding a wildcard if the lookup failed due to an
                # unresolved super() in the attribute chain.
                return

            # Both object and attr known.
            if isinstance(attr_node, Node):
                self.logger.info(f"getattr {node.attr} on {objname} returns {attr_node}")

                # add uses edge
                from_node = self.get_node_of_current_namespace()
                self.logger.debug(f"Use from {from_node} to {attr_node}")
                if self.add_uses_edge(from_node, attr_node):
                    self.logger.info(f"New edge added for Use from {from_node} to {attr_node}")

                # If the resolved attr won't appear in the graph (not defined),
                # also connect to the object itself or — if the object is also
                # not defined — its immediate parent.  This handles Enum members
                # and class constants (Color.RED → Color), as well as
                # namespace-style modules (#127): a module that exports a
                # runtime-built object whose attributes are accessed by callers
                # remains invisible in the call graph if no fallback fires.
                # Stepping up to the object's parent lands on the module Node,
                # which surfaces the cross-module coupling.
                if not attr_node.defined and isinstance(obj_node, Node):
                    ancestor = self._defined_self_or_parent(obj_node)
                    if ancestor is not None and not self._within(from_node, ancestor):  # noqa: SIM102 -- guard + log-on-success: outer asks "should we add?", inner asks "did we add (vs. already present)?"
                        if self.add_uses_edge(from_node, ancestor):
                            self.logger.info(f"New edge added for Use from {from_node} to defined ancestor {ancestor} (attr {node.attr} not defined)")

                # remove resolved wildcard from current site to <Node *.attr>
                if attr_node.namespace is not None:
                    self.remove_wild(from_node, attr_node, node.attr)

                return attr_node

            # Object known, but attr unknown. Create node and add a uses edge.
            #
            # TODO: this is mainly useful for imports. Should probably disallow
            # creating new attribute nodes for other undefined attrs of known objs.
            #
            # E.g.
            #
            # import math  # create <Node math>
            # math.sin     # create <Node math.sin> (instead of <Node *.sin> even though math.py is not analyzed)
            #
            # This sometimes creates silly nodes such as (when analyzing Pyan itself)
            # <Node pyan.analyzer.CallGraphVisitor.defines_edges.name.namespace>
            # but these are harmless, as they are considered undefined and
            # will not be visualized.
            #
            elif isinstance(obj_node, Node) and obj_node.namespace is not None:
                tgt_name = node.attr
                from_node = self.get_node_of_current_namespace()
                ns = obj_node.get_name()  # fully qualified namespace **of attr**
                to_node = self.get_node(ns, tgt_name, node, flavor=Flavor.ATTRIBUTE)
                self.logger.debug(
                    f"Use from {from_node} to {to_node} (target obj {obj_node} known but target attr "
                    f"{node.attr} not resolved; maybe fwd ref or unanalyzed import)"
                )
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(
                        "New edge added for Use from {from_node} to {to_node} (target obj {obj_node} known but "
                        f"target attr {node.attr} not resolved; maybe fwd ref or unanalyzed import)"
                    )

                # Same as above: also connect to the object itself (or its
                # immediate parent if the object isn't defined either), so the
                # cross-module coupling stays visible even when the attribute
                # itself isn't statically resolvable.
                ancestor = self._defined_self_or_parent(obj_node)
                if ancestor is not None and not self._within(from_node, ancestor):  # noqa: SIM102 -- guard + log-on-success: outer asks "should we add?", inner asks "did we add (vs. already present)?"
                    if self.add_uses_edge(from_node, ancestor):
                        self.logger.info(f"New edge added for Use from {from_node} to defined ancestor {ancestor} (attr {node.attr} unresolved)")

                # remove resolved wildcard from current site to <Node *.attr>
                self.remove_wild(from_node, obj_node, node.attr)

                return to_node

            # pass on
            else:
                return self.visit(node.value)
        # Store context: handled by _bind_target
        # Del context: handled by visit_Delete (protocol method edges)

    # name access (node.ctx is ast.Load/Store/Del)
    # Store context: handled by _bind_target
    # Del context: handled by visit_Delete (protocol method edges)
    def visit_Name(self, node):
        self.logger.debug(f"Name {node.id} in context {type(node.ctx)}, {self.filename}:{node.lineno}")

        if isinstance(node.ctx, ast.Load):
            tgt_name = node.id
            to_node = self.get_value(tgt_name)  # resolves "self" if needed
            current_class = self.get_current_class()
            if current_class is None or to_node is not current_class:  # add uses edge only if not pointing to "self"
                if not isinstance(to_node, Node):
                    # Local with no resolved value — no useful type info, skip.
                    if tgt_name in self.scope_stack[-1].locals:
                        return None
                    # namespace=None means we don't know the namespace yet
                    to_node = self.get_node(None, tgt_name, node, flavor=Flavor.UNKNOWN)

                from_node = self.get_node_of_current_namespace()
                self.logger.debug(f"Use from {from_node} to Name {to_node}")
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(f"New edge added for Use from {from_node} to Name {to_node}")

            return to_node
        # Store context: handled by _bind_target
        # Del context: handled by visit_Delete (protocol method edges)

    def visit_Assign(self, node):
        # - chaining assignments like "a = b = c" produces multiple targets
        # - tuple unpacking works as a separate mechanism on top of that (see analyze_binding())
        #
        if len(node.targets) > 1:
            self.logger.debug(f"Assign (chained with {len(node.targets)} outputs)")

        # TODO: support lists, dicts, sets (so that we can recognize calls to their methods)
        # TODO: begin with supporting empty lists, dicts, sets
        # TODO: need to be more careful in sanitizing; currently destroys a bare list

        values = canonize_exprs(node.value)  # values is the same for each set of targets
        for targets in node.targets:
            targets = canonize_exprs(targets)
            self.logger.debug(
                f"Assign {[get_ast_node_name(x) for x in targets]} {[get_ast_node_name(x) for x in values]}, {self.filename}:{node.lineno}"
            )
            self.analyze_binding(targets, values)

    def visit_AnnAssign(self, node):  # PEP 526, Python 3.6+
        if node.value is not None:
            targets = canonize_exprs(node.target)
            values = canonize_exprs(node.value)
            # issue #62: value may be an empty list, so it doesn't always have any elements
            # even after `canonize_exprs`.
            self.logger.debug(
                f"AnnAssign {get_ast_node_name(node.target)} {get_ast_node_name(node.value)}, {self.filename}:{node.lineno}"
            )
            self.analyze_binding(targets, values)
        else:  # just a type declaration
            self.logger.debug(
                f"AnnAssign {get_ast_node_name(node.target)} <no value>, {self.filename}:{node.lineno}"
            )
            self._bind_target(node.target, None)
        # Visit the type annotation to create uses edges for referenced types.
        if node.annotation is not None:
            self.visit(node.annotation)

    def visit_NamedExpr(self, node):  # PEP 572, Python 3.8+  (walrus operator :=)
        self.logger.debug(
            f"NamedExpr {get_ast_node_name(node.target)}, {self.filename}:{node.lineno}"
        )
        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.value)
        self.analyze_binding(targets, values)
        # Unlike plain assignment, walrus is an *expression* — the enclosing
        # context needs the bound value.
        return self.get_value(node.target.id)

    def visit_TypeAlias(self, node):  # PEP 695, Python 3.12+
        self.logger.debug(f"TypeAlias {node.name.id}, {self.filename}:{node.lineno}")

        # Create defines edge for the alias name.
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, node.name.id, node, flavor=Flavor.NAME)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info(f"Def from {from_node} to TypeAlias {to_node}")
        self.associate_node(to_node, node, self.filename)
        self.set_value(node.name.id, to_node)

        # Visit the type value inside its scope.  For parameterized aliases,
        # the type-parameter closure scope is pushed first (see #123);
        # analyze_scopes stores it under a synthetic key so that both
        # parameterized and simple aliases have their type-alias scope
        # directly under the enclosing namespace.
        with (self._type_params_scope(node.name.id),
              ExecuteInInnerScope(self, node.name.id)):
            self.visit(node.value)

    def visit_AugAssign(self, node):
        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.value)  # values is the same for each set of targets

        self.logger.debug(
            f"AugAssign {[get_ast_node_name(x) for x in targets]} {type(node.op)} {[get_ast_node_name(x) for x in values]}, {self.filename}:{node.lineno}"
        )

        # TODO: maybe no need to handle tuple unpacking in AugAssign? (but simpler to use the same implementation)
        self.analyze_binding(targets, values)

    # for() is also a binding form.
    #
    # (Without analyzing the bindings, we would get an unknown node for any
    #  use of the loop counter(s) in the loop body. This would have confusing
    #  consequences in the expand_unknowns() step, if the same name is
    #  in use elsewhere.)
    #
    def _add_iterator_protocol_edges(self, iter_node, is_async=False):
        """Add uses edges for the iterator protocol on `iter_node`.

        Sync iteration:  ``__iter__`` + ``__next__``
        Async iteration: ``__aiter__`` + ``__anext__``
        """
        if isinstance(iter_node, Node):
            from_node = self.get_node_of_current_namespace()
            methods = ("__aiter__", "__anext__") if is_async else ("__iter__", "__next__")
            for methodname in methods:
                to_node = self.get_node(iter_node.get_name(), methodname, None, flavor=Flavor.METHOD)
                self.logger.debug(f"Use from {from_node} to {to_node} (iteration)")
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(f"New edge added for Use from {from_node} to {to_node} (iteration)")

    def visit_For(self, node):
        self.logger.debug(f"For-loop, {self.filename}:{node.lineno}")

        # Visit the iterable to resolve the object node, then add protocol edges.
        # NOTE: node.iter is visited again inside analyze_binding(); the double
        # visit is harmless (resolves to the same node, edges deduplicate).
        iter_node = self.visit(node.iter)
        self._add_iterator_protocol_edges(iter_node)

        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.iter)
        self.analyze_binding(targets, values)

        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_AsyncFor(self, node):
        self.logger.debug(f"AsyncFor-loop, {self.filename}:{node.lineno}")

        # NOTE: node.iter is visited again inside analyze_binding(); the double
        # visit is harmless (resolves to the same node, edges deduplicate).
        iter_node = self.visit(node.iter)
        self._add_iterator_protocol_edges(iter_node, is_async=True)

        targets = canonize_exprs(node.target)
        values = canonize_exprs(node.iter)
        self.analyze_binding(targets, values)

        for stmt in node.body:
            self.visit(stmt)
        for stmt in node.orelse:
            self.visit(stmt)

    def visit_ListComp(self, node):
        self.logger.debug(f"ListComp, {self.filename}:{node.lineno}")
        return self.analyze_comprehension(node, "listcomp")

    def visit_SetComp(self, node):
        self.logger.debug(f"SetComp, {self.filename}:{node.lineno}")
        return self.analyze_comprehension(node, "setcomp")

    def visit_DictComp(self, node):
        self.logger.debug(f"DictComp, {self.filename}:{node.lineno}")
        return self.analyze_comprehension(node, "dictcomp", field1="key", field2="value")

    def visit_GeneratorExp(self, node):
        self.logger.debug(f"GeneratorExp, {self.filename}:{node.lineno}")
        return self.analyze_comprehension(node, "genexpr")

    def _next_anon_scope_name(self, scope_type, ast_node):
        """Return a numbered scope name like ``listcomp.0``, ``lambda.1``, etc.

        Each anonymous scope instance in a parent namespace gets a unique index,
        so that multiple comprehensions or lambdas don't share bindings.

        The AST node is used for deduplication: if the same node is visited
        more than once (e.g. a ``for`` loop iter expression visited by both
        ``visit_For`` and ``analyze_binding``), the same name is returned.
        """
        parent_ns = self.get_node_of_current_namespace().get_name()
        # Dedup by AST node identity (line + col is unique per scope instance).
        dedup_key = (parent_ns, scope_type, ast_node.lineno, ast_node.col_offset)
        if dedup_key in self._anon_scope_idx:
            return self._anon_scope_idx[dedup_key]
        count_key = (parent_ns, scope_type)
        idx = self._anon_scope_idx.get(count_key, 0)
        self._anon_scope_idx[count_key] = idx + 1
        name = f"{scope_type}.{idx}"
        self._anon_scope_idx[dedup_key] = name
        return name

    def analyze_comprehension(self, node, label, field1="elt", field2=None):
        """Analyze a comprehension node (listcomp, setcomp, dictcomp, genexpr).

        field1 and field2 name the AST attributes holding the output expression(s):
        ListComp/SetComp/GeneratorExp use ``elt``; DictComp uses ``key`` and ``value``.

        Returns the inner scope Node representing the comprehension, so that
        callers (e.g. ``analyze_binding``) can bind it to a target.
        """
        # The outermost iterator is evaluated in the current scope;
        # everything else in the new inner scope.
        #
        # See function symtable_handle_comprehension() in
        #   https://github.com/python/cpython/blob/master/Python/symtable.c
        # For how it works, see
        #   https://stackoverflow.com/questions/48753060/what-are-these-extra-symbols-in-a-comprehensions-symtable
        # For related discussion, see
        #   https://bugs.python.org/issue10544
        gens = node.generators  # tuple of ast.comprehension
        outermost = gens[0]
        moregens = gens[1:] if len(gens) > 1 else []

        outermost_iters = canonize_exprs(outermost.iter)
        outermost_targets = canonize_exprs(outermost.target)
        # Evaluate outermost iterator in current scope.
        iter_node = None
        for expr in outermost_iters:
            iter_node = self.visit(expr)
        self._add_iterator_protocol_edges(iter_node, is_async=outermost.is_async)

        # Give each comprehension instance a unique scope name (e.g. listcomp.0,
        # listcomp.1) so that multiple comprehensions in the same function don't
        # share bindings.  The numbering must match analyze_scopes() (pre-3.12)
        # since both iterate children/nodes in AST order.
        numbered_label = self._next_anon_scope_name(label, node)

        # Ensure comprehension scope exists. On Python 3.12+ (PEP 709),
        # symtable no longer reports listcomp/setcomp/dictcomp as child scopes.
        # Create a synthetic scope with the iteration target names to preserve
        # variable isolation during analysis.
        parent_ns = self.get_node_of_current_namespace().get_name()
        inner_ns = f"{parent_ns}.{numbered_label}"
        if inner_ns not in self.scopes:
            target_names = set()
            for gen in gens:
                self._collect_target_names(gen.target, target_names)
            self.scopes[inner_ns] = Scope.from_names(numbered_label, target_names)

        with ExecuteInInnerScope(self, numbered_label) as scope_ctx:
            # Bind outermost targets to the iterator value in inner scope.
            for tgt in outermost_targets:
                self._bind_target(tgt, iter_node)
            for expr in outermost.ifs:
                self.visit(expr)

            for gen in moregens:
                targets = canonize_exprs(gen.target)
                values = canonize_exprs(gen.iter)
                self.analyze_binding(targets, values)
                # Add iterator protocol edges for inner generators.
                # NOTE: gen.iter is visited again (already visited inside
                # analyze_binding); harmless — same node, edges deduplicate.
                inner_iter_node = self.visit(gen.iter)
                self._add_iterator_protocol_edges(inner_iter_node, is_async=gen.is_async)
                for expr in gen.ifs:
                    self.visit(expr)

            self.visit(getattr(node, field1))  # e.g. node.elt
            if field2:
                self.visit(getattr(node, field2))
        return scope_ctx.inner_scope_node

    def visit_Call(self, node):
        self.logger.debug(f"Call {get_ast_node_name(node.func)}, {self.filename}:{node.lineno}")

        # visit args to detect uses
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            self.visit(kw.value)

        # Recognize ``setattr(target, name, value)`` against a
        # NAMESPACE_OBJECT target — symmetric counterpart to ``e.k = v``
        # for the dynamic form.  No-op for any non-matching call.  See
        # ``_maybe_register_setattr_call`` for the three name-resolution
        # levels (literal / scope-local / cross-module).
        self._maybe_register_setattr_call(node)

        # see if we can predict the result
        try:
            result_node = self.resolve_builtins(node)
        except UnresolvedSuperCallError:
            result_node = None

        if isinstance(result_node, Node):  # resolved result
            from_node = self.get_node_of_current_namespace()
            to_node = result_node
            self.logger.debug(f"Use from {from_node} to {to_node} (via resolved call to built-ins)")
            if self.add_uses_edge(from_node, to_node):
                self.logger.info(
                    f"New edge added for Use from {from_node} to {to_node} (via resolved call to built-ins)"
                )
            return result_node

        else:  # unresolved call — general case
            func_node = self.visit(node.func)

            # If the call target is a known class (e.g. MyClass()),
            # add a uses edge to MyClass.__init__().
            if func_node in self.class_base_ast_nodes:
                from_node = self.get_node_of_current_namespace()
                to_node = self.get_node(func_node.get_name(), "__init__", None, flavor=Flavor.METHOD)
                self.logger.debug(f"Use from {from_node} to {to_node} (call creates an instance)")
                if self.add_uses_edge(from_node, to_node):
                    self.logger.info(
                        f"New edge added for Use from {from_node} to {to_node} (call creates an instance)"
                    )
            return func_node

    def _visit_with(self, node, enter_method, exit_method):
        """Shared implementation for With and AsyncWith."""
        self.logger.debug(f"With (context manager), {self.filename}:{node.lineno}")

        def add_uses_enter_exit_of(graph_node):
            if isinstance(graph_node, Node):
                from_node = self.get_node_of_current_namespace()
                withed_obj_node = graph_node

                self.logger.debug(f"Use from {from_node} to With {withed_obj_node}")
                for methodname in (enter_method, exit_method):
                    to_node = self.get_node(withed_obj_node.get_name(), methodname, None, flavor=Flavor.METHOD)
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info(f"New edge added for Use from {from_node} to {to_node}")

        for withitem in node.items:
            expr = withitem.context_expr
            vars = withitem.optional_vars

            # NOTE: expr is visited again inside analyze_binding() when vars is not None;
            # the double visit is harmless (resolves to the same node, edges deduplicate).
            cm_node = self.visit(expr)
            add_uses_enter_exit_of(cm_node)

            if vars is not None:
                # bind optional_vars
                #
                # TODO: For now, we support only the following (most common) case:
                #  - only one binding target, vars is ast.Name
                #    (not ast.Tuple or something else)
                #  - the variable will point to the object that was with'd
                #    (i.e. we assume the object's __enter__() method
                #     to finish with "return self")
                #
                if isinstance(vars, ast.Name):
                    self.analyze_binding(canonize_exprs(vars), canonize_exprs(expr))
                else:
                    self.visit(vars)  # just capture any uses on the With line itself

        for stmt in node.body:
            self.visit(stmt)

    def visit_With(self, node):
        self._visit_with(node, "__enter__", "__exit__")

    def visit_AsyncWith(self, node):
        self._visit_with(node, "__aenter__", "__aexit__")

    def visit_Delete(self, node):
        """Track protocol method calls implied by `del` statements.

        `del obj.attr` invokes `obj.__delattr__("attr")`.
        `del obj[key]` invokes `obj.__delitem__(key)`.
        `del name` just unbinds a local — no protocol call.

        NOTE: `del name` also invalidates prior value bindings for `name`,
        so a subsequent `name.attr` would be a NameError at runtime.  We do
        not clear the binding here because the analyzer is flow-insensitive —
        the `del` might sit in a branch that doesn't always execute, or come
        after the use in source order but not in control flow.  Clearing would
        be wrong as often as right.  Revisit if flow sensitivity is ever added.
        """
        self.logger.debug(f"Delete, {self.filename}:{node.lineno}")
        from_node = self.get_node_of_current_namespace()
        for target in node.targets:
            if isinstance(target, ast.Attribute):
                obj_node = self.visit(target.value)
                if isinstance(obj_node, Node):
                    to_node = self.get_node(obj_node.get_name(), "__delattr__", None, flavor=Flavor.METHOD)
                    self.logger.debug(f"Use from {from_node} to {to_node} (del attr)")
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info(f"New edge added for Use from {from_node} to {to_node} (del attr)")
            elif isinstance(target, ast.Subscript):
                obj_node = self.visit(target.value)
                if isinstance(obj_node, Node):
                    to_node = self.get_node(obj_node.get_name(), "__delitem__", None, flavor=Flavor.METHOD)
                    self.logger.debug(f"Use from {from_node} to {to_node} (del item)")
                    if self.add_uses_edge(from_node, to_node):
                        self.logger.info(f"New edge added for Use from {from_node} to {to_node} (del item)")
                # Also visit the slice — it may contain names/calls.
                self.visit(target.slice)
            # ast.Name in ast.Del context: just unbinds, no protocol call.

    # --- Match statement (PEP 634, Python 3.10+) ---

    def visit_Match(self, node):
        self.logger.debug(f"Match, {self.filename}:{node.lineno}")
        self.visit(node.subject)
        for case in node.cases:
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            for stmt in case.body:
                self.visit(stmt)

    def visit_MatchValue(self, node):
        self.visit(node.value)

    def visit_MatchSingleton(self, node):
        pass

    def visit_MatchSequence(self, node):
        for pattern in node.patterns:
            self.visit(pattern)

    def visit_MatchMapping(self, node):
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self.set_value(node.rest, None)

    def visit_MatchClass(self, node):
        self.visit(node.cls)
        for pattern in node.patterns:
            self.visit(pattern)
        for pattern in node.kwd_patterns:
            self.visit(pattern)

    def visit_MatchStar(self, node):
        if node.name is not None:
            self.set_value(node.name, None)

    def visit_MatchAs(self, node):
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self.set_value(node.name, None)

    def visit_MatchOr(self, node):
        for pattern in node.patterns:
            self.visit(pattern)

    ###########################################################################
    # Analysis helpers

    def analyze_functiondef(self, ast_node):
        """Analyze a function definition.

        Visit decorators, and if this is a method definition, capture the name
        of the first positional argument to denote "self", like Python does.

        Return (self_name, flavor), where self_name the name representing self,
        or None if not applicable; and flavor is a Flavor, specifically one of
        FUNCTION, METHOD, STATICMETHOD or CLASSMETHOD."""

        if not isinstance(ast_node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            raise TypeError(f"Expected ast.FunctionDef; got {type(ast_node)}")

        # Visit decorators
        deco_names = []
        for deco in ast_node.decorator_list:
            deco_node = self.visit(deco)
            if isinstance(deco_node, Node):
                deco_names.append(deco_node.name)

        # Analyze flavor
        in_class_ns = self.context_stack[-1].startswith("ClassDef")
        if not in_class_ns:
            flavor = Flavor.FUNCTION
        else:
            if "staticmethod" in deco_names:
                flavor = Flavor.STATICMETHOD
            elif "classmethod" in deco_names:
                flavor = Flavor.CLASSMETHOD
            else:  # instance method
                flavor = Flavor.METHOD

        # Get the name representing "self", if applicable.
        #
        # - ignore static methods
        # - ignore functions defined inside methods (this new FunctionDef
        #   must be directly in a class namespace)
        #
        if flavor in (Flavor.METHOD, Flavor.CLASSMETHOD):
            # We can treat instance methods and class methods the same,
            # since Pyan is only interested in object types, not instances.
            all_args = ast_node.args  # args, vararg (*args), kwonlyargs, kwarg (**kwargs)
            posargs = all_args.args
            if len(posargs):
                self_name = posargs[0].arg
                return self_name, flavor

        return None, flavor

    def _bind_target(self, target, value, rhs_ast=None):
        """Bind an AST target node to a resolved value (a graph Node or None).

        Dispatches on target type: Name and Attribute perform scalar binding,
        Tuple/List recurse (all sub-targets get the same value), Starred
        unwraps to its inner target, and ast.arg handles function parameter
        defaults.

        *rhs_ast* — when known — is the AST node of the rhs expression,
        passed through so recognizers that need to inspect the rhs (e.g.
        the namespace-constructor and string-literal recognizers) can
        avoid having to re-derive it.  ``None`` for cases where the rhs
        isn't a single expression (e.g. cartesian fallback in
        ``analyze_binding``).
        """
        if isinstance(target, ast.Name):
            self.set_value(target.id, value)
            self._maybe_define_name_node(target)
            if rhs_ast is not None:
                self._maybe_register_name_literal(target, rhs_ast)
                self._maybe_register_namespace_object(target, rhs_ast)
        elif isinstance(target, ast.Attribute):
            try:
                if self.set_attribute(target, value):
                    self.logger.info(f"setattr {get_ast_node_name(target.value)}.{target.attr} to {value}")
                # Attribute-uses fallback for the Store case (#127): writing
                # ``obj.attr = value`` is just as much coupling to *obj* as
                # reading ``obj.attr`` is. Emit an edge to *obj* itself (or
                # its immediate parent if *obj* isn't defined), mirroring what
                # visit_Attribute does on the Load side. Fires regardless of
                # whether set_attribute returned True — even when *value*
                # isn't a tracked Node, the write itself is the coupling we
                # want to record.
                obj_node, _ = self.resolve_attribute(target)
                if isinstance(obj_node, Node):
                    ancestor = self._defined_self_or_parent(obj_node)
                    from_node = self.get_node_of_current_namespace()
                    if ancestor is not None and not self._within(from_node, ancestor):  # noqa: SIM102 -- guard + log-on-success: outer asks "should we add?", inner asks "did we add (vs. already present)?"
                        if self.add_uses_edge(from_node, ancestor):
                            self.logger.info(f"New edge added for Use from {from_node} to defined ancestor {ancestor} (attribute-write fallback)")
            except UnresolvedSuperCallError:
                pass
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._bind_target(elt, value)
        elif isinstance(target, ast.Starred):
            self._bind_target(target.value, value)
        elif isinstance(target, ast.arg):
            self.set_value(target.arg, value)

    def _maybe_define_name_node(self, name_target):
        """Create a defined ``Flavor.NAME`` Node for an ``ast.Name`` binding
        target if currently in a module or class scope.

        The graph's notion of "defined Node" tracks named entities reachable
        from outside their definition site. Module-level and class-level
        bindings are reachable (via ``from mymod import x`` or ``Class.x``)
        and so deserve a Node so that cross-module imports and attribute
        accesses can resolve to the actual binding rather than degrading to
        a wildcard or to #127's coarser module-level fallback.

        Function-locals (and synthetic anonymous scopes — comprehensions,
        lambdas — which symtable reports as ``"function"``) are not
        externally addressable; promoting every loop variable to a Node
        would only clutter the graph. They stay scope-only, set via
        ``set_value``.

        Method/function/class definitions are flavored separately by their
        own visitors (``visit_FunctionDef``, ``visit_ClassDef``) and don't
        come through this path.
        """
        if not self.scope_stack:
            return
        scope = self.scope_stack[-1]
        if scope.type not in ("module", "class"):
            return
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = self.get_node(ns, name_target.id, name_target, flavor=Flavor.NAME)
        if self.add_defines_edge(from_node, to_node):
            self.logger.info(f"Def from {from_node} to NAME {to_node}")
        self.associate_node(to_node, name_target, self.filename)

    def _maybe_register_name_literal(self, name_target, rhs_ast):
        """If a ``Name`` binding's rhs is a string ``Constant``, record the
        bound value in ``self.name_literals[ns][name]``.

        Used by the ``setattr`` recognizer to trace ``setattr(obj, k, v)``
        when ``k`` is a ``Name`` bound to a string literal (level 2:
        scope-local, level 3: cross-module via import resolution).

        Only literal strings are tracked — runtime-computed strings are
        beyond static analysis by design.
        """
        if not isinstance(rhs_ast, ast.Constant):
            return
        if not isinstance(rhs_ast.value, str):
            return
        if not self.scope_stack:
            return
        # Track at module/class scope only (mirrors `_maybe_define_name_node`):
        # function-local literal bindings aren't externally addressable, and
        # cross-module lookups require the binding to live in a module's namespace.
        if self.scope_stack[-1].type not in ("module", "class"):
            return
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        self.name_literals.setdefault(ns, {})[name_target.id] = rhs_ast.value

    def _maybe_register_namespace_object(self, name_target, rhs_ast):
        """Pattern: ``LHS = constructor(**kwargs)`` where *constructor*'s
        fully-qualified import origin is in ``self.namespace_constructors``.

        Recognizes:

        - ``config = env(thingy=baa)`` (canonical)
        - ``config: Env = env(thingy=baa)`` (annotated)
        - ``(config := env(thingy=baa))`` (walrus)
        - ``with env(thingy=baa) as config:`` (context manager — same path
          via `_visit_with` → `analyze_binding`)

        On a hit, the LHS Node (already created as ``Flavor.NAME`` by
        ``_maybe_define_name_node``) gets its flavor upgraded to
        ``Flavor.NAMESPACE_OBJECT``, and a scope is created for it whose
        ``defs`` dict is populated with the call's keyword arguments.
        Subsequent attribute reads (``config.thingy``) and writes
        (``config.flag = value``) then resolve through the existing
        ``get_attribute`` / ``set_attribute`` machinery.

        No-op when the rhs isn't a recognized constructor call, or when
        the binding is in a function scope (where no NAME Node exists).
        """
        if not isinstance(rhs_ast, ast.Call):
            return
        # Cheap gates first — most assignments aren't to module/class scope,
        # and FQN resolution is comparatively expensive (scope-chain lookup
        # and/or attribute resolution).
        if not self.scope_stack or self.scope_stack[-1].type not in ("module", "class"):
            return
        fqn = self._resolve_constructor_fqn(rhs_ast.func)
        if fqn is None or fqn not in self.namespace_constructors:
            return
        from_node = self.get_node_of_current_namespace()
        ns = from_node.get_name()
        # Locate the LHS Node (already created by `_maybe_define_name_node`)
        # and upgrade its flavor.  Direct assignment bypasses
        # `Flavor.specificity`'s upgrade gate, which is intentional —
        # we have additional information (the rhs is a known constructor)
        # that the gate doesn't know about.
        obj_node = self.get_node(ns, name_target.id, name_target)
        obj_node.flavor = Flavor.NAMESPACE_OBJECT
        obj_node.defined = True
        if self.add_defines_edge(from_node, obj_node):
            self.logger.info(f"Def from {from_node} to NAMESPACE_OBJECT {obj_node}")
        # Repoint the scope binding from the constructor (e.g. the env
        # IMPORTEDITEM) to the new NAMESPACE_OBJECT Node, so that later
        # ``config.attr`` lookups walk into ``mymod.config``'s scope rather
        # than into the constructor's namespace.  Plain NAME Nodes don't do
        # this — the binding is kept at the rhs value so e.g. ``pd =
        # pandas; pd.DataFrame`` still resolves into pandas' namespace.
        # NAMESPACE_OBJECT is the case where attribute resolution should
        # stay on the LHS itself.
        self.set_value(name_target.id, obj_node)
        # Ensure the scope exists at construction time, even when no
        # kwargs were passed.  Otherwise the staged form ``config = env();
        # config.a = baa`` breaks: the later attribute write goes through
        # ``set_attribute``, which writes into an *existing* scope but
        # doesn't create one (writes to non-NAMESPACE_OBJECT obj.attr
        # paths shouldn't materialize scopes either).
        obj_ns = obj_node.get_name()
        if obj_ns not in self.scopes:
            self.scopes[obj_ns] = Scope.from_names(obj_ns, [])
        for kw in rhs_ast.keywords:
            if kw.arg is None:  # **kwargs splat — not statically visible
                continue
            self._register_namespace_object_attr(obj_node, kw.arg, self.visit(kw.value))

    def _register_namespace_object_attr(self, obj_node, attr_name, attr_value):
        """Write ``attr_name → attr_value`` into *obj_node*'s scope.

        Used by both the constructor recognizer (for ``env(k=v)`` kwargs)
        and the ``setattr`` recognizer (for literal-named
        ``setattr(obj, "k", v)`` writes).  Idempotently creates the scope
        first — needed for the staged form ``config = env(); config.a = v``,
        where no kwargs at the construction site means no scope yet exists.

        Plain ``obj.attr = v`` writes go through ``set_attribute`` instead;
        that path skips when the scope is missing rather than creating it,
        because writes to attribute paths on non-NAMESPACE_OBJECT objects
        shouldn't materialize scopes for arbitrary objects.
        """
        obj_ns = obj_node.get_name()
        if obj_ns not in self.scopes:
            self.scopes[obj_ns] = Scope.from_names(obj_ns, [])
        self.scopes[obj_ns].defs[attr_name] = attr_value
        self.logger.info(f"Registered {attr_name} -> {attr_value} in NAMESPACE_OBJECT {obj_node}")

    def _resolve_constructor_fqn(self, func_ast):
        """Resolve a ``Call.func`` AST to its fully-qualified import origin
        as a dotted string, or ``None`` if not statically determinable.

        Three cases:

        - ``Name('env')`` where ``env`` is a user-bound name — looks up via
          ``get_value``, returns ``namespace + "." + name`` of the
          resolved Node.  Handles ``from unpythonic.env import env``
          (FQN ``"unpythonic.env.env"``) and ``from unpythonic import env``
          (FQN ``"unpythonic.env"``).
        - ``Name('setattr')`` where the name isn't user-bound but matches a
          Python builtin — returns ``"builtins.<name>"``.  Lets the
          ``setattr`` recognizer match the unaliased call.  Aliased
          builtins (``from builtins import setattr as sa``) take the first
          path automatically, since the import binds the name.
        - ``Attribute(Name('types'), 'SimpleNamespace')`` — first tries to
          look up the resolved attr Node (analyzed-source case).  Failing
          that, reconstructs the FQN from the dotted AST path
          (unanalyzed-module case: ``import types; types.SimpleNamespace``).
        """
        if isinstance(func_ast, ast.Name):
            node = self.get_value(func_ast.id)
            if isinstance(node, Node) and node.namespace is not None:
                return self._fqn_of_node(node)
            # Builtin fallback — only fires when the name isn't user-bound.
            if hasattr(_builtins_module, func_ast.id):
                return f"builtins.{func_ast.id}"
            return None
        if isinstance(func_ast, ast.Attribute):
            try:
                obj_node, attr_name = self.resolve_attribute(func_ast)
            except UnresolvedSuperCallError:
                return None
            if not isinstance(obj_node, Node) or obj_node.namespace is None:
                return None
            ns = obj_node.get_name()
            if ns in self.scopes and attr_name in self.scopes[ns].defs:
                resolved = self.scopes[ns].defs[attr_name]
                if isinstance(resolved, Node):
                    return self._fqn_of_node(resolved)
            # Unanalyzed-module case: reconstruct from the dotted path.
            return f"{ns}.{attr_name}"
        return None

    @staticmethod
    def _fqn_of_node(node):
        if not node.namespace:
            return node.name
        return f"{node.namespace}.{node.name}"

    def _resolve_setattr_name(self, name_arg_ast):
        """Resolve the second argument of ``setattr(obj, name, value)`` to a
        string, following three concentric levels of static knowability.

        - **Level 1 — literal string.** ``ast.Constant(value=str)``.  Use
          the value directly.
        - **Level 2 — name-bound literal.** ``ast.Name(id=k)`` where ``k``
          is bound to a string literal in a scope reachable from here
          (current scope chain).
        - **Level 3 — cross-module name-bound literal.** ``ast.Name(id=k)``
          where ``k`` resolves through an import to a string literal in
          another analyzed module.

        Returns the resolved string, or ``None`` if not statically
        knowable (loop variables, function-returned strings, dynamic
        construction — out of scope by design for a static analyzer).
        """
        if isinstance(name_arg_ast, ast.Constant) and isinstance(name_arg_ast.value, str):
            return name_arg_ast.value
        if isinstance(name_arg_ast, ast.Name):
            # Level 2: walk the current namespace chain (current ns and all
            # enclosing ones) looking for a tracked literal.  `name_literals`
            # is keyed by the fully-qualified namespace where the literal was
            # bound, so we have to traverse by namespace string rather than
            # by `Scope` object (whose `.name` is "" for the module).
            ns = self.get_node_of_current_namespace().get_name()
            while True:
                bucket = self.name_literals.get(ns, {})
                if name_arg_ast.id in bucket:
                    return bucket[name_arg_ast.id]
                if "." not in ns:
                    break
                ns = ns.rsplit(".", 1)[0]
            # Level 3: the Name might resolve to an imported binding.
            # `get_value` returns the resolved Node (after import resolution
            # within the visitor pass).  Look up its FQN's namespace in
            # `name_literals`.
            resolved = self.get_value(name_arg_ast.id)
            if isinstance(resolved, Node) and resolved.namespace is not None:
                bucket = self.name_literals.get(resolved.namespace, {})
                if resolved.name in bucket:
                    return bucket[resolved.name]
        return None

    def _maybe_register_setattr_call(self, call_ast):
        """Recognize ``setattr(target, name, value)`` calls on
        ``NAMESPACE_OBJECT``-flavored Nodes and register the implied
        binding in *target*'s scope, mirroring ``e.k = v``.

        Three structural preconditions:

        1. ``call_ast.func`` resolves to FQN ``"builtins.setattr"`` (handles
           aliased imports for free via scope-chain resolution).
        2. ``target`` (first positional arg) resolves to a Node with
           ``flavor=NAMESPACE_OBJECT`` (so a scope exists for it).
        3. ``name`` (second positional arg) resolves to a string via the
           three-level resolution in ``_resolve_setattr_name``.

        On match: ``self.scopes[target_node.get_name()].defs[name] = visit(value)``.
        On miss: no-op — same floor as the #127 module-level fallback.

        Symmetric ``delattr`` is intentionally not handled: pyan is
        flow-insensitive, and clearing bindings from a branch that doesn't
        always execute would be wrong as often as right (see
        ``visit_Delete`` for the analogous reasoning on ``del obj.attr``).
        """
        # Cheap structural gates first.  We're called from visit_Call on
        # every Call in the analyzed source, so the gate ordering matters
        # for analyzer cost: AST-shape checks are O(1), but FQN resolution
        # involves scope-chain lookup and/or attribute resolution.
        if len(call_ast.args) != 3 or call_ast.keywords:
            return
        if any(isinstance(a, ast.Starred) for a in call_ast.args):
            return
        target_arg, name_arg, value_arg = call_ast.args
        # Precondition: target is a `Name` (the recognizer doesn't handle
        # nested forms like ``setattr(get_obj(), ...)``).  Skip before
        # attempting any expensive resolution.
        if not isinstance(target_arg, ast.Name):
            return
        if not isinstance(call_ast.func, (ast.Name, ast.Attribute)):
            return
        # Precondition 1: func is builtins.setattr.
        fqn = self._resolve_constructor_fqn(call_ast.func)
        if fqn != "builtins.setattr":
            return
        # Precondition 2: target resolves to a NAMESPACE_OBJECT Node.
        target_node = self.get_value(target_arg.id)
        if not isinstance(target_node, Node) or target_node.flavor != Flavor.NAMESPACE_OBJECT:
            return
        # Precondition 3: name resolves to a string literal.
        attr_name = self._resolve_setattr_name(name_arg)
        if attr_name is None:
            return
        # Register the binding into target's scope.  set_attribute can't
        # be used here — its API takes an Attribute AST node, which we
        # don't have (the LHS *is* a Call, not an Attribute).
        self._register_namespace_object_attr(target_node, attr_name, self.visit(value_arg))

    @staticmethod
    def _collect_target_names(target, names):
        """Collect all Name identifiers from an assignment target AST node."""
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                CallGraphVisitor._collect_target_names(elt, names)
        elif isinstance(target, ast.Starred):
            CallGraphVisitor._collect_target_names(target.value, names)

    def analyze_binding(self, targets, values):
        """Generic handler for binding forms. Inputs must be canonize_exprs()d."""
        captured = [self.visit(value) for value in values]
        if len(targets) == len(captured):
            for tgt, val, val_ast in zip(targets, captured, values, strict=False):
                self._bind_target(tgt, val, rhs_ast=val_ast)
        else:
            # Check for positional starred unpacking on LHS (e.g. a, b, *c = x, y, z, w).
            star_idx = None
            for i, tgt in enumerate(targets):
                if isinstance(tgt, ast.Starred):
                    if star_idx is not None:
                        star_idx = None  # multiple stars → give up
                        break
                    star_idx = i

            if star_idx is not None and len(captured) >= len(targets) - 1:
                # Positional matching: bind non-starred targets to their
                # positional counterparts, starred target to the remainder.
                n_before = star_idx
                n_after = len(targets) - star_idx - 1
                for tgt, val in zip(targets[:n_before], captured[:n_before], strict=False):
                    self._bind_target(tgt, val)
                if n_after > 0:
                    for tgt, val in zip(targets[-n_after:], captured[-n_after:], strict=False):
                        self._bind_target(tgt, val)
                star_end = len(captured) - n_after if n_after else len(captured)
                remainder = captured[n_before:star_end]
                if remainder:
                    for val in remainder:
                        self._bind_target(targets[star_idx], val)
                else:
                    self._bind_target(targets[star_idx], None)
            else:
                # No star, multiple stars, or too few values.
                # Overapproximate: each target gets every RHS value.
                # _bind_target handles Tuple/List/Starred recursion.
                # Skip logging when captured is a single value (e.g. for-loop
                # or comprehension binding multiple targets to one iterable) —
                # no combinatorial blowup, and it's the common case.
                if len(captured) > 1:
                    lineno = getattr(targets[0], "lineno", "?") if targets else "?"
                    self.logger.info(f"Cartesian fallback: {len(targets)} targets, {len(captured)} values, {self.filename}:{lineno}")
                for tgt in targets:
                    for val in captured:
                        self._bind_target(tgt, val)

    def resolve_builtins(self, ast_node):
        """Resolve those calls to built-in functions whose return values
        can be determined in a simple manner.

        Currently, this supports:

          - str(obj), repr(obj) --> obj.__str__, obj.__repr__

          - super() (any arguments ignored), which works only in pass 2,
            because the MRO is determined between passes.

        May raise UnresolvedSuperCallError, if the call is to super(),
        but the result cannot be (currently) determined (usually because either
        pass 1, or some relevant source file is not in the analyzed set).

        Returns the Node the call resolves to, or None if not determined.
        """
        if not isinstance(ast_node, ast.Call):
            raise TypeError(f"Expected ast.Call; got {type(ast_node)}")

        func_ast_node = ast_node.func  # expr
        if isinstance(func_ast_node, ast.Name):
            funcname = func_ast_node.id
            if funcname == "super":
                class_node = self.get_current_class()
                self.logger.debug(f"Resolving super() of {class_node}")
                if class_node in self.mro:
                    # Our super() class is the next one in the MRO.
                    #
                    # Note that we consider only the **static type** of the
                    # class itself. The later elements of the MRO - important
                    # for resolving chained super() calls in a dynamic context,
                    # where the dynamic type of the calling object is different
                    # from the static type of the class where the super() call
                    # site is - are never used by Pyan for resolving super().
                    #
                    # This is a limitation of pure lexical scope based static
                    # code analysis.
                    #
                    if len(self.mro[class_node]) > 1:
                        result = self.mro[class_node][1]
                        self.logger.debug(f"super of {class_node} is {result}")
                        return result
                    else:
                        msg = f"super called for {class_node}, but no known bases"
                        self.logger.info(msg)
                        raise UnresolvedSuperCallError(msg)
                else:
                    msg = f"super called for {class_node}, but MRO not determined for it (maybe still in pass 1?)"
                    self.logger.info(msg)
                    raise UnresolvedSuperCallError(msg)

            if funcname in ("str", "repr") and len(ast_node.args) == 1:  # these take only one argument
                obj_astnode = ast_node.args[0]
                if isinstance(obj_astnode, (ast.Name, ast.Attribute)):
                    self.logger.debug(f"Resolving {funcname}() of {get_ast_node_name(obj_astnode)}")
                    attrname = f"__{funcname}__"
                    # build a temporary ast.Attribute AST node so that we can use get_attribute()
                    tmp_astnode = ast.Attribute(value=obj_astnode, attr=attrname, ctx=obj_astnode.ctx)
                    obj_node, attr_node = self.get_attribute(tmp_astnode)
                    self.logger.debug(
                        f"Resolve {funcname}() of {get_ast_node_name(obj_astnode)}: returning attr node {attr_node}"
                    )
                    return attr_node

            # add implementations for other built-in funcnames here if needed

    def resolve_attribute(self, ast_node):
        """Resolve an ast.Attribute.

        Nested attributes (a.b.c) are automatically handled by recursion.

        Return (obj,attrname), where obj is a Node (or None on lookup failure),
        and attrname is the attribute name.

        May pass through UnresolvedSuperCallError, if the attribute resolution
        failed specifically due to an unresolved super() call.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError(f"Expected ast.Attribute; got {type(ast_node)}")

        self.logger.debug(
            f"Resolve {get_ast_node_name(ast_node.value)}.{ast_node.attr} in context {type(ast_node.ctx)}"
        )

        # Resolve nested attributes
        #
        # In pseudocode, e.g. "a.b.c" is represented in the AST as:
        #    ast.Attribute(attr=c, value=ast.Attribute(attr=b, value=a))
        #
        if isinstance(ast_node.value, ast.Attribute):
            obj_node, attr_name = self.resolve_attribute(ast_node.value)

            if isinstance(obj_node, Node) and obj_node.namespace is not None:
                ns = obj_node.get_name()  # fully qualified namespace **of attr**
                if ns in self.scopes:  # imported modules not in the set of analyzed files are not seen by Pyan
                    sc = self.scopes[ns]
                    if attr_name in sc.defs:
                        self.logger.debug(f"Resolved to attr {ast_node.attr} of {sc.defs[attr_name]}")
                        return sc.defs[attr_name], ast_node.attr

            # It may happen that ast_node.value has no corresponding graph Node,
            # if this is a forward-reference, or a reference to a file
            # not in the analyzed set.
            #
            # In this case, return None for the object to let visit_Attribute()
            # add a wildcard reference to *.attr.
            #
            self.logger.debug(f"Unresolved, returning attr {ast_node.attr} of unknown")
            return None, ast_node.attr
        else:
            # detect str.join() and similar (attributes of constant literals,
            # such as "hello".upper())
            if isinstance(ast_node.value, ast.Constant):
                theliteral = ast_node.value
                t = type(theliteral.value)
                tn = t.__name__
                # Create a namespace-like Node with no associated AST node.
                # Constants are builtins, so they should live in the
                # top-level namespace (same level as module names).
                #
                # Since get_node() creates only one node per unique
                # (namespace,name) pair, the AST node would anyway be
                # frozen to the first constant of any matching type that
                # the analyzer encountered in the analyzed source code,
                # which is not useful.
                #
                # The CLASS flavor is the best match, as these constants
                # are object types.
                #
                obj_node = self.get_node("", tn, None, flavor=Flavor.CLASS)

            # attribute of a function call. Detect cases like super().dostuff()
            elif isinstance(ast_node.value, ast.Call):
                # Note that resolve_builtins() will signal an unresolved
                # super() by an exception, which we just pass through here.
                obj_node = self.resolve_builtins(ast_node.value)

                # can't resolve result of general function call
                if not isinstance(obj_node, Node):
                    self.logger.debug(f"Unresolved function call as obj, returning attr {ast_node.attr} of unknown")
                    return None, ast_node.attr
            else:
                # Get the Node object corresponding to node.value in the current ns.
                #
                # (Using the current ns here is correct; this case only gets
                #  triggered when there are no more levels of recursion,
                #  and the leftmost name always resides in the current ns.)
                obj_node = self.get_value(get_ast_node_name(ast_node.value))  # resolves "self" if needed

        self.logger.debug(f"Resolved to attr {ast_node.attr} of {obj_node}")
        return obj_node, ast_node.attr

    ###########################################################################
    # Scope analysis

    def analyze_scopes(self, code, filename):
        """Gather lexical scope information.

        PEP 695 handling (Python 3.12+, #123):

        Generic classes, functions, and type aliases (``class C[T]``,
        ``def f[T]``, ``type A[T] = ...``) get an implicit
        *type-parameter scope* in CPython's ``symtable``.  This scope is
        a real lexical closure — it sits between the enclosing scope and
        the entity scope, binding the type parameter names (``T``, etc.)
        so they are visible inside the entity body without polluting the
        enclosing namespace.

        In ``symtable``, the type-parameter scope has the **same name**
        as the entity it wraps, which would normally double the dotted
        namespace path (``mod.C.C.method`` instead of
        ``mod.C.method``).  The AST, however, has no corresponding
        intermediate node — the visitor walks ``ClassDef`` → body
        directly.

        To reconcile these two views we:

        1. Detect type-parameter scopes (``_is_type_params_scope``).
        2. Store them under a synthetic key
           ``<parent_ns>.<type_params>.<entity_name>`` so that the
           visitors can push them onto ``scope_stack`` for correct
           lexical lookup (see ``_type_params_scope``).
        3. Process their children under the **parent** namespace, so
           the actual entity lands at the correct dotted name.

        This preserves the closure semantics that Python itself uses —
        essentially a let-over-lambda: ``T`` is bound once at class
        definition time, and all methods close over that binding.
        Even if the class body shadows ``T`` with an assignment, methods
        still see the type-parameter ``T``, because Python's class scope
        is not a closure scope (methods cannot see bare names from the
        class body — they must use ``self.x`` or ``type(self).x``).
        """

        # Below, ns is the fully qualified ("dotted") name of sc.
        #
        # Technically, the module scope is anonymous, but we treat it as if
        # it was in a namespace named after the module, to support analysis
        # of several files as a set (keeping their module-level definitions
        # in different scopes, as we should).
        #
        scopes = {}

        def process(parent_ns, table):
            sc = Scope(table)
            ns = f"{parent_ns}.{sc.name}" if len(sc.name) else parent_ns
            scopes[ns] = sc
            anon_counts = {}  # number duplicate anonymous scope children
            for t in table.get_children():
                child_name = t.get_name()
                if child_name in ANON_SCOPE_NAMES:
                    idx = anon_counts.get(child_name, 0)
                    anon_counts[child_name] = idx + 1
                    child_sc = Scope(t)
                    numbered_name = f"{child_name}.{idx}"
                    child_sc.name = numbered_name
                    child_ns = f"{ns}.{numbered_name}"
                    scopes[child_ns] = child_sc
                    for sub_t in t.get_children():
                        process(child_ns, sub_t)
                elif _is_type_params_scope(t):
                    # PEP 695 (#123): store the type-parameter scope
                    # under a synthetic key and process its children
                    # under the current namespace (see docstring above).
                    tp_scope = Scope(t)
                    tp_key = f"{ns}.<type_params>.{child_name}"
                    scopes[tp_key] = tp_scope
                    for sub_t in t.get_children():
                        process(ns, sub_t)
                else:
                    process(ns, t)

        process(self.module_name, symtable.symtable(code, filename, compile_type="exec"))

        # add to existing scopes (while not overwriting any existing definitions with None)
        for ns in scopes:
            if ns not in self.scopes:  # add new scope info
                self.scopes[ns] = scopes[ns]
            else:  # update existing scope info
                sc = scopes[ns]
                oldsc = self.scopes[ns]
                for name in sc.defs:
                    if name not in oldsc.defs:
                        oldsc.defs[name] = sc.defs[name]

        self.logger.debug(f"Scopes now: {self.scopes}")

    @contextmanager
    def _type_params_scope(self, entity_name):
        """Context manager: push PEP 695 type-parameter closure scope.

        Pushes the type-parameter scope (if one exists for *entity_name*)
        onto ``scope_stack`` on entry, pops it on exit.  Does **not**
        touch ``name_stack`` — the type-parameter scope is a closure
        that doesn't contribute to the dotted namespace path.

        On Python < 3.12, or for non-generic entities, this is a no-op.
        """
        ns = self.get_node_of_current_namespace().get_name()
        key = f"{ns}.<type_params>.{entity_name}"
        pushed = key in self.scopes
        if pushed:
            self.scope_stack.append(self.scopes[key])
        try:
            yield
        finally:
            if pushed:
                self.scope_stack.pop()

    @contextmanager
    def _module_scope(self, module_name):
        """Context manager: enter/leave a module scope."""
        self.name_stack.append(module_name)
        self.scope_stack.append(self.scopes[module_name])
        self.context_stack.append(f"Module {module_name}")
        try:
            yield
        finally:
            self.context_stack.pop()
            self.scope_stack.pop()
            self.name_stack.pop()

    @contextmanager
    def _class_scope(self, node, class_node):
        """Context manager: enter/leave a class scope.

        Pushes ``class_stack``, ``name_stack``, ``scope_stack``, and
        ``context_stack``.  Yields the fully qualified inner namespace
        name (e.g. ``mod.MyClass``).
        """
        self.class_stack.append(class_node)
        self.name_stack.append(node.name)
        inner_ns = self.get_node_of_current_namespace().get_name()
        self.scope_stack.append(self.scopes[inner_ns])
        self.context_stack.append(f"ClassDef {node.name}")
        try:
            yield inner_ns
        finally:
            self.context_stack.pop()
            self.scope_stack.pop()
            self.name_stack.pop()
            self.class_stack.pop()

    @contextmanager
    def _function_scope(self, node):
        """Context manager: enter/leave a function scope.

        Pushes ``name_stack``, ``scope_stack``, and ``context_stack``.
        Yields the fully qualified inner namespace name
        (e.g. ``mod.MyClass.my_method``).
        """
        self.name_stack.append(node.name)
        inner_ns = self.get_node_of_current_namespace().get_name()
        self.scope_stack.append(self.scopes[inner_ns])
        self.context_stack.append(f"FunctionDef {node.name}")
        try:
            yield inner_ns
        finally:
            self.context_stack.pop()
            self.scope_stack.pop()
            self.name_stack.pop()

    def get_current_class(self):
        """Return the node representing the current class, or None if not inside a class definition."""
        return self.class_stack[-1] if len(self.class_stack) else None

    def get_node_of_current_namespace(self):
        """Return the unique node representing the current namespace,
        based on self.name_stack.

        For a Node n representing a namespace:
          - n.namespace = fully qualified name of the parent namespace
                          (empty string if at top level)
          - n.name      = name of this namespace
          - no associated AST node.
        """
        assert len(self.name_stack)  # name_stack should never be empty (always at least module name)

        namespace = ".".join(self.name_stack[0:-1])
        name = self.name_stack[-1]
        return self.get_node(namespace, name, None, flavor=Flavor.SCOPE)

    ###########################################################################
    # Value getter and setter

    def get_value(self, name):
        """Get the value of name in the current scope. Return the Node, or None
        if name is not set to a value."""

        # get the innermost scope that has name **and where name has a value**
        def find_scope(name):
            for sc in reversed(self.scope_stack):
                if name in sc.defs and sc.defs[name] is not None:
                    return sc

        sc = find_scope(name)
        if sc is not None:
            value = sc.defs[name]
            if isinstance(value, Node):
                self.logger.info(f"Get {name} in {self.scope_stack[-1]}, found in {sc}, value {value}")
                return value
            else:
                # TODO: should always be a Node or None
                self.logger.debug(
                    f"Get {name} in {self.scope_stack[-1]}, found in {sc}: value {value} is not a Node"
                )
        else:
            self.logger.debug(f"Get {name} in {self.scope_stack[-1]}: no Node value (or name not in scope)")

    def set_value(self, name, value):
        """Set the value of name in the current scope. Value must be a Node."""

        # get the innermost scope that has name (should be the current scope unless name is a global)
        def find_scope(name):
            for sc in reversed(self.scope_stack):
                if name in sc.defs:
                    return sc

        sc = find_scope(name)
        if sc is not None:
            if isinstance(value, Node):
                sc.defs[name] = value
                self.logger.info(f"Set {name} in {sc} to {value}")
            else:
                # TODO: should always be a Node or None
                self.logger.debug(f"Set {name} in {sc}: value {value} is not a Node")
        else:
            self.logger.debug(f"Set: name {name} not in scope")

    ###########################################################################
    # Attribute getter and setter

    def get_attribute(self, ast_node):
        """Get value of an ast.Attribute.

        Supports inherited attributes. If the obj's own namespace has no match
        for attr, the ancestors of obj are also tried, following the MRO based
        on the static type of the object, until one of them matches or until
        all ancestors are exhausted.

        Return pair of Node objects (obj,attr), where each item can be None
        on lookup failure. (Object not known, or no Node value assigned
        to its attr.)

        May pass through UnresolvedSuperCallError.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError(f"Expected ast.Attribute; got {type(ast_node)}")
        if not isinstance(ast_node.ctx, ast.Load):
            raise ValueError(f"Expected a load context, got {type(ast_node.ctx)}")

        obj_node, attr_name = self.resolve_attribute(ast_node)

        if isinstance(obj_node, Node) and obj_node.namespace is not None:
            ns = obj_node.get_name()  # fully qualified namespace **of attr**

            # detect str.join() and similar (attributes of constant literals)
            #
            # Any attribute is considered valid for these special types,
            # but only in a load context. (set_attribute() does not have this
            # special handling, by design.)
            #
            if ns in ("Num", "Str"):  # TODO: other types?
                return obj_node, self.get_node(ns, attr_name, None, flavor=Flavor.ATTRIBUTE)

            # look up attr_name in the given namespace, return Node or None
            def lookup(ns):
                if ns in self.scopes:
                    sc = self.scopes[ns]
                    if attr_name in sc.defs:
                        return sc.defs[attr_name]

            # first try directly in object's ns (this works already in pass 1)
            value_node = lookup(ns)
            if value_node is not None:
                return obj_node, value_node

            # next try ns of each ancestor (this works only in pass 2,
            # after self.mro has been populated)
            #
            if obj_node in self.mro:
                for base_node in tail(self.mro[obj_node]):  # the first element is always obj itself
                    ns = base_node.get_name()
                    value_node = lookup(ns)
                    if value_node is not None:
                        break
                else:
                    return None, None  # not found
                return base_node, value_node  # as obj, return the base class in which attr was found

        return obj_node, None  # here obj_node is either None or unknown (namespace None)

    def set_attribute(self, ast_node, new_value):
        """Assign the Node provided as new_value into the attribute described
        by the AST node ast_node. Return True if assignment was done,
        False otherwise.

        May pass through UnresolvedSuperCallError.
        """

        if not isinstance(ast_node, ast.Attribute):
            raise TypeError(f"Expected ast.Attribute; got {type(ast_node)}")
        if not isinstance(ast_node.ctx, ast.Store):
            raise ValueError(f"Expected a store context, got {type(ast_node.ctx)}")

        if not isinstance(new_value, Node):
            return False

        obj_node, attr_name = self.resolve_attribute(ast_node)

        if isinstance(obj_node, Node) and obj_node.namespace is not None:
            ns = obj_node.get_name()  # fully qualified namespace **of attr**
            if ns in self.scopes:
                sc = self.scopes[ns]
                sc.defs[attr_name] = new_value
                return True
        return False

    ###########################################################################
    # Graph creation

    def get_node(self, namespace, name, ast_node=None, flavor=Flavor.UNSPECIFIED):
        """Return the unique node matching the namespace and name.
        Create a new node if one doesn't already exist.

        To associate the node with a syntax object in the analyzed source code,
        an AST node can be passed in. This only takes effect if a new Node
        is created.

        To associate an AST node to an existing graph node,
        see associate_node().

        Flavor describes the kind of object the node represents.
        See the node.Flavor enum for currently supported values.

        For existing nodes, flavor overwrites, if the given flavor is
        (strictly) more specific than the node's existing one.
        See node.Flavor.specificity().

        !!!
        In CallGraphVisitor, always use get_node() to create nodes, because it
        also sets some important auxiliary information. Do not call the Node
        constructor directly.
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
        # TODO: this is tentative. Add in filename only when sure?
        # (E.g. in visit_ClassDef(), visit_FunctionDef())
        #
        # If the namespace is one of the modules being analyzed,
        # the Node belongs to the corresponding file; otherwise assume current file.
        filename = self.module_to_filename.get(namespace, self.filename)

        n = Node(namespace, name, ast_node, filename, flavor)

        # Add to the list of nodes that have this short name.
        if name in self.nodes:
            self.nodes[name].append(n)
        else:
            self.nodes[name] = [n]

        return n

    def get_parent_node(self, graph_node):
        """Get the parent node of the given Node. (Used in postprocessing.)"""
        if "." in graph_node.namespace:
            ns, name = graph_node.namespace.rsplit(".", 1)
        else:
            ns, name = "", graph_node.namespace
        return self.get_node(ns, name, None)

    @staticmethod
    def _within(inner, outer):
        """Return ``True`` if *inner* lies inside (or equals) *outer*'s
        namespace subtree, judged by dotted full names.

        Used by the attribute-uses fallback (#127) to suppress trivial
        within-scope self-references: a function reading module-level state
        in its own module, or a method reading a class attribute on its own
        class, is just normal scoping — emitting a fallback edge only adds
        noise.
        """
        outer_full = outer.get_name()
        inner_full = inner.get_name()
        return inner_full == outer_full or inner_full.startswith(outer_full + ".")

    def _defined_self_or_parent(self, graph_node):
        """Return *graph_node* itself if it is defined, or its immediate
        parent (by dotted name) if that parent is defined.  Returns ``None``
        otherwise.

        Used by the attribute-uses fallback (#127): when an attribute access
        like ``obj.attr`` can't be resolved to a defined Node, attribute the
        coupling to the immediate container of *obj* — typically the module
        that exports it.

        Stepping up by one level only — never further — is intentional.  A name
        imported from an unanalyzed package (e.g. ``gui_config`` imported from
        ``raven.common.gui.fontsetup``) would otherwise walk through every
        undefined intermediate and pin the edge on whatever top-level package
        happened to be analyzed, drowning the real signal in noise.  Chained
        accesses ``a.b.c`` are handled by ``visit_Attribute`` falling through
        to its inner ``Attribute``, which performs its own one-level lookup
        on a fresh ``obj_node``.

        Does not create new Nodes (unlike :meth:`get_parent_node`).
        """
        if graph_node.defined:
            return graph_node
        full = graph_node.get_name()
        if "." not in full:
            return None
        parent_full = full.rsplit(".", 1)[0]
        return next(
            (n for lst in self.nodes.values() for n in lst
             if n.defined and n.get_name() == parent_full),
            None,
        )

    def associate_node(self, graph_node, ast_node, filename=None):
        """Change the AST node (and optionally filename) mapping of a graph node.

        This is useful for generating annotated output with source filename
        and line number information.

        Sometimes a function in the analyzed code is first seen in a FromImport
        before its definition has been analyzed. The namespace can be deduced
        correctly already at that point, but the source line number information
        has to wait until the actual definition is found (because the line
        number is contained in the AST node). However, a graph Node must be
        created immediately when the function is first encountered, in order
        to have a Node that can act as a "uses" target (namespaced correctly,
        to avoid a wildcard and the over-reaching expand_unknowns() in cases
        where they are not needed).

        This method re-associates the given graph Node with a different
        AST node, which allows updating the context when the definition
        of a function or class is encountered."""
        graph_node.ast_node = ast_node
        if filename is not None:
            graph_node.filename = filename

    def add_defines_edge(self, from_node, to_node):
        """Add a defines edge in the graph between two nodes.
        N.B. This will mark both nodes as defined."""
        status = False
        if from_node not in self.defines_edges:
            self.defines_edges[from_node] = set()
            status = True
        from_node.defined = True
        if to_node is None or to_node in self.defines_edges[from_node]:
            return status
        self.defines_edges[from_node].add(to_node)
        to_node.defined = True
        return True

    def add_uses_edge(self, from_node, to_node):
        """Add a uses edge in the graph between two nodes."""

        # Record decorator-argument targets (#125) regardless of whether the
        # underlying edge is new: if another function in the same module has
        # already added ``module → foo``, the edge is deduplicated but we
        # still need to see ``foo`` here to attribute it to the decorated fn.
        for rec in self._decorator_use_recorders:
            rec.add(to_node)

        if from_node not in self.uses_edges:
            self.uses_edges[from_node] = set()
        if to_node in self.uses_edges[from_node]:
            return False
        self.uses_edges[from_node].add(to_node)

        # for pass 2: remove uses edge to any matching wildcard target node
        # if the given to_node has a known namespace.
        #
        # Prevents the spurious reference to MyClass.f in this example:
        #
        # class MyClass:
        #     def __init__(self):
        #         pass
        #     def f():
        #         pass
        #
        # def main():
        #     f()
        #
        # def f():
        #     pass
        #
        # (caused by reference to *.f in pass 1, combined with
        #  expand_unknowns() in postprocessing.)
        #
        # TODO: this can still get confused. The wildcard is removed if the
        # name of *any* resolved uses edge matches, whereas the wildcard
        # may represent several uses, to different objects.
        #
        if to_node.namespace is not None:
            self.remove_wild(from_node, to_node, to_node.name)

        return True

    def remove_uses_edge(self, from_node, to_node):
        """Remove a uses edge from the graph. (Used in postprocessing.)"""

        if from_node in self.uses_edges:
            u = self.uses_edges[from_node]
            if to_node in u:
                u.remove(to_node)

    def remove_wild(self, from_node, to_node, name):
        """Remove uses edge from from_node to wildcard *.name.

        This needs both to_node and name because in case of a bound name
        (e.g. attribute lookup) the name field of the *target value* does not
        necessarily match the formal name in the wildcard.

        Used for cleaning up forward-references once resolved.
        This prevents spurious edges due to expand_unknowns()."""

        if name is None:  # relative imports may create nodes with name=None.
            return

        if from_node not in self.uses_edges:  # no uses edges to remove
            return

        # Keep wildcard if the target is actually an unresolved argument
        # (see visit_FunctionDef())
        if to_node.get_name().find("^^^argument^^^") != -1:
            return

        # Here we may prefer to err in one of two ways:
        #
        #  a) A node seemingly referring to itself is actually referring
        #     to somewhere else that was not fully resolved, so don't remove
        #     the wildcard.
        #
        #     Example:
        #
        #         import sympy as sy
        #         def simplify(expr):
        #             sy.simplify(expr)
        #
        #     If the source file of sy.simplify is not included in the set of
        #     analyzed files, this will generate a reference to *.simplify,
        #     which is formally satisfied by this function itself.
        #
        #     (Actually, after commit e3c32b782a89b9eb225ef36d8557ebf172ff4ba5,
        #      this example is bad; sy.simplify will be recognized as an
        #      unknown attr of a known object, so no wildcard is generated.)
        #
        #  b) A node seemingly referring to itself is actually referring
        #     to itself (it can be e.g. a recursive function). Remove the wildcard.
        #
        #     Bad example:
        #
        #         def f(count):
        #             if count > 0:
        #                 return 1 + f(count-1)
        #             return 0
        #
        #     (This example is bad, because visit_FunctionDef() will pick up
        #      the f in the top-level namespace, so no reference to *.f
        #      should be generated in this particular case.)
        #
        # We choose a).
        #
        # TODO: do we need to change our opinion now that also recursive calls are visualized?
        #
        if to_node == from_node:
            return

        matching_wilds = [n for n in self.uses_edges[from_node] if n.namespace is None and n.name == name]
        assert len(matching_wilds) < 2  # the set can have only one wild of matching name
        if len(matching_wilds):
            wild_node = matching_wilds[0]
            self.logger.info(f"Use from {from_node} to {to_node} resolves {wild_node}; removing wildcard")
            self.remove_uses_edge(from_node, wild_node)
