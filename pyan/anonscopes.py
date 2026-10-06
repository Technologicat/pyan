"""Name the lambdas and comprehensions of a module, and find each one's `symtable` table.

The visitor walks a lambda inside the namespace it names, like ``mod.f.lambda.1``, and looks up the
lambda's scope there. Both the name and the scope come from here, so the two cannot disagree.

**Names.** Anonymous scopes are numbered per kind within the namespace the visitor walks them in, in the
order `symtable` reports them — which is the order the compiler meets them, not always the reading order:
a function's defaults come before its decorators. Where `symtable` reports no table, which is a
comprehension inlined by PEP 709 (Python 3.12+), they are numbered in reading order instead. Only the
scopes the visitor walks in a namespace are counted there, so the names do not depend on which
comprehensions the running Python inlines.

**Tables.** Tag every lambda, comprehension, function and class with a marker name, run `symtable` on the
tagged source, and read off which table holds which marker. The analyzer then builds its scopes from that
same run, ignoring the markers.
"""

__all__ = ["scope_key", "ScopePlan", "plan_anonymous_scopes"]

import ast
import symtable
from typing import NamedTuple

from .anutils import ANON_SCOPE_NAMES, normalize_symtable_scope_name

_ANON_KINDS = {ast.Lambda: "lambda",
               ast.ListComp: "listcomp",
               ast.SetComp: "setcomp",
               ast.DictComp: "dictcomp",
               ast.GeneratorExp: "genexpr"}
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def scope_key(node):
    """Return the key identifying the lambda or comprehension *node* in a `ScopePlan`.

    The type and the source span, which no two such nodes share. It works across parses of the same source.
    """
    return type(node), node.lineno, node.col_offset, node.end_lineno, node.end_col_offset


class ScopePlan(NamedTuple):
    """The anonymous scopes of one module, as returned by `plan_anonymous_scopes`."""
    source: str  # the source this was made from
    table: symtable.SymbolTable  # the module's table, from the tagged source
    marker_prefix: str  # every marker name starts with this, and no name in the source does
    labels: dict  # `scope_key` → label, such as ``lambda.1``
    anon_tables: list  # (fully qualified name, table) of each anonymous scope that has a table
    synthesized: set  # `scope_key`s of the scopes that have none, whose scope the visitor must create


def plan_anonymous_scopes(source, filename, module_name):
    """Name the lambdas and comprehensions of the module *source*, whose namespace is *module_name*."""
    tree = ast.parse(source, filename)
    owners = _owners(tree)
    prefix = "_pyan_scope_"  # a double underscore would be name-mangled inside a class body
    while prefix in source:
        prefix = f"_{prefix}"
    try:
        top, by_marker = _tagged_symtable(tree, list(owners), prefix)
    except SyntaxError:
        # The tagged source is unparsed from the AST, so its line numbers are not the user's. The original
        # raises the same complaint about the right line.
        symtable.symtable(source, filename, "exec")
        raise

    # The position of each table in `symtable`'s traversal.
    tables = {}
    position = {}

    def walk(table):
        for child in table.get_children():
            node = _identify(child, by_marker)
            if node is not None:
                tables[node] = child
                position[node] = len(position)
            walk(child)

    walk(top)

    groups = {}
    for node, owner in owners.items():
        if type(node) in _ANON_KINDS:
            groups.setdefault((owner, _ANON_KINDS[type(node)]), []).append(node)
    labels = {}
    for (_owner, kind), nodes in groups.items():
        # One kind of scope either always has a table or never does: on 3.12+, `symtable` reports no list,
        # set or dict comprehension anywhere, and every generator expression. Should that ever not hold,
        # reading order is the one that applies to all of them.
        if all(node in position for node in nodes):
            nodes.sort(key=position.__getitem__)
        else:
            nodes.sort(key=lambda node: (node.lineno, node.col_offset))
        for index, node in enumerate(nodes):
            labels[node] = f"{kind}.{index}"

    names = {tree: module_name}

    def qualified_name(node):
        if node not in names:
            own = labels[node] if node in labels else node.name  # noqa: SIM401 -- `.get` would evaluate `node.name`, which an anonymous node lacks
            names[node] = f"{qualified_name(owners[node])}.{own}"
        return names[node]

    return ScopePlan(source=source,
                     table=top,
                     marker_prefix=prefix,
                     labels={scope_key(node): label for node, label in labels.items()},
                     anon_tables=[(qualified_name(node), table) for node, table in tables.items()
                                  if node in labels],
                     synthesized={scope_key(node) for node in labels if node not in tables})


