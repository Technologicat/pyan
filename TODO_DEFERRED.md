# Deferred Issues

Items with GitHub ticket numbers are tracked externally. The rest are internal notes.

## Open

### With GitHub tickets

- **D13: Per-anonymous-scope isolation** (#110): Multiple comprehensions or lambdas in the same function share one scope key. Would need numbered keys to isolate each scope's bindings. 3.12+ `symtable` quirk complicates this — see ticket for details.
- **D15: modvis multi-project coloring** (#111): Color by top-level directory, not immediate package. Would match call-graph analyzer's approach.
- **D21: Prefix methods by class name in graph** (#112): When grouping is off, method labels should include the class name for clarity.
- **D25: Enum attribute tracking** (#113): `Color.RED` should create a uses edge to the Enum class.

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

- **D30: README update for 2.2.0**: Update CLI examples and Python API examples in README to showcase new features: `--depth`, `--direction`, `--concentrate`, `--paths-from`/`--paths-to`, `--dot-ranksep`, `--graphviz-layout`, `--init`, directory input. Also update the feature list.

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
- **D27**: Directional graph filtering (`1e096ec`)
