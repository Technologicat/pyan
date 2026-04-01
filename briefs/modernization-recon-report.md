# Pyan3 Reconnaissance Report

**Date**: 2026-02-17
**Scope**: Analysis of pyan3 codebase for Python 3.10–3.14 modernization
**Status**: Recon only — no code changes

---

## 1. Architecture Overview

### Module map

```
__main__.py (6 lines)
    └→ pyan.main()

__init__.py (119 lines) — Public API: create_callgraph()
    ├→ analyzer.CallGraphVisitor
    ├→ visgraph.VisualGraph
    └→ writers.{DotWriter, HTMLWriter, SVGWriter}

main.py (247 lines) — CLI: argparse, file discovery, orchestration
    ├→ analyzer.CallGraphVisitor
    ├→ visgraph.VisualGraph
    └→ writers.{DotWriter, HTMLWriter, SVGWriter, TgfWriter, YedWriter}

analyzer.py (1764 lines) — Core: AST visitor, two-pass analysis
    ├→ anutils.{Scope, ExecuteInInnerScope, resolve_method_resolution_order, ...}
    └→ node.{Node, Flavor}

anutils.py (287 lines) — Scope adaptor (wraps symtable), C3 MRO, AST helpers
    └→ node.Flavor

node.py (189 lines) — Node + Flavor enum (no internal deps)

visgraph.py (251 lines) — VisualGraph, Colorizer (no pyan imports)

writers.py (322 lines) — DotWriter, SVGWriter, HTMLWriter, TgfWriter, YedWriter
    └→ [external: jinja2, subprocess for graphviz]

sphinx.py (171 lines) — Sphinx directive (optional)
    └→ __init__.create_callgraph
    └→ [external: sphinx, docutils — UNDECLARED]
```

### Data flow

```
Python source files (.py)
    │
    ▼
CallGraphVisitor (analyzer.py)
  ├─ analyze_scopes() — symtable-based scope extraction
  ├─ Pass 1: visit_*() methods → build nodes, defines_edges, uses_edges
  ├─ resolve_base_classes() + compute MRO
  ├─ Pass 2: re-traverse with full type info (forward refs resolved)
  └─ postprocess(): expand_unknowns → resolve_imports → contract_nonexistents
                     → cull_inherited → collapse_inner
    │
    ▼
VisualGraph.from_visitor() (visgraph.py)
  ├─ Colorize (HSL: hue=namespace, lightness=depth)
  ├─ Create VisualNode/VisualEdge objects
  └─ Build subgraph groupings
    │
    ▼
Writer.run() (writers.py)
  └─ .dot / .svg / .html / .tgf / .graphml
```

### Key data structures

- **`Node`**: `(namespace, name, ast_node, filename, flavor, defined)`. Namespace is a dotted path; name is the local identifier.
- **`Flavor`** enum with specificity scoring: `UNSPECIFIED(0) < NAMESPACE/ATTRIBUTE(1) < IMPORTEDITEM(2) < MODULE/CLASS/FUNCTION/METHOD/...(3)`. Higher specificity overwrites lower during analysis.
- **`Scope`**: Wraps `symtable.SymTable`. Has `defs` dict mapping identifiers to Nodes.
- **`defines_edges`**: `Dict[Node, Set[Node]]` — structural containment (module→class, class→method).
- **`uses_edges`**: `Dict[Node, Set[Node]]` — references/calls.

---

## 2. AST Node Usage Audit

### Visitor methods (21 total, all in analyzer.py)

| Visitor | Line | Purpose |
|---------|------|---------|
| `visit_Module` | 332 | Top-level entry per file |
| `visit_ClassDef` | 352 | Class definitions |
| `visit_FunctionDef` | 396 | Function definitions |
| `visit_AsyncFunctionDef` | 465 | Async function definitions |
| `visit_Lambda` | 468 | Lambda expressions |
| `visit_Import` | 525 | `import` statements |
| `visit_ImportFrom` | 534 | `from ... import` statements |
| `visit_Constant` | 626 | Literal constants (Python 3.8+) |
| `visit_Attribute` | 634 | Attribute access (`obj.attr`) |
| `visit_Name` | 718 | Identifiers |
| `visit_Assign` | 747 | Assignment statements |
| `visit_AnnAssign` | 772 | Annotated assignment (`x: int = 5`) |
| `visit_AugAssign` | 793 | Augmented assignment (`x += 1`) |
| `visit_For` | 818 | `for` loops (binding) |
| `visit_AsyncFor` | 830 | `async for` loops |
| `visit_ListComp` | 833 | List comprehensions |
| `visit_SetComp` | 837 | Set comprehensions |
| `visit_DictComp` | 841 | Dict comprehensions |
| `visit_GeneratorExp` | 845 | Generator expressions |
| `visit_Call` | 887 | Function/method calls |
| `visit_With` | 938 | Context managers |