def _inner_parts(node):
    """Return the children of *node* that the visitor walks inside *node*'s own namespace.

    This mirrors the visitor, not Python: annotations and class bases are visited inside the function or
    class, and a lambda's defaults inside the lambda. A comprehension's outermost iterable belongs outside.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = node.args
        params = [*a.posonlyargs, *a.args, a.vararg, *a.kwonlyargs, a.kwarg]
        annotations = [p.annotation for p in params if p is not None and p.annotation is not None]
        return [*annotations, *([node.returns] if node.returns is not None else []), *node.body]
    if isinstance(node, ast.ClassDef):
        return [*node.bases, *node.body]
    if isinstance(node, ast.Lambda):
        return [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None), node.body]
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        first, *rest = node.generators
        parts = [first.target, *first.ifs]
        for gen in rest:
            parts.extend([gen.target, gen.iter, *gen.ifs])
        if isinstance(node, ast.DictComp):
            # `value` is `None` in an unpacking comprehension, `{**d for d in ds}` (Python 3.15+).
            return [*parts, node.key, *([node.value] if node.value is not None else [])]
        return [*parts, node.elt]
    return []


def _owners(tree):
    """Map each function, class, lambda and comprehension in *tree* to the node whose namespace the visitor
    walks it in.

    That is the nearest enclosing function, class, lambda or comprehension, or *tree* itself at the top level.
    """
    owners = {}
    inner = set()  # ids of nodes walked under their scope node rather than under its owner

    def walk(node, owner):
        if type(node) in _ANON_KINDS or isinstance(node, _DEFS):
            owners[node] = owner
        parts = _inner_parts(node)
        inner.update(id(part) for part in parts)
        for child in ast.iter_child_nodes(node):
            walk_outer(child, owner)
        for part in parts:
            walk(part, node)

    def walk_outer(node, owner):
        if id(node) not in inner:
            walk(node, owner)

    walk(tree, tree)
    return owners


def _tagged_symtable(tree, nodes, prefix):
    """Tag each of *nodes* in *tree*, in place, with a marker name, and run `symtable` on the result.

    The marker is *prefix* plus a number, and is a name the node's own scope refers to: a lambda's body and
    a comprehension's output expression are wrapped as ``(marker, expr)``, and a function or class body
    gets ``marker`` as its first statement. Returns the module's table, and a dict mapping each marker to
    its node.
    """
    by_marker = {}
    for index, node in enumerate(nodes):
        marker = f"{prefix}{index}"
        by_marker[marker] = node
        load = ast.Name(id=marker, ctx=ast.Load())
        if isinstance(node, ast.Lambda):
            node.body = ast.Tuple(elts=[load, node.body], ctx=ast.Load())
        elif isinstance(node, ast.DictComp):
            node.key = ast.Tuple(elts=[load, node.key], ctx=ast.Load())
        elif type(node) in _ANON_KINDS:
            node.elt = ast.Tuple(elts=[load, node.elt], ctx=ast.Load())
        else:
            node.body.insert(0, ast.Expr(value=load))
    return symtable.symtable(ast.unparse(tree), "<pyan>", "exec"), by_marker


def _identify(table, by_marker):
    """Return the node *table* belongs to, or `None` if it holds no marker of its own.

    That is the one node whose marker the table refers to and none of its children does. Tables of scopes
    with no AST node of their own — a PEP 695 type-parameter scope, an ``__annotate__`` scope — hold none.
    """
    inherited = {name for child in table.get_children() for name in child.get_identifiers()}
    candidates = [by_marker[name] for name in table.get_identifiers()
                  if name in by_marker and name not in inherited]
    kind = normalize_symtable_scope_name(table.get_name())
    if kind in ANON_SCOPE_NAMES:
        candidates = [node for node in candidates if _ANON_KINDS.get(type(node)) == kind]
    else:  # an inlined comprehension's marker lands in the enclosing function's table
        candidates = [node for node in candidates if isinstance(node, _DEFS) and node.name == table.get_name()]
    return candidates[0] if len(candidates) == 1 else None
