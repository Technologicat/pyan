# Deferred TODOs

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## "Node" terminology overload

Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Consider introducing distinct terminology.

## Edge confidence scoring

Determine confidence of detected edges. See [DESIGN-NOTES.md](DESIGN-NOTES.md).

## Improved wildcard resolution

Partly addressed by #88 fix (import-aware expansion). Remainder: see [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).

## A module-level constant that *is* used still produces no uses edge

*Cluster: analyzer · Cost: ? · Gate: none · Filed: 2026-08-20 · See also: #140*

Given `CONSTANT = 42` at module level and a `def caller(): return CONSTANT` in the same file, the analyzer records no edge from `caller` to `m.CONSTANT`. The Node exists — flavor `name`, `defined=True` — and the sibling `UNUSED_CONSTANT` is indistinguishable from it in the graph. visgraph then drops NAME Nodes that have no uses edges, so a constant is invisible whether or not anything reads it.

Unknown whether this is deliberate (a constant is not a call, and a call graph may not want it) or a gap in binding tracking for module-level names read from an inner scope.

It matters for the docs either way: the README's "What the graph leaves out" says that a module-level binding *nothing uses* is not drawn, which a reader will take to mean used ones are. Once the behaviour is settled, that sentence needs to match it.

Discovered while documenting the graph-shaping rules for #140 (2026-08-20).

## Packages with no members are drawn as isolated nodes

*Cluster: rendering · Cost: S · Gate: needs a decision on whether an empty package is worth showing · Filed: 2026-08-20 · See also: #140*

An `__init__.py` with nothing in it yields a module Node with no edges, and — since a module's cluster exists only where it has non-module members — no cluster either. A grouped graph of `pkg/api/routes/...` therefore shows `pkg`, `pkg.api`, `pkg.api.routes` and `pkg.api.schemas` as lone ellipses off to one side, connected to nothing.

Distinct from the twin-node problem #140 fixed: these never had a box to be merged into. What they convey is that the package exists, which the dotted names of everything inside it already convey.

Filtering them is a one-line change, so the work is the decision, not the patch.

Discovered while checking the grouped rendering for #140 (2026-08-20).

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

## Audit typing: abstract parameter types, concrete return types

Parameters should use abstract types from `collections.abc` (`Mapping`, `Sequence`, `Iterable`) for widest-possible-accepted semantics. Return types should use concrete lowercase builtins (`tuple[int, int]`, `list[int]`, `dict[str, int]`) — PEP 585, Python 3.9+. The capitalized `typing` forms (`Dict`, `List`, `Tuple`) are deprecated aliases for the builtins and offer no extra width — avoid them. Audit existing type hints across the codebase for consistency.

Discovered during raven-cherrypick compare mode planning (2026-03-30).

## expand_unknowns leaves dangling wildcard edges instead of removing them

`expand_unknowns` adds the resolved edges but never removes the originating `*.name` wildcard edge; the wildcard Node is merely flagged `defined = False` at the end of the pass, and visgraph filters undefined Nodes at render time. So the uses/defines dicts carry edges to soon-to-be-suppressed phantom Nodes, and correctness depends on every consumer honouring the `defined` flag. The query API (`find_paths`, `get_related_nodes`) walks the edge dicts directly — worth confirming it filters undefined targets, and worth considering whether expansion should rewrite the edge (drop the wildcard, add the real target) rather than overlay-and-suppress. Off-key architecture, not a live bug.

Noticed while reviewing PR #135 / issue #134 (2026-06-20).

## Should genexprs use their real symtable scope rather than a synthesized one?

`analyze_comprehension` synthesizes a scope when the expected one is missing
(`analyzer.py:1281–1284`, via `Scope.from_names`), while `visit_Lambda` requires the scope to
already exist — `ExecuteInInnerScope` raises `ValueError: Unknown scope` otherwise. That
asymmetry is what made the Python 3.15 `symtable` rename show up only through lambdas: genexprs
hit the synthesis path and carried on silently.

The tempting reading is that lambdas want a fallback too. Looking at why the synthesis exists
suggests the opposite. `Scope.from_names` was added for PEP 709: on 3.12+ `symtable` genuinely
stops reporting scopes for list/set/dict comprehensions, because they are inlined into the
enclosing function. For those, synthesis is not a fallback at all — it is the only path
available. **Generator expressions were never inlined**, so `symtable` still reports a real
scope for them, carrying symbol information a synthesized scope (target names only) does not
have. Verified on both 3.14 and 3.15: a function containing three comprehensions has no
symtable children, while one containing a genexpr has a `genexpr` / `<genexpr>` child.

So the question is whether genexprs should be *required* to find their real scope, the way
lambdas are, with synthesis reserved for the inlined kinds that cannot have one. That would
have turned the 3.15 rename into a loud failure on genexprs too, rather than a silent downgrade
to a scope holding less information.

Worth measuring before acting: check whether any resolution actually differs between the
synthesized and the real genexpr scope. If nothing differs, this is cosmetic and the present
leniency is fine; if something does, the leniency has been quietly costing accuracy since 3.12.

Raised 2026-08-17 during the Python 3.15 support work. The normalization fix landed then already
restores the real scope on 3.15 — this item is about the general shape, not that bug.
