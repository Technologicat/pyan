# Deferred Issues

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## Open

### With GitHub tickets

- **D13: Per-anonymous-scope isolation** (#110): Multiple comprehensions or lambdas in the same function share one scope key. Would need numbered keys to isolate each scope's bindings. 3.12+ `symtable` quirk complicates this — see ticket for details.

### Internal

- **D14: "Node" terminology overload**: Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Consider introducing distinct terminology.
- **D18: Edge confidence scoring**: Determine confidence of detected edges. See [DESIGN-NOTES.md](DESIGN-NOTES.md).
- **D19: Improved wildcard resolution**: Partly addressed by #88 fix (import-aware expansion). Remainder: see [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).
- **D20: Type inference for function arguments**: Would reduce wildcard noise by resolving argument types at call sites. Ambitious.
- **D22: Tuples/lists as first-class values**: `x = [a, b, c]` overapproximates via Cartesian fallback. Would need flow-sensitive analysis.
- **D23: Subscript assignment**: `ast.Subscript` in assignment targets — binding information not recorded.
- **D24: Additional unpacking generalizations (PEP 448)**: `{**a, **b}`, `[*a, *b]` — uses detected, bindings not recorded.
- **D26: Resolving function call results**: Return type tracking beyond the `super()` special case.
- **D28: Per-namespace `resolve_imports`**: Global IMPORTEDITEM remapping can leak function-level imports to siblings. Partially mitigated by `_has_import_to()` in `expand_unknowns`.
- **D29: Document the visitor-to-visgraph protocol**: `VisualGraph.from_visitor` expects an implicit protocol (`nodes`, `uses_edges`, `defines_edges`). Should be documented or formalized.

- **D30: README update for 2.2.0**: ✓ Done. Updated CLI examples, Python API examples, feature list, dev setup, and install sections for all 2.2.0 features. Removed dead links to nonexistent CONTRIBUTING.md and ROADMAP.md.
- **D31: Test suite organization**: Tests are spread across few modules (`test_features.py`, `test_regressions.py`, `test_modvis.py`, `test_writers.py`, `test_analyzer.py`, `test_sphinx.py`, `test_coverage.py`). Consider reorganizing by concern — e.g. separate CLI tests from unit tests, group by module under test.
- **D32: Analyzer module split**: `analyzer.py` is ~2200 lines. Consider splitting into submodules (e.g. visitors, postprocessing, scope handling) without changing the public API.
- **D33: Type annotations for pyan's own code**: Add type annotations to pyan's modules. The analyzer is the largest target (~2200 lines). Would improve IDE support and catch bugs.

## Done

- **D1**: Rename `sanitize_exprs` → `canonize_exprs` (`38fffd0`)
- **D2**: `resolve()` keyword-only params (`a402739`)
- **D3**: Unify output format support (`600f724`)
- **D4**: README badges (`6f48a78`)
- **D5**: Sphinx extension verification (`4d1e196`)
- **D6**: README: document `--module-level` mode (`831f31c`)
- **D7**: `Del` context tracking
- **D8**: Iterator protocol tracking + `is_async`
- **D9**: modvis `filename_to_module_name` cwd fragility (`c9cc075`)
- **D10**: `visit_Name` local variable noise
- **D11**: Plain-text output (`d2a5b6a`)
- **D12**: Tuple unpacking with `Starred`
- **D16**: Review flake8/ruff warnings (`1af4e31`..`9c9c45c`)
- **D17**: README example graph
- **D34**: Document recommended options in README
- **D27**: Directional graph filtering (`1e096ec`)

- **D35: Audit typing: abstract parameter types, concrete return types**: Parameters should use abstract types from `collections.abc` (`Mapping`, `Sequence`, `Iterable`) for widest-possible-accepted semantics. Return types should use concrete lowercase builtins (`tuple[int, int]`, `list[int]`, `dict[str, int]`) — PEP 585, Python 3.9+. The capitalized `typing` forms (`Dict`, `List`, `Tuple`) are deprecated aliases for the builtins and offer no extra width — avoid them. Audit existing type hints across the codebase for consistency. (Discovered during raven-cherrypick compare mode planning, 2026-03-30.)
