#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities for analyzer."""

import ast
from glob import glob
import os
import os.path

from .node import Flavor


def expand_sources(patterns):
    """Expand source file patterns, treating directories as ``dir/**/*.py``.

    Accepts a list of file paths, glob patterns, or directory paths.
    Directories are expanded to ``dir/**/*.py`` recursively.
    """
    result = []
    for pat in patterns:
        if os.path.isdir(pat):
            pat = os.path.join(pat, "**", "*.py")
        result.extend(glob(pat, recursive=True))
    return result


def infer_root(filenames):
    """Infer the project root from a list of ``.py`` file paths.

    Finds the deepest common ancestor directory of all *filenames*,
    then walks up while the directory contains ``__init__.py`` (those
    are packages, not the root).  The first directory without
    ``__init__.py`` is returned as the root.

    Falls back to cwd when *filenames* is empty.
    """
    abspaths = [os.path.abspath(f) for f in filenames]
    if not abspaths:
        return os.getcwd()
    common = os.path.dirname(abspaths[0]) if len(abspaths) == 1 else os.path.commonpath(abspaths)
    # If commonpath landed on a file (single file, or all files share a name prefix),
    # step up to the containing directory.
    if not os.path.isdir(common):
        common = os.path.dirname(common)
    # Walk up while directory is a package (contains __init__.py).
    while os.path.isfile(os.path.join(common, "__init__.py")):
        parent = os.path.dirname(common)
        if parent == common:  # filesystem root
            break
        common = parent
    return common


def head(lst):
    if len(lst):
        return lst[0]


def tail(lst):
    if len(lst) > 1:
        return lst[1:]
    else:
        return []


def get_module_name(filename, root: str = None):
    """Determine the full module name of a source file.

    When *root* is given, the module name is the dotted path from *root*
    to *filename* (with ``.py`` stripped).  This is the reliable mode —
    use :func:`infer_root` to obtain a suitable *root* from a set of
    source files.

    .. deprecated:: 2.2.2
        The *root* = ``None`` mode is **unreliable** and should not be
        used.  It walks up the directory tree using ``__init__.py`` as
        the only package marker, which **silently produces wrong names**
        for namespace packages (PEP 420 — directories without
        ``__init__.py``).  Always pass an explicit *root*.
    """
    if root is not None:
        # Normalise both to absolute so the comparison is reliable
        # regardless of whether the caller passed relative or absolute paths.
        filename = os.path.abspath(filename)
        root = os.path.abspath(root)

    if os.path.basename(filename) == "__init__.py":
        # init file means module name is directory name
        module_path = os.path.dirname(filename)
    else:
        # otherwise it is the filename without extension
        module_path = filename.removesuffix(".py")

    # find the module root - walk up the tree and check if it contains .py files - if yes. it is the new root
    directories = [(module_path, True)]
    if root is None:
        while directories[0][0] != os.path.dirname(directories[0][0]):
            potential_root = os.path.dirname(directories[0][0])
            # Check if potential_root is valid and exists before listing
            if not potential_root or not os.path.exists(potential_root) or not os.path.isdir(potential_root):
                break
            is_root = any(f == "__init__.py" for f in os.listdir(potential_root))
            directories.insert(0, (potential_root, is_root))

        # keep directories where itself or parent is root
        while not directories[0][1]:
            directories.pop(0)

    else:  # root is already known - just walk up until it is matched
        while directories[0][0] != root:
            potential_root = os.path.dirname(directories[0][0])
            if potential_root == directories[0][0]:
                # Hit filesystem root without matching — root is not an
                # ancestor of filename.  Fall back to what we have.
                break
            directories.insert(0, (potential_root, True))
        # The root directory itself is not part of the module name — it's
        # the directory from which module paths are resolved (like sys.path).
        if directories[0][0] == root:
            directories.pop(0)

    mod_name = ".".join([os.path.basename(f[0]) for f in directories])
    return mod_name


def format_alias(x):
    """Return human-readable description of an ast.alias (used in Import and ImportFrom nodes)."""
    if not isinstance(x, ast.alias):
        raise TypeError(f"Can only format an ast.alias; got {type(x)}")

    if x.asname is not None:
        return f"{x.name} as {x.asname}"
    else:
        return f"{x.name}"


