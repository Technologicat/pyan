# Deferred TODOs

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## "Node" terminology overload

Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Consider introducing distinct terminology.

## Edge confidence scoring

Determine confidence of detected edges. See [DESIGN-NOTES.md](DESIGN-NOTES.md).

## Improved wildcard resolution

Partly addressed by #88 fix (import-aware expansion). Remainder: see [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).

## Type inference for function arguments

Would reduce wildcard noise by resolving argument types at call sites. Ambitious.

## Tuples/lists as first-class values

`x = [a, b, c]` overapproximates via Cartesian fallback. Would need flow-sensitive analysis.

## Subscript assignment

`ast.Subscript` in assignment targets — binding information not recorded.

## Additional unpacking generalizations (PEP 448)

`{**a, **b}`, `[*a, *b]` — uses detected, bindings not recorded.

## Resolving function call results

Return type tracking beyond the `super()` special case.

## Per-namespace `resolve_imports`

Global IMPORTEDITEM remapping can leak function-level imports to siblings. Partially mitigated by `_has_import_to()` in `expand_unknowns`.

## Document the visitor-to-visgraph protocol

`VisualGraph.from_visitor` expects an implicit protocol (`nodes`, `uses_edges`, `defines_edges`). Mostly resolved by the `CallGraph` extraction — the visitor exposes those as properties on `self.graph`. Could now accept a `CallGraph` directly instead of the visitor; minor follow-up.

## Type annotations for pyan's own code

Add type annotations to pyan's modules. The analyzer is the largest target. Would improve IDE support and catch bugs.

## NAMESPACE_OBJECT in a same-named module renders confusingly

When a NAMESPACE_OBJECT is bound at the top of a module that shares its name (e.g. `raven.visualizer.app_state` contains `app_state = env(...)`), visgraph emits both a standalone node for the module and a cluster (group box) labelled with the same dotted path containing the env Node — visually two "raven.visualizer.app_state" boxes side by side. The data model is correct (module Node has its own edges; cluster groups Nodes whose namespace equals the module path), but the rendering doesn't disambiguate the two roles. Consider either suppressing the standalone module Node when its namespace also has a cluster, or labelling the cluster differently (e.g. with a leading marker).

Discovered while smoke-testing #129 against Raven Visualizer (2026-04-29).

## Audit typing: abstract parameter types, concrete return types

Parameters should use abstract types from `collections.abc` (`Mapping`, `Sequence`, `Iterable`) for widest-possible-accepted semantics. Return types should use concrete lowercase builtins (`tuple[int, int]`, `list[int]`, `dict[str, int]`) — PEP 585, Python 3.9+. The capitalized `typing` forms (`Dict`, `List`, `Tuple`) are deprecated aliases for the builtins and offer no extra width — avoid them. Audit existing type hints across the codebase for consistency.

Discovered during raven-cherrypick compare mode planning (2026-03-30).
