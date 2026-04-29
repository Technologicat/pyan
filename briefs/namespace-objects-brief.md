# Namespace Objects — Design Brief

This brief documents the design behind the work tracked in **#129** (resolve attribute access on namespace-constructor bindings to the specific target) and its prequisite — generalising the analyzer's notion of "defined Node" to cover module-level name bindings.

Audience: future archaeology. If you're trying to figure out *why* `Flavor.SCOPE` and `Flavor.NAMESPACE_OBJECT` exist as separate flavors, or why module-level `x = 5` produces a defined Node where it previously did not, this is the document.

## Context

### The asymmetry

Until this work, the analyzer treated only a subset of Python's named entities as graph Nodes:

- `class Foo: ...` → defined `CLASS` Node at `mymod.Foo`, with a populated scope.
- `def foo(): ...` → defined `FUNCTION` / `METHOD` Node at `mymod.foo`, with a scope.
- `import foo` / `from x import foo` → `IMPORTEDITEM` Node, remapped during postprocessing.
- `mymod.x = 5` (plain module-level assignment) → **no Node**. Just a `set_value("x", ...)` into the module's scope's `defs` dict. Invisible from outside the module.

The asymmetry has two consequences:

1. **`from mymod import x` for a plain assignment can't resolve.** The IMPORTEDITEM at `mymod.x` has nothing to remap to — there is no defined Node at that path. Postprocessing contracts it to a wildcard. The edge to the actual binding is lost.
2. **Attribute resolution on namespace-like values fails.** `config = env(thingy=baa)` followed by external `config.thingy` cannot resolve, because `config` is not a Node and has no scope. #127 patched this with a module-level fallback edge, which is honest but coarse — the edge lands on the *module* containing `config`, not on `config` itself or its kwarg target.

#129 set out to fix the second consequence for namespace-constructor bindings specifically. In design, we found that the cleaner shape is to fix the underlying asymmetry first, and let #129 fall out as a small overlay.

### The principle

> Every named entity reachable from outside its definition site is a Node.

"Reachable from outside" is the cut. Module-level and class-level bindings are reachable (via import, via attribute access). Function locals are not — promoting every loop variable to a Node would make the graph unusable. Closures are the existing exception, already handled by the nested-def machinery.

Under this principle, the analyzer's existing handling of classes / functions / modules is the rule, and "plain module-level assignment is invisible" was the deviation. We bring assignments into line.

## Two-PR plan

