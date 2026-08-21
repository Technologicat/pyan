# Deferred TODOs

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## "Node" terminology overload

Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Consider introducing distinct terminology.

## Edge confidence scoring

Determine confidence of detected edges. See [DESIGN-NOTES.md](DESIGN-NOTES.md).

## Improved wildcard resolution

Partly addressed by #88 fix (import-aware expansion). Remainder: see [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).

## The same input does not always produce the same graph

*Cluster: analyzer · Cost: ? · Gate: none · Filed: 2026-08-21*

Two runs over the same 328-file project, in the same process, differ. Measured on raven: 47588 edges then 47586, the two extra both wildcards — `raven.librarian.chat_controller._descend_to_latest -> *.get_payload` and `raven.visualizer.info_panel.build_window -> *.is_any_modal_window_visible`.

Two distinct causes, and the second is much the larger:

- **Hash seed.** Fixing `PYTHONHASHSEED` makes a run reproducible: seed 0 gives 47675 edges with a stable digest across runs, seed 1 gives 47676. So something downstream — `expand_unknowns` is the obvious suspect, since every observed difference is a wildcard — depends on the iteration order of a set or dict keyed by strings.
- **File order.** The same files given in a different order change the result by roughly 88 edges (47587 unsorted glob vs 47675 sorted). Much bigger than the hash effect, and it means the command line's argument order is part of the answer.

Why it matters beyond tidiness: a call graph that changes between runs cannot be diffed against a previous one, which is what anybody comparing two revisions of a project wants to do. It also makes output comparison unreliable as a regression check — the `*args` subscript work had to distinguish a real one-edge change from this noise, and could only do so by pinning the seed.

Worth establishing first whether the file-order dependence is a *bug* or the documented consequence of two-pass analysis: pass 1 collects definitions and pass 2 resolves, so order should not matter, and the fact that it does suggests something is resolved during pass 1 that ought to wait.

Found while diffing edge sets to verify the subscript change (2026-08-21).

## Function attributes and locals share one scope dictionary

*Cluster: analyzer · Cost: M · Gate: none · Filed: 2026-08-21*

`helper.marker = Thing` is recorded and `helper.marker()` resolves — but by accident rather than by design. The binding lands in `scopes["mod.helper"].defs`, the same dictionary holding `helper`'s locals, and nothing at the point of lookup tells the two apart. So an attribute access on a function would reach its locals as readily as its attributes, which is why a parameter annotated with a function is deliberately not bound to it (see "What a parameter's annotation means" in the README): `cb.stash.method()` would resolve against a local `stash`.

The discriminator already exists and is unused. `Scope.locals` holds exactly the names `symtable` reports as local, and an attribute assigned from outside the function is not among them — so a `defs` entry absent from `locals` is an attribute.

Worth settling rather than leaving to luck, because function attributes are load-bearing in real code: `unpythonic.syntax` stashes markers on functions.

The assignment-on-a-named-function half looks entirely tractable, and has precedent: the NAMESPACE_OBJECT overlay (#129) already turns attribute assignments into scope entries deliberately.

The harder half is an attribute stashed onto a *parameter* inside a decorator, since knowing which functions acquire it means knowing which functions reach that parameter. In full generality that is interprocedural dataflow and out of scope. Worth checking first whether the decorator case collapses to something bounded, though: pyan already resolves decorators statically, so "this decorator's body assigns `func.attr`, therefore everything it decorates has `attr`" may be a pattern rather than a dataflow problem. Unverified — that is the thing to establish before estimating the rest.

Raised while reviewing why annotated parameters bind only to classes (2026-08-21).

## Log calls build their messages whether or not logging is on

*Cluster: performance · Cost: M (mechanical but widespread) · Gate: none · Filed: 2026-08-21*

Profiling a 94k-line project shows **8 million calls to `Scope.__repr__`**, about 1.5s of a 16s run, with logging disabled entirely. The analyzer logs through f-strings — `self.logger.debug(f"Get {name} in {self.scope_stack[-1]}, found in {sc}")` — and an f-string is evaluated before the call, so every message is formatted and thrown away.

The fix is the lazy form, `logger.debug("Get %s in %s", name, scope)`, which defers formatting to the handler. Mechanical, but there are a lot of call sites, and a blind find-replace would break the ones doing real work in the expression rather than just interpolating.

Worth measuring before committing to it: `__repr__` is the visible 1.5s, but the f-string machinery around it costs more than that, and how much more is unknown.

Found while re-profiling after the attribute-fallback speedup (2026-08-21).

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
