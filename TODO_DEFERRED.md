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
- **D8: Iterator protocol tracking + `is_async`**: We already track the context manager protocol (`__enter__`/`__exit__` for `with`). Tracking the iterator protocol (`__iter__`/`__next__`) would be a natural addition — and would make `analyze_comprehension`'s ignored `ast.comprehension.is_async` field relevant too (`__aiter__`/`__anext__` vs `__iter__`/`__next__`).
- **D9: modvis `filename_to_module_name` cwd fragility**: ✓ Done (`c9cc075`+`a310477`). Added `root` parameter to `filename_to_module_name`, `ImportVisitor`, `create_modulegraph`, and CLI `--root`. Root is inferred by default (walk up past `__init__.py` dirs).
- **D10: `visit_Name` local variable noise**: When a local has no known value, a wildcard `UNKNOWN`-flavored node is created (analyzer.py:721–725). The existing TODO suggests skipping node creation for locals in the innermost scope — would reduce graph noise and postprocessor cleanup work.
- **D11: Plain-text output**: ✓ Done (`d2a5b6a`). `TextWriter` added to `writers.py`; `--text` CLI flag and `"text"` format for both call-graph and module-level modes. Old commented-out plaintext code removed from modvis.

## Large

- **D12: Tuple unpacking with `Starred`**: `analyze_binding` (analyzer.py:1106–1112) overapproximates when target/value counts don't match — each target gets every RHS value. Could do positional matching for the non-starred targets (e.g. `a, b, *c = x, y, z, foo, bar` → bind `a=x`, `b=y`, `c={z, foo, bar}`). The architecture supports it; `_bind_target` already recurses into `Starred`.
- **D13: Per-comprehension scope isolation**: All listcomps (or setcomps, etc.) in the same function share one scope key (e.g. `"module.func.listcomp"`). This is the same on both pre-3.12 (last symtable child wins) and 3.12+ (synthetic scope shared). Would need numbered keys to isolate each comprehension's bindings.
- **D14: "Node" terminology overload**: Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Check whether all three are still conflated and consider introducing distinct terminology to reduce confusion.
- **D15: modvis multi-project coloring**: When analyzing files from several projects in one run, hue could be decided by the top-level directory name (after `./` if any), and lightness by depth in each tree. This would match how the call-graph analyzer colors functions/classes. Currently all modules are colored by their immediate package directory.
- **D17: README example graph**: The current `graph0.svg` (generated from `pyan.modvis`) is realistic but visually cluttered for a front-page showcase. Replace with a synthetic multi-file example designed to demonstrate the features described in the README's "About" section: uses edges (including recursion and mutual recursion), HSL node coloring (hue by file, lightness by nesting depth), translucent fills, and grouping. Recursion should be visible as a self-loop (A→A), and mutual recursion as a pair of arrows (B→C, C→B). Use meaningful names — no `foo`/`bar`. Omit defines edges — they add noise without aiding first impression. Keep the synthetic source files in the repo (e.g. `examples/`) so the graph is reproducible.
