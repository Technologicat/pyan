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
- **D13: Per-anonymous-scope isolation**: Multiple comprehensions or lambdas in the same function share one scope key (e.g. `"module.func.listcomp"`, `"module.func.<lambda>"`). This is the same on both pre-3.12 (last symtable child wins) and 3.12+ (synthetic scope shared). Would need numbered keys to isolate each scope's bindings — applies to both comprehensions and lambdas. **Note (3.12+ symtable quirk):** PEP 709 inlines comprehensions — `symtable` no longer reports child scopes for them, and comprehension iteration variables appear in the parent function's `get_identifiers()` as `local=True, assigned=True`, indistinguishable from real locals. The existing `Scope.from_names()` synthetic scopes handle variable isolation during analysis, so the ghost entries in the parent scope's `defs` are currently benign (`None` values, never updated outside the synthetic scope). But this needs proper attention when implementing numbered comprehension scopes — the parent scope's `defs` shouldn't include comprehension-only variables on 3.12+. NOTE: When resolved, update the symtable caveat in CLAUDE.md.
- **D14: "Node" terminology overload**: Three concepts share the name "node": (1) AST node (`ast.AST`), (2) Pyan's analysis graph node (`Node` class), (3) visualization/output node. Check whether all three are still conflated and consider introducing distinct terminology to reduce confusion. NOTE: When resolved, update the terminology overload caveat in CLAUDE.md.
- **D15: modvis multi-project coloring**: When analyzing files from several projects in one run, hue could be decided by the top-level directory name (after `./` if any), and lightness by depth in each tree. This would match how the call-graph analyzer colors functions/classes. Currently all modules are colored by their immediate package directory.
- **D17: README example graph**: ✓ Done. Synthetic orbital mechanics example in `tests/orbital/` (3 modules: orbits, bodies, mission). Demonstrates uses edges, self-recursion (`TransferOrbit.refine`), mutual recursion (`converge_anomaly` ↔ `refine_anomaly`), HSL coloring (3 hues), nesting-depth lightness, and namespace grouping. Generated with `--uses --no-defines --colored --grouped --nested-groups --namespace orbital`.
- **D18: Edge confidence scoring**: Determine confidence of detected edges (probability that the edge is correct). See also [DESIGN-NOTES.md](DESIGN-NOTES.md).
- **D19: Improved wildcard resolution**: Improve the mechanism for resolving `*.name` wildcards. See discussion at [johnyf/pyan#5](https://github.com/johnyf/pyan/issues/5).
- **D20: Type inference for function arguments**: Would reduce wildcard noise by allowing the analyzer to resolve argument types at call sites.
- **D21: Prefix methods by class name in graph**: When grouping is off, method nodes show only the bare name. Prefix with class name for clarity. Also consider a legend for annotations. See discussion at [johnyf/pyan#4](https://github.com/johnyf/pyan/issues/4).
- **D22: Tuples/lists as first-class values**: Assigning a tuple/list to a single name (e.g. `x = [a, b, c]`) overapproximates: `x` is bound to all of `a`, `b`, `c` via the Cartesian fallback. This is sound but imprecise — tracking which index maps to which value would require flow-sensitive analysis.
- **D23: Subscript assignment**: Slicing and indexing in assignment targets (`ast.Subscript`) — binding information is not recorded.
- **D24: Additional unpacking generalizations (PEP 448)**: E.g. `{**a, **b}`, `[*a, *b]`. Uses on the RHS are detected, but binding information is not recorded.
- **D25: Enum attribute tracking**: Need to mark uses of Enum member attributes as uses of the Enum class itself.
- **D26: Resolving function call results**: The analyzer does not track the return type of function calls, except for a limited special case for `super()`.
- **D27: Directional graph filtering (`filter_up`/`filter_down`)**: ✓ Done (`1e096ec`). `--direction up/down/both` CLI flag and `direction` API parameter. Reverse-edge BFS traversal in `get_related_nodes()`. Five tests.
- **D28: Per-namespace `resolve_imports`**: `resolve_imports` currently remaps IMPORTEDITEM nodes globally. A function-level import can leak to sibling functions via this path. `expand_unknowns` already has per-namespace import scoping (via `_has_import_to`), which mitigates the worst effects — but `resolve_imports` running first can still resolve a sibling's wildcard as a side effect of `add_uses_edge`'s wildcard-removal mechanism. Impact is minor (over-approximation, not under-approximation).
- **D29: Document the visitor-to-visgraph protocol**: `VisualGraph.from_visitor` expects `visitor.nodes` (dict of name → list of Nodes), `visitor.uses_edges` and `visitor.defines_edges` (dict of Node → set of Nodes). This is an implicit protocol shared by `CallGraphVisitor` and `ImportVisitor.prepare_graph()`, but neither side documents it. The "same format as in analyzer" comment in `prepare_graph` should be replaced with a proper docstring or protocol class.