### isinstance checks for AST types

- `ast.Store`, `ast.Load` — context checks in `visit_Attribute` and `visit_Name`
- `ast.Name`, `ast.Attribute` — node type validation in several resolution methods
- `ast.Call`, `ast.FunctionDef`, `ast.AsyncFunctionDef` — type checks in helpers
- `ast.Tuple`, `ast.List` — in `sanitize_exprs()` (anutils.py)
- `ast.alias` — in `format_alias()` (anutils.py)

### Critical: deprecated AST node usage

**`analyzer.py:1203`** — inside `resolve_attribute()`:
```python
if isinstance(ast_node.value, (ast.Num, ast.Str)):  # TODO: other types?
```

- `ast.Num` and `ast.Str` were **deprecated in 3.8**, **removed in 3.14**.
- On 3.8–3.13: this check is *dead code* — the parser produces `ast.Constant` nodes, so the isinstance never matches. The equivalent logic already exists in `visit_Constant` (line 626–631).
- On 3.14: **crashes with `AttributeError`** because `ast.Num` and `ast.Str` no longer exist.
- Fix: replace with `isinstance(ast_node.value, ast.Constant)`.

No other uses of `ast.Num`, `ast.Str`, `ast.Bytes`, `ast.NameConstant`, `ast.Ellipsis`, `ast.Index`, or `ast.ExtSlice` were found.

### Missing visitors for Python 3.8–3.14 syntax

| Syntax | Python | AST node | Call graph impact | Priority |
|--------|--------|----------|-------------------|----------|
| Walrus `:=` | 3.8 | `NamedExpr` | Binding semantics lost; calls in RHS still found via `generic_visit` | Medium |
| `match`/`case` | 3.10 | `Match`, `MatchClass`, etc. | `MatchClass` references classes (uses edge missed); guard exprs and case bodies work via `generic_visit` | Medium |
| `except*` | 3.11 | `TryStar` | No impact — structurally identical to try/except for call graph; handler bodies traverse normally | None |
| `type` alias | 3.12 | `TypeAlias` | Alias name not tracked; RHS type references traverse normally | Low |
| Type params | 3.12 | `TypeVar`, `ParamSpec`, `TypeVarTuple` (scoped) | Bound expressions traverse normally | Low |
| `TypeVar` default | 3.13 | field on `TypeVar` | Just an expression; traverses normally | None |
| t-strings | 3.14 | `TemplateStr`, `Interpolation` | Same as f-strings — interpolated expressions traverse normally | None |

**Bottom line**: `NamedExpr` and `Match` are the only ones that need explicit visitors for correct call graph analysis. The rest are either no-ops or adequately handled by `generic_visit`.

### Not visited by design (correct for call graph analysis)

Control flow (`If`, `While`, `Try`, `Return`, `Raise`, etc.), operators (`BinOp`, `UnaryOp`, `BoolOp`, `Compare`), data structures (`Dict`, `Set`, `Subscript`), expressions (`IfExp`, `Yield`, `Await`), and f-strings (`JoinedStr`, `FormattedValue`). All of these are correctly handled by `generic_visit` — their sub-expressions (which may contain calls) are traversed automatically.

---

## 3. `last_value` Mechanism

### What it is

A single `Node`-valued instance attribute (`self.last_value`) on `CallGraphVisitor`, initialized to `None`. Acts as a depth-0 implicit return channel between visitor methods: one visitor sets it, the next reads it. There is no stack, no branching, no union — just the most recently written value.

### What question it answers

**"What was the result of the most recently visited RHS expression?"**

Concrete use cases:
1. **Assignment binding** (`analyze_binding`, line 1036): visit RHS → capture `last_value` → visit LHS targets in Store context → `set_value(name, last_value)`.
2. **Class instantiation detection** (`visit_Call`, line 928): after visiting the callee expression, if `last_value` is a known class Node, emit a uses edge to `ClassName.__init__`.
3. **Attribute assignment** (`visit_Attribute` in Store context, line 644): propagate `last_value` to `set_attribute()`.
4. **Decorator capture** (`analyze_functiondef`, line 1002): after visiting a decorator expression, read `last_value` to get the decorator node.
5. **Context manager binding** (`visit_With`, line 960): after visiting the `with` expression, read `last_value` to find what object is being managed.
6. **Comprehension target binding** (`analyze_comprehension`, line 870): visit iterator → capture `last_value` → bind to target variable.