def get_ast_node_name(x):
    """Return human-readable name of ast.Attribute or ast.Name. Pass through anything else."""
    if isinstance(x, ast.Attribute):
        # x.value might also be an ast.Attribute (think "x.y.z")
        return f"{get_ast_node_name(x.value)}.{x.attr}"
    elif isinstance(x, ast.Name):
        return x.id
    else:
        return x


# Helper for handling binding forms.
def canonize_exprs(exprs):
    """Normalize ast.Tuple/ast.List to Python lists for uniform processing."""

    def process(expr):
        if isinstance(expr, (ast.Tuple, ast.List)):
            return expr.elts  # .elts is a Python tuple
        else:
            return [expr]

    if isinstance(exprs, (tuple, list)):
        return [process(expr) for expr in exprs]
    else:
        return process(exprs)


def resolve_method_resolution_order(class_base_nodes, logger):
    """Compute the method resolution order (MRO) for each of the analyzed classes.

    class_base_nodes: dict cls: [base1, base2, ..., baseN]
                      where dict and basej are all Node objects.
    """

    # https://en.wikipedia.org/wiki/C3_linearization#Description

    class LinearizationImpossible(Exception):
        pass

    from functools import reduce
    from operator import add

    def C3_find_good_head(heads, tails):  # find an element of heads which is not in any of the tails
        flat_tails = reduce(add, tails, [])  # flatten the outer level
        for hd in heads:
            if hd not in flat_tails:
                break
        else:  # no break only if there are cyclic dependencies.
            raise LinearizationImpossible(
                f"MRO linearization impossible; cyclic dependency detected. heads: {heads}, tails: {tails}"
            )
        return hd

    def remove_all(elt, lst):  # remove all occurrences of elt from lst, return a copy
        return [x for x in lst if x != elt]

    def remove_all_in(elt, lists):  # remove elt from all lists, return a copy
        return [remove_all(elt, lst) for lst in lists]

    def C3_merge(lists):
        out = []
        while True:
            logger.debug(f"MRO: C3 merge: out: {out}, lists: {lists}")
            heads = [head(lst) for lst in lists if head(lst) is not None]
            if not len(heads):
                break
            tails = [tail(lst) for lst in lists]
            logger.debug(f"MRO: C3 merge: heads: {heads}, tails: {tails}")
            hd = C3_find_good_head(heads, tails)
            logger.debug(f"MRO: C3 merge: chose head {hd}")
            out.append(hd)
            lists = remove_all_in(hd, lists)
        return out

    mro = {}  # result
    try:
        memo = {}  # caching/memoization

        def C3_linearize(node):
            logger.debug(f"MRO: C3 linearizing {node}")
            seen.add(node)
            if node not in memo:
                #  unknown class                     or no ancestors
                if node not in class_base_nodes or not len(class_base_nodes[node]):
                    memo[node] = [node]
                else:  # known and has ancestors
                    lists = []
                    # linearization of parents...
                    for baseclass_node in class_base_nodes[node]:
                        if baseclass_node not in seen:
                            lists.append(C3_linearize(baseclass_node))
                    # ...and the parents themselves (in the order they appear in the ClassDef)
                    logger.debug(f"MRO: parents of {node}: {class_base_nodes[node]}")
                    lists.append(class_base_nodes[node])
                    logger.debug(f"MRO: C3 merging {lists}")
                    memo[node] = [node] + C3_merge(lists)
            logger.debug(f"MRO: C3 linearized {node}, result {memo[node]}")
            return memo[node]

        for node in class_base_nodes:
            logger.debug(f"MRO: analyzing class {node}")
            seen = set()  # break cycles (separately for each class we start from)
            mro[node] = C3_linearize(node)
    except LinearizationImpossible as e:
        logger.error(e)

        # generic fallback: depth-first search of lists of ancestors
        #
        # (so that we can try to draw *something* if the code to be
        #  analyzed is so badly formed that the MRO algorithm fails)

        memo = {}  # caching/memoization

        def lookup_bases_recursive(node):
            seen.add(node)
            if node not in memo:
                out = [node]  # first look up in obj itself...
                if node in class_base_nodes:  # known class?
                    for baseclass_node in class_base_nodes[node]:  # ...then in its bases
                        if baseclass_node not in seen:
                            out.append(baseclass_node)
                            out.extend(lookup_bases_recursive(baseclass_node))
                memo[node] = out
            return memo[node]

        mro = {}
        for node in class_base_nodes:
            logger.debug(f"MRO: generic fallback: analyzing class {node}")
            seen = set()  # break cycles (separately for each class we start from)
            mro[node] = lookup_bases_recursive(node)

    return mro


