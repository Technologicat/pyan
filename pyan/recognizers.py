#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pattern recognizers for the analyzer (#129 — NAMESPACE_OBJECT overlay).

Each recognizer inspects an AST shape and, on a match, registers an
implied binding into the visitor's scope/graph state. On a miss, the
recognizer is a no-op — the analyzer falls through to its default
handling (typically the #127 module-level fallback).

Three public entry points:

- :func:`maybe_register_name_literal` — track string-literal name
  bindings (level 2/3 input for ``setattr`` recognition)
- :func:`maybe_register_namespace_object` — recognize
  ``LHS = constructor(**kwargs)`` against the registry of namespace
  constructors and upgrade the LHS Node's flavor + populate its scope
- :func:`maybe_register_setattr_call` — recognize
  ``setattr(obj, "name", value)`` on a NAMESPACE_OBJECT target

All take the visitor as the first positional argument and operate on
its state. Helper functions prefixed with ``_`` are module-internal.

See ``briefs/namespace-objects-brief.md`` for the design context.
"""

import ast
import builtins as _builtins_module

from .anutils import Scope, UnresolvedSuperCallError
from .node import Flavor, Node

__all__ = [
    "maybe_register_name_literal",
    "maybe_register_namespace_object",
    "maybe_register_setattr_call",
]


def maybe_register_name_literal(visitor, name_target, rhs_ast):
    """If a ``Name`` binding's rhs is a string ``Constant``, record the
    bound value in ``visitor.name_literals[ns][name]``.

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
    if not visitor.scope_stack:
        return
    # Track at module/class scope only (mirrors `_maybe_define_name_node`):
    # function-local literal bindings aren't externally addressable, and
    # cross-module lookups require the binding to live in a module's namespace.
    if visitor.scope_stack[-1].type not in ("module", "class"):
        return
    from_node = visitor.get_node_of_current_namespace()
    ns = from_node.get_name()
    visitor.name_literals.setdefault(ns, {})[name_target.id] = rhs_ast.value


def maybe_register_namespace_object(visitor, name_target, rhs_ast):
    """Pattern: ``LHS = constructor(**kwargs)`` where *constructor*'s
    fully-qualified import origin is in ``visitor.namespace_constructors``.

    Recognizes:

    - ``config = env(thingy=baa)`` (canonical)
    - ``config: Env = env(thingy=baa)`` (annotated)
    - ``(config := env(thingy=baa))`` (walrus)
    - ``with env(thingy=baa) as config:`` (context manager — same path
      via ``_visit_with`` → ``analyze_binding``)

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
    if not visitor.scope_stack or visitor.scope_stack[-1].type not in ("module", "class"):
        return
    fqn = _resolve_constructor_fqn(visitor, rhs_ast.func)
    if fqn is None or fqn not in visitor.namespace_constructors:
        return
    from_node = visitor.get_node_of_current_namespace()
    ns = from_node.get_name()
    # Locate the LHS Node (already created by `_maybe_define_name_node`)
    # and upgrade its flavor.  Direct assignment bypasses
    # `Flavor.specificity`'s upgrade gate, which is intentional —
    # we have additional information (the rhs is a known constructor)
    # that the gate doesn't know about.
    obj_node = visitor.get_node(ns, name_target.id, name_target)
    obj_node.flavor = Flavor.NAMESPACE_OBJECT
    obj_node.defined = True
    if visitor.add_defines_edge(from_node, obj_node):
        visitor.logger.info(f"Def from {from_node} to NAMESPACE_OBJECT {obj_node}")
    # Repoint the scope binding from the constructor (e.g. the env
    # IMPORTEDITEM) to the new NAMESPACE_OBJECT Node, so that later
    # ``config.attr`` lookups walk into ``mymod.config``'s scope rather
    # than into the constructor's namespace.  Plain NAME Nodes don't do
    # this — the binding is kept at the rhs value so e.g. ``pd =
    # pandas; pd.DataFrame`` still resolves into pandas' namespace.
    # NAMESPACE_OBJECT is the case where attribute resolution should
    # stay on the LHS itself.
    visitor.set_value(name_target.id, obj_node)
    # Ensure the scope exists at construction time, even when no
    # kwargs were passed.  Otherwise the staged form ``config = env();
    # config.a = baa`` breaks: the later attribute write goes through
    # ``set_attribute``, which writes into an *existing* scope but
    # doesn't create one (writes to non-NAMESPACE_OBJECT obj.attr
    # paths shouldn't materialize scopes either).
    obj_ns = obj_node.get_name()
    if obj_ns not in visitor.scopes:
        visitor.scopes[obj_ns] = Scope.from_names(obj_ns, [])
    for kw in rhs_ast.keywords:
        if kw.arg is None:  # **kwargs splat — not statically visible
            continue
        _register_namespace_object_attr(visitor, obj_node, kw.arg, visitor.visit(kw.value))


def maybe_register_setattr_call(visitor, call_ast):
    """Recognize ``setattr(target, name, value)`` calls on
    ``NAMESPACE_OBJECT``-flavored Nodes and register the implied
    binding in *target*'s scope, mirroring ``e.k = v``.

    Three structural preconditions:

    1. ``call_ast.func`` resolves to FQN ``"builtins.setattr"`` (handles
       aliased imports for free via scope-chain resolution).
    2. ``target`` (first positional arg) resolves to a Node with
       ``flavor=NAMESPACE_OBJECT`` (so a scope exists for it).
    3. ``name`` (second positional arg) resolves to a string via the
       three-level resolution in :func:`_resolve_setattr_name`.

    On match: ``visitor.scopes[target_node.get_name()].defs[name] = visit(value)``.
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
    fqn = _resolve_constructor_fqn(visitor, call_ast.func)
    if fqn != "builtins.setattr":
        return
    # Precondition 2: target resolves to a NAMESPACE_OBJECT Node.
    target_node = visitor.get_value(target_arg.id)
    if not isinstance(target_node, Node) or target_node.flavor != Flavor.NAMESPACE_OBJECT:
        return
    # Precondition 3: name resolves to a string literal.
    attr_name = _resolve_setattr_name(visitor, name_arg)
    if attr_name is None:
        return
    # Register the binding into target's scope.  set_attribute can't
    # be used here — its API takes an Attribute AST node, which we
    # don't have (the LHS *is* a Call, not an Attribute).
    _register_namespace_object_attr(visitor, target_node, attr_name, visitor.visit(value_arg))


###############################################################################
# Internal helpers


def _register_namespace_object_attr(visitor, obj_node, attr_name, attr_value):
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
    if obj_ns not in visitor.scopes:
        visitor.scopes[obj_ns] = Scope.from_names(obj_ns, [])
    visitor.scopes[obj_ns].defs[attr_name] = attr_value
    visitor.logger.info(f"Registered {attr_name} -> {attr_value} in NAMESPACE_OBJECT {obj_node}")


def _resolve_constructor_fqn(visitor, func_ast):
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
        node = visitor.get_value(func_ast.id)
        if isinstance(node, Node) and node.namespace is not None:
            return _fqn_of_node(node)
        # Builtin fallback — only fires when the name isn't user-bound.
        if hasattr(_builtins_module, func_ast.id):
            return f"builtins.{func_ast.id}"
        return None
    if isinstance(func_ast, ast.Attribute):
        try:
            obj_node, attr_name = visitor.resolve_attribute(func_ast)
        except UnresolvedSuperCallError:
            return None
        if not isinstance(obj_node, Node) or obj_node.namespace is None:
            return None
        ns = obj_node.get_name()
        if ns in visitor.scopes and attr_name in visitor.scopes[ns].defs:
            resolved = visitor.scopes[ns].defs[attr_name]
            if isinstance(resolved, Node):
                return _fqn_of_node(resolved)
        # Unanalyzed-module case: reconstruct from the dotted path.
        return f"{ns}.{attr_name}"
    return None


def _fqn_of_node(node):
    if not node.namespace:
        return node.name
    return f"{node.namespace}.{node.name}"


def _resolve_setattr_name(visitor, name_arg_ast):
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
        ns = visitor.get_node_of_current_namespace().get_name()
        while True:
            bucket = visitor.name_literals.get(ns, {})
            if name_arg_ast.id in bucket:
                return bucket[name_arg_ast.id]
            if "." not in ns:
                break
            ns = ns.rsplit(".", 1)[0]
        # Level 3: the Name might resolve to an imported binding.
        # `get_value` returns the resolved Node (after import resolution
        # within the visitor pass).  Look up its FQN's namespace in
        # `name_literals`.
        resolved = visitor.get_value(name_arg_ast.id)
        if isinstance(resolved, Node) and resolved.namespace is not None:
            bucket = visitor.name_literals.get(resolved.namespace, {})
            if resolved.name in bucket:
                return bucket[resolved.name]
    return None