### Where it lives (27 reference sites)

| Role | Locations |
|------|-----------|
| **Init** | `__init__:82` |
| **Write** | `visit_Constant:631`, `visit_Attribute:676,711`, `visit_Name:745`, `visit_Call:903`, `analyze_binding:1077`, `anutils.ExecuteInInnerScope.__exit__:287` |
| **Read** | `visit_Attribute:645`, `visit_Name:726`, `visit_Call:928,930`, `visit_With:960`, `analyze_functiondef:1002`, `analyze_binding:1074` |
| **Reset** | `visit_Module:347`, `visit_AnnAssign:774,788`, `analyze_comprehension:871`, `visit_With:958,961`, `analyze_functiondef:998,1005`, `analyze_binding:1044,1075,1079,1086` |

### How deeply wired in

Deeply. Removing it breaks:
- All assignment tracking (simple, annotated, augmented)
- Class instantiation edge detection
- Attribute store handling
- Decorator analysis
- Context manager analysis
- Comprehension target binding

### Correctness issues

| Problem | Severity | Example |
|---------|----------|---------|
| **Branches**: single value, not per-path | High | `if c: x = A() else: x = B()` → only B survives |
| **Non-trivial tuple unpacking** | High | `a, b = f(), g()` when count mismatches → all targets get last value (acknowledged FIXME at line 1080) |
| **Comprehension target binding** | Medium | Iterator → target binding is approximate |
| **Loops**: visited once, not iterated | Medium | Loop body binding reflects single visit |
| **Exception handlers**: `as` binding not tracked | Medium | `except E as e:` — no `visit_ExceptHandler` |

The code itself calls it a hack in two TODO comments (lines 640, 721), and proposes the fix: move all Store-context handling into `analyze_binding()`, making `visit_Attribute` and `visit_Name` load-only.

### What a replacement would look like

The `last_value` hack answers a single-valued question where the honest static answer is set-valued. A proper replacement:

1. **Minimal fix**: Replace `self.last_value` with `self.last_values: List[Node]`, collecting all possible RHS bindings and creating edges for all of them. This is a "set of all bindings in scope" approach — honest overapproximation.

2. **Better fix**: Restructure so that `analyze_binding()` directly receives the RHS Node(s) as arguments rather than communicating through shared mutable state. The visitor methods for Load context would return their resolved Node instead of stashing it in a side channel.

3. **Full fix**: Points-to analysis (tracking which names can point to which objects across all paths). Almost certainly overkill for a call graph tool — the overapproximation from (1) or (2) would be plenty useful and much simpler.

Recommendation: option (2) — explicit argument passing in `analyze_binding()` with multi-valued support. It's the refactoring the existing TODO comments already describe. **Decision: confirmed, do this after compatibility fixes.**

---

## 4. `modvis.py` Characterization

### What it does

Module-level import dependency analysis. Maps which modules import which other modules, detects import cycles, visualizes as directed graph. Complementary to the main analyzer's function-level call graph.

### How it differs from the main analyzer

| Aspect | `modvis.py` | `analyzer.py` |
|--------|-------------|---------------|
| Granularity | Module-level | Function/class/method-level |
| Edge types | Uses only (imports) | Defines + Uses |
| Node flavors | `MODULE` only | Full Flavor set |
| Analysis passes | Single pass | Two passes |
| Scope tracking | None | Full scope stack + symtable |
| MRO | N/A | C3 linearization |

### Implementation

- Own `ImportVisitor(ast.NodeVisitor)` — visits only `Import` and `ImportFrom` nodes.
- Resolves relative imports to fully-qualified names.
- Adds synthetic edges for implicit `__init__.py` dependencies.
- Detects and reports import cycles (DFS with cycle length statistics).
- Uses `optparse` (deprecated, not removed — still works but should migrate to `argparse`).

### Shared infrastructure

Already uses `pyan.node`, `pyan.visgraph`, `pyan.writers` — same output pipeline as the main analyzer. Does NOT import `pyan.analyzer`.

### Integration path

Straightforward:
1. Migrate `optparse` → `argparse`.
2. Add `--module-level` flag to main CLI.
3. Conditionally instantiate `ImportVisitor` vs `CallGraphVisitor`.
4. Both produce the same output types (nodes + uses_edges → VisualGraph → writers).

---

## 5. Import/Boot Issues

### `__version__` crash (HIGH)

`__init__.py:7`: `__version__ = version("pyan3")` — crashes with `PackageNotFoundError` when running from a dev checkout without `pip install -e .`.

