# Deferred Issues

## Small

- **D1: Rename `sanitize_exprs` → `canonize_exprs`**: ✓ Done (`38fffd0`).
- **D2: `resolve()` keyword-only params**: ✓ Done (`a402739`).
- **D3: Unify output format support**: ✓ Done (`600f724`).
- **D4: README badges**: ✓ Done (`6f48a78`).
- **D5: Sphinx extension verification**: ✓ Done (`4d1e196`). Smoke tests added; typo fix.
- **D16: Review flake8 warnings (W503, E203, E741)**: ✓ Done (`1af4e31`..`9c9c45c`). W503/E203 added to ignore list; E741 renamed; F401/F841 tagged in test fixtures; unused Path import removed. Zero warnings.

## Medium

- **D6: README: document `--module-level` mode**: ✓ Done (`831f31c`). Also added --svg/--html to modvis CLI.
- **D7: `Del` context tracking**: ✓ Done. `visit_Delete` tracks `__delattr__` for `del obj.attr` and `__delitem__` for `del obj[key]`. Bare `del name` is a no-op (just unbinds). Three tests added.
- **D8: Iterator protocol tracking + `is_async`**: ✓ Done. `_add_iterator_protocol_edges()` adds `__iter__`/`__next__` (or `__aiter__`/`__anext__` when async) for `for`, `async for`, and comprehension generators. The `is_async` field on `ast.comprehension` is now used. Three tests added.
- **D9: modvis `filename_to_module_name` cwd fragility**: ✓ Done (`c9cc075`+`a310477`). Added `root` parameter to `filename_to_module_name`, `ImportVisitor`, `create_modulegraph`, and CLI `--root`. Root is inferred by default (walk up past `__init__.py` dirs).
- **D10: `visit_Name` local variable noise**: ✓ Done. `Scope` now tracks a `locals` set (assigned, not imported/global/free). `visit_Name` skips UNKNOWN node creation when the name is a local with no resolved value — eliminates spurious wildcard edges for loop counters, temporaries, etc. One test added.
- **D11: Plain-text output**: ✓ Done (`d2a5b6a`). `TextWriter` added to `writers.py`; `--text` CLI flag and `"text"` format for both call-graph and module-level modes. Old commented-out plaintext code removed from modvis.

## Large

- **D12: Tuple unpacking with `Starred`**: ✓ Done. `analyze_binding` now does positional matching when the LHS has exactly one starred target: non-starred targets bind to their positional counterparts, starred target to the remainder. Cartesian fallback for ambiguous cases (no star, multiple stars, too few values). Three tests added.
- **D13: Per-comprehension scope isolation**: All listcomps (or setcomps, etc.) in the same function share one scope key (e.g. `"module.func.listcomp"`). This is the same on both pre-3.12 (last symtable child wins) and 3.12+ (synthetic scope shared). Would need numbered keys to isolate each comprehension's bindings. **Note (3.12+ symtable quirk):** PEP 709 inlines comprehensions — `symtable` no longer reports child scopes for them, and comprehension iteration variables appear in the parent function's `get_identifiers()` as `local=True, assigned=True`, indistinguishable from real locals. The existing `Scope.from_names()` synthetic scopes handle variable isolation during analysis, so the ghost entries in the parent scope's `defs` are currently benign (`None` values, never updated outside the synthetic scope). But this needs proper attention when implementing numbered comprehension scopes — the parent scope's `defs` shouldn't include comprehension-only variables on 3.12+.
- **D14: "Node" terminology overload**: Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Check whether all three are still conflated and consider introducing distinct terminology to reduce confusion.
- **D15: modvis multi-project coloring**: When analyzing files from several projects in one run, hue could be decided by the top-level directory name (after `./` if any), and lightness by depth in each tree. This would match how the call-graph analyzer colors functions/classes. Currently all modules are colored by their immediate package directory.
- **D17: README example graph**: The current `graph0.svg` (generated from `pyan.modvis`) is realistic but visually cluttered for a front-page showcase. Replace with a synthetic multi-file example designed to demonstrate the features described in the README's "About" section: uses edges (including recursion and mutual recursion), HSL node coloring (hue by file, lightness by nesting depth), translucent fills, and grouping. Recursion should be visible as a self-loop (A→A), and mutual recursion as a pair of arrows (B→C, C→B). Use meaningful names — no `foo`/`bar`. Omit defines edges — they add noise without aiding first impression. Keep the synthetic source files in the repo (e.g. `examples/`) so the graph is reproducible.
