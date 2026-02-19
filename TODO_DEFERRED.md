# Deferred Issues

## Small

- **D1: Rename `sanitize_exprs` → `canonize_exprs`**: ✓ Done (`38fffd0`).
- **D16: Review flake8 warnings (W503, E203, E741)**: Decide whether to fix, suppress per-file with `# noqa`, or add to `flake8rc` ignore list. Currently ~5 instances across `analyzer.py`, `modvis.py`, and `test_writers.py`.
- **D2: `resolve()` keyword-only params**: `resolve("anything", "os.path", 0)` isn't self-documenting. Make `current_module`, `target_module`, and `level` keyword-only (or at least `level`) to force explicit call sites. Update all callers (in `ImportVisitor` and tests).
- **D3: Unify output format support**: `create_callgraph()` only supports dot/svg/html; `main()` also supports tgf/yed. Should support all formats from both entry points.
- **D4: README badges**: Add badges similar to `unpythonic`/`mcpyrate` (Python version, PyPI, etc.).
- **D5: Sphinx extension verification**: Verify the Sphinx extension still works with current Sphinx. (Optional deps now declared; functional test still needed.)

## Medium

- **D6: README: document `--module-level` mode**: Cover CLI usage (`pyan3 --module-level`), the `create_modulegraph()` API, cycle detection semantics (combinatorial explosion, most cycles harmless, etc.), and how it differs from the call-graph analyzer.
- **D7: `Del` context tracking**: Currently silently ignored (falls through the `ast.Load` guard) in `visit_Attribute`/`visit_Name`. Could track `__delattr__`/`__del__` protocol calls for completeness, similar to how `__enter__`/`__exit__` are tracked for `with`.
- **D8: Iterator protocol tracking + `is_async`**: We already track the context manager protocol (`__enter__`/`__exit__` for `with`). Tracking the iterator protocol (`__iter__`/`__next__`) would be a natural addition — and would make `analyze_comprehension`'s ignored `ast.comprehension.is_async` field relevant too (`__aiter__`/`__anext__` vs `__iter__`/`__next__`).
- **D9: modvis `filename_to_module_name` cwd fragility**: Converts file paths to dotted module names by simple string manipulation relative to cwd. Absolute paths or wrong cwd produce incorrect names, breaking relative import resolution downstream. Could accept an explicit `root` parameter (like the call-graph analyzer does) and strip the root prefix before conversion.
- **D10: `visit_Name` local variable noise**: When a local has no known value, a wildcard `UNKNOWN`-flavored node is created (analyzer.py:721–725). The existing TODO suggests skipping node creation for locals in the innermost scope — would reduce graph noise and postprocessor cleanup work.
- **D11: modvis plain-text output**: Commented-out plaintext report in `main()` would show spurious deps (speculative `__init__` and submodule entries) because it reads raw `self.modules` instead of going through `prepare_graph()` which filters to analyzed-set-only. Fix: always go through `prepare_graph`, use the filtered graph for any output format including plaintext. Also consider adding plain-text output for the call-graph analyzer (D3).

## Large

- **D12: Tuple unpacking with `Starred`**: `analyze_binding` (analyzer.py:1106–1112) overapproximates when target/value counts don't match — each target gets every RHS value. Could do positional matching for the non-starred targets (e.g. `a, b, *c = x, y, z, foo, bar` → bind `a=x`, `b=y`, `c={z, foo, bar}`). The architecture supports it; `_bind_target` already recurses into `Starred`.
- **D13: Per-comprehension scope isolation**: All listcomps (or setcomps, etc.) in the same function share one scope key (e.g. `"module.func.listcomp"`). This is the same on both pre-3.12 (last symtable child wins) and 3.12+ (synthetic scope shared). Would need numbered keys to isolate each comprehension's bindings.
- **D14: "Node" terminology overload**: Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Check whether all three are still conflated and consider introducing distinct terminology to reduce confusion.
- **D15: modvis multi-project coloring**: When analyzing files from several projects in one run, hue could be decided by the top-level directory name (after `./` if any), and lightness by depth in each tree. This would match how the call-graph analyzer colors functions/classes. Currently all modules are colored by their immediate package directory.