The work splits into a **[prequisite](https://github.com/Technologicat/substrate-independent/blob/main/glossary.md#prequisite)** (architectural cleanup, no new feature) and **#129** (the targeted overlay). Done in this order so each diff is reviewable on its own and the test churn from the prequisite doesn't co-mingle with the feature's logic.

### PR 1 — Prequisite: module-level NAME Node-ification

**What changes**:

- Every module-level binding produces a defined `NAME`-flavored Node, addressable via the LHS dotted path. (`Flavor.NAME` was previously used only for PEP 695 type aliases at `analyzer.py:1337`. We extend its remit.)
- Class-level bindings already produce attribute Nodes via the existing class-scope machinery; no change there.
- Function-locals still go through `set_value`-only — no Node, no graph clutter. The cut is module-level + class-level.
- A flavor rename for clarity: **`Flavor.NAMESPACE` → `Flavor.SCOPE`**. The existing `NAMESPACE` flavor is the synthetic "this dotted prefix represents a namespace" marker used for structural bookkeeping (module / class / function scope objects). Calling it `SCOPE` keeps it distinguishable from #129's runtime-namespace flavor (`NAMESPACE_OBJECT`). The Node represents the scope; the `Scope` class implements one — same concept at two layers.
- Default-suppress NAME Nodes that have no incoming or outgoing edges. Module constants like `__version__ = "..."` would otherwise add visual noise to the default graph output. Suppression happens in the visgraph layer (filtering before render), not the analyzer (the Node still exists for cross-module resolution). A future CLI flag can opt back in if anyone wants the noise.

**Behavioral consequences**:

- `from mymod import CONSTANT` now creates an edge to the actual `mymod.CONSTANT` Node instead of contracting to a wildcard. Latent precision win across the codebase.
- Test fixture churn: any fixture with module-level constants will gain new defines edges. Mechanically tedious but bounded — each test's regenerated graph is mechanically derivable from its source.
- Public API: no changes to `create_callgraph` / `create_modulegraph` signatures.

### PR 2 — #129: NAMESPACE_OBJECT overlay

Layered onto PR 1's foundation. The framing changes from "create a new kind of Node" to "upgrade a NAME Node's flavor and populate its scope."

**What changes**:

1. **New flavor `Flavor.NAMESPACE_OBJECT`** in `node.py`, with a comment cross-linking to `Flavor.SCOPE` (which up to pyan3 2.5.0 used to be named `Flavor.NAMESPACE`) to disambiguate. Semantically: a runtime namespace value (an `env` instance, a `SimpleNamespace` instance), populated with statically-visible kwargs.

2. **Constructor registry** — module-level frozenset in `anutils.py`:
   ```python
   NAMESPACE_CONSTRUCTORS = frozenset({
       "unpythonic.env.env",
       "unpythonic.env",   # top-level re-export (yes, the module shadows the class)
       "types.SimpleNamespace",
       "argparse.Namespace",
   })
   ```
   Merged at analyzer-construction time with user additions from CLI (`--namespace-constructor FQN`, `action="append"`, accepts comma-split). One-shot stderr nudge fires the first time the option is supplied, inviting the user to file an issue if their constructor is reasonably common — we want to grow the built-in registry from observed real-world use.

3. **Single recognition helper**, called from the four binding sites (`visit_Assign`, `visit_AnnAssign`, `visit_NamedExpr`, `_visit_with`). Detects `Call(func=...)` rhs whose resolved func has a fully-qualified import origin (`namespace + "." + name`) in the merged registry. On hit:
   - Upgrades the LHS Node's flavor from `NAME` to `NAMESPACE_OBJECT`.
   - Ensures `self.scopes[lhs.get_name()]` exists.
   - Registers `{kwarg.arg: visit(kwarg.value)}` into that scope's `defs`.

4. **Attribute writes (`e.k = v`) need no new code.** `_bind_target`'s Attribute branch already calls `set_attribute`, which writes into the obj's scope's `defs` if the scope exists (`analyzer.py:2326-2331`). PR 1's Node creation + PR 2's scope creation is sufficient; later writes are picked up automatically. This covers the staged form `config = env(); config.a = baa` for free.

5. **`setattr(target, name, value)` recognition.** Symmetric counterpart to point 4 for the dynamic form. A helper `_try_register_setattr_call` in `visit_Call` checks two structural preconditions (`func` resolves to FQN `"builtins.setattr"` — handles aliased imports for free via scope-chain resolution; `target` resolves to a `NAMESPACE_OBJECT`-flavored Node) and then resolves `name` through three concentric levels of static knowability:

   - **Level 1 — literal string.** `name` is `Constant(value=str)`. Use the value directly.
   - **Level 2 — name-bound literal.** `name` is `Name(id=k)` where the scope chain has `k` bound to a string literal. Requires a parallel tracking state: a `name_literals` dict (or extension of `Scope`) populated in `visit_Assign` / `visit_AnnAssign` whenever a `Name` target gets a string-`Constant` rhs. Flow-insensitive (latest-seen wins) — same posture pyan takes elsewhere.
   - **Level 3 — cross-module name-bound literal.** `name` is `Name(id=k)` where `k` resolves through an import to a string literal in another module. The `name_literals` machinery is per-module (keyed by namespace); cross-module lookup follows the same path import resolution does. PR 1's module-level Node-ification is what makes this addressable.

   On match (any level): write `{resolved_name: visit(value)}` into target's scope's `defs`. On miss: no-op — same floor as today.

   The symmetric `delattr(target, name)` is intentionally not handled: pyan is flow-insensitive and already chooses not to clear bindings on `del obj.attr` (see comment in `visit_Delete` — clearing in a branch that doesn't always execute would be wrong as often as right). Same reasoning applies.

6. **Pass timing.** Recognition runs idempotently in both passes — no `current_pass` attribute, no gating. Pass 1 catches the common case (imports typically precede bindings in source order); pass 2 corrects any forward-import edge cases. `get_node` is idempotent, scope `defs[k] = v` is overwrite-with-same-value, defines edges deduplicate. The simplicity wins over a more controlled split.

## Scope and non-goals

Out of scope for this work — degrades to #127's module-level fallback, which is the right floor:

- **Factory-returned namespaces** (`config = make_config()` where `make_config` returns an env). Requires return-value type tracking. Big.
- **Splat construction** (`env(**kwargs)`). Kwargs not statically visible.
- **Genuinely dynamic writes** (`for k, v in source.items(): setattr(config, k, v)`, or `config.__dict__[k] = v`). The `setattr` form is covered when `k` is a literal string, a name bound to a string literal, or an imported name resolving to one — see point 5 in PR 2. Anything beyond that (loop variables, function-returned strings, computed strings) requires data-flow analysis — out of scope by design for a static analyzer.
- **Aliasing through function returns / parameter passing / container indexing.** Pyan already shares Nodes across direct name aliasing (`f = e`); deeper data-flow tracking is its own large project.

For each of these, #127's fallback continues to emit the module-level edge, which is honest about what static analysis can know.

## Walrus and other corners

- `(obj.attr := v)` is a `SyntaxError` per PEP 572 — walrus targets are restricted to `Name`. No attribute-walrus path to handle.
- `(config := env(thingy=baa))` is legal walrus (`Name := Call`) and routes through `visit_NamedExpr`.
- Context-manager construction (`with env(thingy=baa) as e:`) registers identically to assignment. The runtime lifecycle differences between constructors (`unpythonic.env.env` clears bindings on scope exit; `SimpleNamespace` and `argparse.Namespace` don't even implement the CM protocol) are flow-sensitive concerns out of scope for a static analyzer.

## Aliasing

Pyan already shares Nodes across name aliases — `f = e` makes both names resolve to the same Node. So `NAMESPACE_OBJECT` flavor and its populated scope are inherited by aliases for free, without any explicit alias-tracking code in this work.

## Test plan

- **PR 1**: regenerate expected graphs in `tests/test_features.py`, `tests/test_writers.py`, etc. for fixtures with module-level constants. Add a coverage test for `from mymod import CONSTANT` resolution. Verify that function-local bindings still don't create Nodes.
- **PR 2**:
  - Direct construction: `config = env(thingy=baa); use config.thingy` resolves to `baa`'s Node, no module-level fallback.
  - Cross-module: separate-module fixture with `config = env(...)`, consumer doing `from app_state import config; config.dataset` — verify the edge bypasses #127's fallback.
  - Staged form: `config = env(); config.a = baa` — point 4 picks up the later write.
  - `setattr` form, level 1: `config = env(); setattr(config, "a", baa)` — literal-string write.
  - `setattr` form, level 2: `k = "a"; setattr(config, k, baa)` — name-bound literal in same scope.
  - `setattr` form, level 3: cross-module fixture with `KEY = "a"` in one module, `setattr(config, KEY, baa)` in another after `from constants import KEY`.
  - `setattr` form, negative: `for k in keys: setattr(config, k, baa)` — loop-bound key, confirming graceful no-op.
  - Walrus: `(config := env(thingy=baa))`.
  - Context manager: `with env(thingy=baa) as e:` body uses `e.thingy`.
  - Negative: factory-returned `config = make_config()` should still hit #127's fallback (regression guard against over-firing).
  - CLI: `--namespace-constructor my.custom.NS` with corresponding fixture, plus the stderr-nudge test.
  - All four constructors in the built-in registry (env, SimpleNamespace, argparse.Namespace, top-level `unpythonic.env`) get at least one fixture each.

## Cross-references

- Predecessor: #127 (module-level fallback for unresolvable attribute access).
- Tracking issue: #129.
- Touches: `pyan/analyzer.py`, `pyan/anutils.py`, `pyan/node.py`, `pyan/visgraph.py` (NAME-Node suppression), `pyan/main.py` (CLI option), tests under `tests/`.
