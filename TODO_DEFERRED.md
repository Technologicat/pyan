# Deferred TODOs

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## "Node" terminology overload

Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Consider introducing distinct terminology.

## Edge confidence scoring

Determine confidence of detected edges. See [DESIGN-NOTES.md](DESIGN-NOTES.md).

## Improved wildcard resolution

Partly addressed by #88 fix (import-aware expansion). Remainder: see [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).

Measured 2026-08-21, in case anyone is tempted to retire the machinery as a leftover from the era before base-class lookup: it is load-bearing, and increasingly so with project size. Counting only edges between defined, non-wildcard Nodes, disabling `contract_nonexistents` + `expand_unknowns` costs 3 edges on pyan, 96 on mcpyrate, and **3198 on raven — about 20% of that graph**. The wildcard round-trip is what recovers cross-module attribute access on objects pyan cannot type, which is most of what a large application does.

That measures quantity, not correctness. Expansion is an overapproximation, and how many of those 3198 are real is unknown; establishing that needs ground truth this project does not have.

## The same input does not always produce the same graph

*Cluster: analyzer · Cost: ? · Gate: none · Filed: 2026-08-21*

Two runs over the same 328-file project, in the same process, differ. Measured on raven: 47588 edges then 47586, the two extra both wildcards — `raven.librarian.chat_controller._descend_to_latest -> *.get_payload` and `raven.visualizer.info_panel.build_window -> *.is_any_modal_window_visible`.

Two distinct causes. The hash seed accounts for about two edges — fixing `PYTHONHASHSEED` makes a run reproducible, so something iterates a set of strings. **File order accounts for the rest, and is much the larger:** on mcpyrate, with the seed pinned, sorted input gives 6673 edges, reversed 6721, shuffled 6734 — a 1% swing decided by the order of arguments on the command line.

Investigated 2026-08-21; the mechanism is known, and it is not where one would look first.

- **Not the postprocessor.** The divergence is already 95 edges straight out of the visitor passes, before any stage runs.
- **Not an unreached fixed point.** Three and four passes give exactly the same 86-edge difference as two. The analysis converges — to different answers.
- **It is pass 1 recording edges that pass 2 would not, and nothing retracting them.** Discarding `uses_edges` after pass 1 drops the order-dependence from 86 edges to 1. That also removes 236 edges from mcpyrate's graph, ~3.5% of it: residue recorded before the analyzer knew enough.

**Suppressing only the wildcards in pass 1 does not work**, and the reason is worth knowing: pass 1 does not record wildcards. It records edges to *name Nodes that turn out not to exist*, and `contract_nonexistents` converts those to `*.name` afterwards. Refusing namespace-`None` targets during pass 1 therefore drops 6 edges and leaves the order-dependence at 86.

**Discarding pass 1 wholesale is not the fix either**, because 34 of those 236 are resolved edges that only pass 1 produces — a forward reference to a module-level name bound *after* the function that reads it:

```python
def deactivate():
    SourceFileLoader.path_stats = stdlib_path_stats   # visited first
stdlib_path_stats = SourceFileLoader.path_stats       # bound later
```

Pass 1 finds the name unbound and links to the NAME Node; pass 2 finds it bound, to an unresolved attribute, and uses the value instead, so the link to the name is never remade. Both orders produce this edge — the binding is in the same file, so pass 1 always reaches the function first. **Deterministic, and not the source of the nondeterminism.** It is a pass-1-only edge, which is a separate question about which pass should win.

**The order-dependence is the cross-file case**, where whether pass 1 could resolve at all depends on which file came first. `mcpyrate.astdumper.dump.recurse -> *.FIELDNAME` is present with the files sorted and absent with them reversed: `FIELDNAME` is set as `self.FIELDNAME` in `ColorScheme.__init__`, so the attribute is only known once `colorizer.py` has been visited. Pass 2 always resolves it, so the *resolved* edge converges. The pass-1 artifact does not, because nothing retracts it.

So the fix wants edges that pass 2 supersedes to be withdrawn, which needs a way to tell "pass 1 could not resolve this yet" from "this genuinely refers to the name" — the two look identical at the point the edge is made. Note that is the same name-versus-value question as the module-level constant fix (2026-08-21), where the name turned out to be the more useful target.

Why it matters beyond tidiness: a graph that changes between runs cannot be diffed against a previous revision, which is a main reason to keep one. It also makes output comparison unreliable as a regression check — verifying the `*args` subscript change meant telling a real one-edge difference from this noise, which needed the seed pinned and the file list fixed.

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


## The cycle report and the module graph name packages differently

*Cluster: modvis dependency resolution · Cost: S · Gate: needs a decision on the speculative deps · Filed: 2026-08-21*

`detect_cycles` walks `self.modules` directly, where a package is keyed `pkg.__init__` and every
import under it carries a speculative dependency on that key. `prepare_graph` draws the same
package as `pkg` and drops those speculative deps. So `-C` and `--text` describe the same tree in
two vocabularies, and a reader cross-referencing one against the other has to know that
`harbor.__init__` and `harbor` are the same node.

Renaming in the report is the easy half. The hard half is that the speculative deps are
*load-bearing for cycle detection* — a cycle between two packages typically runs through exactly
those implicit imports, and the `detect_cycles` docstring says as much. So they cannot simply be
filtered to match the graph; the report would have to name them as what they are (an implicit
dependency on the package's initialization) rather than as an ordinary import.

Noticed while fixing the dependency-on-a-package bug (2026-08-21), which made the mismatch
visible: before it, the default graph did not draw packages at all.


## `--module-level` misses `from . import name` when the name lives in `__init__.py`

*Cluster: modvis dependency resolution · Cost: M · Gate: none · Filed: 2026-08-21*

`add_dependency` records what an import *names*, and separately speculates that each dotted
prefix might be a package by adding `<prefix>.__init__`. `prepare_graph` then keeps whichever of
those exists in the analyzed set. That covers `from pkg import x` (the plain dep on `pkg`
resolves to the package's node) but not the relative form.

`from . import thing`, written in `pkg/sub.py` where `thing` is a *name* defined in
`pkg/__init__.py`, resolves to `pkg.thing`, and `add_dependency("pkg.thing")` records:

- `pkg.thing` — no such module, correctly dropped;
- `pkg.__init__` — speculative, dropped by default along with every other module's;
- `pkg.thing.__init__` — no such module, correctly dropped.

So nothing is left, and a real dependency on the package goes unrecorded. `from .. import thing`
is the same shape one level up. Note the *submodule* case (`from . import gamma`, gamma being
`gamma.py`) is fine — `pkg.gamma` is a real module and resolves.

The fix wants the speculative entries resolved against the analyzed set once both passes are
done, rather than each import guessing in isolation: if `pkg.thing` turns out not to be a
module, the dependency is on `pkg` itself. That needs `add_dependency` to keep the speculative
deps distinguishable from the plain ones — presently they go into the same set — so it is a
change to how dependencies are recorded, not a filter at the end.

Discovered while fixing the sibling case, where a dependency on a package was dropped because
the package's node was named `pkg.__init__` and the dependency was named `pkg` (2026-08-21).