Fix: wrap in try/except, fall back to reading version from `pyproject.toml` or hardcode `"dev"`.

### Undeclared Sphinx/docutils dependencies (MEDIUM)

`sphinx.py` imports `sphinx` and `docutils` — neither is declared in `pyproject.toml`. Safe in practice (sphinx.py is never imported by default), but should be declared as optional:

```toml
[project.optional-dependencies]
sphinx = ["sphinx>=3.0", "docutils>=0.12"]
```

### No other import-time issues found

- All stdlib imports are current.
- No conditional imports.
- No `__future__` imports needed (code doesn't use `annotations` PEP 563 style).

---

## 6. Dependency Audit

### Declared runtime deps

| Package | Used in | Status |
|---------|---------|--------|
| `jinja2` | `writers.py` (HTMLWriter template) | Needed, no version pin |
| `graphviz` | `writers.py` (SVGWriter pipes to `dot` subprocess) | **Misleading** — the `graphviz` PyPI package provides a Python API, but Pyan actually shells out to the `dot` binary via `subprocess`. The PyPI package isn't used. |

Note: The `graphviz` dependency should be verified — if the code only uses `subprocess.Popen(["dot", ...])` (which it does), then the `graphviz` PyPI package is unnecessary. The system `graphviz` binary is needed but can't be declared as a Python dependency.

### Python version metadata

- `requires-python = ">=3.9"` — should become `">=3.10"` (dropping 3.9).
- Classifiers list 3.9–3.12 — should add 3.13, 3.14 and remove 3.9.
- Ruff `target-version = "py39"` — should become `"py310"`.

---

## 7. Test Coverage Assessment

### Current state

`tests/test_analyzer.py`: 6 integration tests, 64 lines. Uses a single `callgraph` fixture that processes all files in `tests/test_code/`.

| Test | What it verifies |
|------|-----------------|
| `test_resolve_import_as` | `import X as Y` creates uses edge |
| `test_import_relative` | `from . import module` creates edge |
| `test_resolve_use_in_class` | Uses edge from class `__init__` |
| `test_resolve_use_in_function` | Function call creates uses edge |
| `test_resolve_package_without___init__` | Defines edges without `__init__.py` |
| `test_resolve_package_with_known_root` | Module naming with explicit root |

### Test data

`tests/test_code/`: Two subpackages with simple modules demonstrating imports, class definitions, function definitions. `tests/old_tests/`: Regression fixtures for issues #2 (annotated vars), #3 (nested comprehensions), #5 (relative imports) — **not wired into the test suite**.

### Critical gaps

1. **No unit tests on analyzer internals** — scope analysis, MRO, postprocessing are untested.
2. **No decorator tests** — `@staticmethod`, `@classmethod`, `@property`, custom decorators.
3. **No output format tests** — DOT/SVG/HTML generation untested.
4. **No Python 3.8+ syntax** — walrus operator, match statements, type aliases, f-strings in graph analysis.
5. **No edge cases** — empty files, syntax errors, circular imports, star imports, Unicode identifiers.
6. **Old test fixtures disconnected** — issues #2, #3, #5 have test data but no tests using them.

### Recommended approach

- Keep existing integration tests as regression baseline.
- Add parametrized unit tests per visitor method.
- Add test fixtures organized by Python version feature.
- Add output format smoke tests (DOT parses, SVG is valid XML, etc.).

---

## 8. Actionable Issue List

### Must fix — blocks running on 3.10–3.14

| # | Issue | Location | Effort |
|---|-------|----------|--------|
| M1 | `ast.Num`/`ast.Str` crash on 3.14 | `analyzer.py:1203` | Trivial — replace with `ast.Constant` check |
| M2 | `__version__` crash in dev mode | `__init__.py:7` | Trivial — try/except fallback |
| M3 | Drop Python 3.9 support | `pyproject.toml`, `__init__.py:9-20` | Small — update requires-python, classifiers, ruff target, remove 3.9 deprecation warning |
| M4 | Add Python 3.13/3.14 classifiers | `pyproject.toml:16-32` | Trivial |

### Should fix — needed for analyzing 3.8–3.14 code correctly

| # | Issue | Location | Effort |
|---|-------|----------|--------|
| S1 | Add `visit_NamedExpr` (walrus operator) | `analyzer.py` | Small — binding semantics similar to `visit_Assign` |
| S1b | Add `visit_AsyncWith` | `analyzer.py` | Small — same as `visit_With` but for `async with`; `as` binding currently not tracked |
| S2 | Add `visit_Match` + pattern visitors | `analyzer.py` | Medium — `MatchClass` needs class reference tracking; rest handled by `generic_visit` |
| S2b | Visit type annotations for uses edges | `analyzer.py` | Small — visit `node.annotation` in AnnAssign, `arg.annotation` in function args, `node.returns` in FunctionDef. Existing Load-context visitors handle the rest. |
| S3 | Declare sphinx/docutils as optional deps | `pyproject.toml` | Trivial |
| S4 | Drop `graphviz` PyPI dep; document system `graphviz` (`dot` CLI) requirement in README | `pyproject.toml`, `README.md` | Small — confirmed: only `subprocess.Popen(["dot", ...])` is used |
| S5 | Convert old crash demos into proper tests with assertions | `tests/` | Small — issue #2 (annotated assignment edges), #3 (nested comprehension traversal), #5 (relative imports, dotted-path imports). Input files exist; need pytest wrappers with edge assertions. Issue #5 `plot_xrd.py` also covers S2b (annotation uses edge to `meas_xrd.MeasXRD`). |
| S6 | Add basic test coverage for core analysis | `tests/` | Medium |

### Nice to have — improvements, not blocking

| # | Issue | Location | Effort |
|---|-------|----------|--------|
| N1 | Refactor `last_value` → explicit argument passing in `analyze_binding` | `analyzer.py` | Large — deep refactor, defer |
| N2 | Add `visit_TypeAlias` (Python 3.12 `type` statement) | `analyzer.py` | Small — mainly for completeness |
| N3 | Migrate `modvis.py` from `optparse` to `argparse` | `modvis.py` | Small |
| N4 | Integrate `modvis.py` as `--module-level` CLI mode | `main.py`, `modvis.py` | Medium |
| N5 | Fix tuple unpacking in non-trivial case | `analyzer.py:1080-1086` | Medium — acknowledged FIXME; roll into N1 (`last_value` redesign) as subtask |
| N6 | Deduplicate `create_callgraph()` vs `main()` | `__init__.py`, `main.py` | Medium — noted TODO at `__init__.py:33` |
| N7 | Add output format tests (DOT validity, SVG validity) | `tests/` | Small |
| N8 | Comprehensive test suite for decorators, comprehensions, async | `tests/` | Large |
| N9 | Add type annotations to stable layers (`node.py`, `anutils.py`, `visgraph.py`, `writers.py`) | `pyan/` | Medium |
| N10 | Add type annotations to `analyzer.py` | `analyzer.py` | Large — do during `last_value` refactor (N1) |

### Suggested order of attack

1. **M1–M4**: Boot fixes, metadata updates. One commit.
2. **S5**: Wire up old test fixtures as proper tests with assertions.
3. **S6**: Baseline test coverage for core analysis — regression baseline before new functionality.
4. **S1–S2, S1b, S2b**: New visitors (walrus, async with, match, annotations).
5. **S3–S4**: Dependency cleanup.
6. **N1+N5**: `last_value` redesign — separate phase, takes tuple unpacking with it.

---

## Appendix: Python AST changes relevant to Pyan3

### Python 3.8
- `ast.Constant` replaces `ast.Num`, `ast.Str`, `ast.Bytes`, `ast.NameConstant`, `ast.Ellipsis` (old nodes deprecated, still exist as aliases)
- `ast.NamedExpr` added (walrus operator)
- `ast.Constant.kind` field added (for `u"..."` string prefix)

### Python 3.9
- `ast.Index` and `ast.ExtSlice` deprecated (not used by Pyan)
- No new node types relevant to call graphs

### Python 3.10
- `ast.Match`, `ast.match_case`, and 8 pattern nodes added
- No removals

### Python 3.11
- `ast.TryStar` added (exception groups)
- No removals

### Python 3.12
- `ast.TypeAlias` added
- Type parameter scope nodes: `ast.TypeVar`, `ast.ParamSpec`, `ast.TypeVarTuple` (as scoped AST nodes, distinct from `typing` module)
- No removals

### Python 3.13
- AST constructor validation tightened — missing required fields emit `DeprecationWarning` (will be errors in 3.15). Pyan does not construct AST nodes manually (it only reads them), so this is not a concern.
- `ast.TypeVar` gains `default_value` field

### Python 3.14
- **`ast.Num`, `ast.Str`, `ast.Bytes`, `ast.NameConstant`, `ast.Ellipsis` REMOVED** (were deprecated since 3.8)
- `ast.Index`, `ast.ExtSlice` still present as deprecated stubs (deprecated since 3.9, removal version TBD — likely 3.15 or 3.16)
- Template strings (t-strings): `ast.TemplateStr`, `ast.Interpolation` added