class UnresolvedSuperCallError(Exception):
    """For specifically signaling an unresolved super()."""

    pass


class Scope:
    """Adaptor that makes scopes look somewhat like those from the Python 2
    compiler module, as far as Pyan's CallGraphVisitor is concerned."""

    def __init__(self, table):
        """table: SymTable instance from symtable.symtable()"""
        name = table.get_name()
        if name == "top":
            name = ""  # Pyan defines the top level as anonymous
        self.name = name
        self.type = table.get_type()  # useful for __repr__()
        self.defs = dict.fromkeys(table.get_identifiers())  # name:assigned_value
        # Pure locals: assigned in this scope, not free/global/imported.
        # Used by visit_Name to skip UNKNOWN node creation for unresolved locals.
        self.locals = {sym.get_name() for sym in table.get_symbols()
                       if sym.is_assigned() and not sym.is_imported()
                       and not sym.is_global() and not sym.is_free()}

    @classmethod
    def from_names(cls, name, identifiers):
        """Create a synthetic scope for inlined comprehensions (Python 3.12+, PEP 709).

        On 3.12+, symtable no longer reports comprehension scopes as children.
        This creates a minimal scope containing only the specified identifiers,
        preserving variable isolation during analysis.
        """
        sc = cls.__new__(cls)
        sc.name = name
        sc.type = "function"
        sc.defs = dict.fromkeys(identifiers)
        sc.locals = set(identifiers)  # comprehension variables are all locals
        return sc

    def __repr__(self):
        return f"<Scope: {self.type} {self.name}>"


# A context manager, sort of a friend of CallGraphVisitor (depends on implementation details)
class ExecuteInInnerScope:
    """Execute a code block with the scope stack augmented with an inner scope.

    Used to analyze lambda, listcomp et al. The scope must still be present in
    analyzer.scopes.

    !!!
    Will add a defines edge from the current namespace to the inner scope,
    marking both nodes as defined.
    !!!

    Use as a context manager::

        with ExecuteInInnerScope(analyzer, "lambda") as scope_ctx:
            # scope_ctx.inner_ns is the fully qualified inner namespace name (str),
            # available immediately on entry.
            ...
        # scope_ctx.inner_scope_node is the Node for the inner scope,
        # available after exit.
    """

    def __init__(self, analyzer, scopename):
        """analyzer: CallGraphVisitor instance
        scopename: name of the inner scope"""
        self.analyzer = analyzer
        self.scopename = scopename

    def __enter__(self):
        # The inner scopes pollute the graph too much; we will need to collapse
        # them in postprocessing. However, we must use them during analysis to
        # follow the Python 3 scoping rules correctly.

        analyzer = self.analyzer
        scopename = self.scopename

        analyzer.name_stack.append(scopename)
        inner_ns = analyzer.get_node_of_current_namespace().get_name()
        if inner_ns not in analyzer.scopes:
            analyzer.name_stack.pop()
            raise ValueError(f"Unknown scope '{inner_ns}'")
        analyzer.scope_stack.append(analyzer.scopes[inner_ns])
        analyzer.context_stack.append(scopename)

        self.inner_ns = inner_ns
        return self

    def __exit__(self, errtype, errvalue, traceback):
        # TODO: do we need some error handling here?
        analyzer = self.analyzer
        scopename = self.scopename

        analyzer.context_stack.pop()
        analyzer.scope_stack.pop()
        analyzer.name_stack.pop()

        # Add a defines edge, which will mark the inner scope as defined,
        # allowing any uses to other objects from inside the lambda/listcomp/etc.
        # body to be visualized.
        #
        # All inner scopes of the same scopename (lambda, listcomp, ...) in the
        # current ns will be grouped into a single node, as they have no name.
        # We create a namespace-like node that has no associated AST node,
        # as it does not represent any unique AST node.
        from_node = analyzer.get_node_of_current_namespace()
        ns = from_node.get_name()
        to_node = analyzer.get_node(ns, scopename, None, flavor=Flavor.NAMESPACE)
        if analyzer.add_defines_edge(from_node, to_node):
            analyzer.logger.info(f"Def from {from_node} to {scopename} {to_node}")
        self.inner_scope_node = to_node  # Available to callers via `with ... as scope_ctx:`.
