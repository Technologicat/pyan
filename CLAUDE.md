# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Pyan3

Static call graph generator for Python 3. Takes one or more Python source files, performs superficial static analysis, and constructs a directed graph of how objects define or use each other. GPL-2.0-or-later.

Two analysis modes:
- **Call graph** (`create_callgraph`): function/method/class-level edges (defines + uses).
- **Module graph** (`create_modulegraph`): module-level import dependencies with cycle detection.

Single dependency: `jinja2` (used only for HTML output). Optional: `sphinx`/`docutils` for the Sphinx extension.

## Build and Development

Uses hatchling. Python 3.10–3.14. Linter is ruff (not flake8).

```bash
pip install -e .[test]   # editable install with test deps
```

Entry point: `pyan3` CLI.

### Running Tests

```bash
pytest                   # runs all tests (pytest-cov configured in pytest.ini)
```

Tests in `tests/`: `test_features.py` (syntax coverage), `test_modvis.py` (module graph), `test_writers.py` (output formats), `test_analyzer.py` (low-level), `test_regressions.py`, `test_sphinx.py`. Version-specific tests in `tests/test_code_312/` (3.12+ syntax).

### CI

GitHub Actions: test matrix across 3.10–3.14 (`.github/workflows/tests.yml`), coverage via codecov (`.github/workflows/coverage.yml`).

### Linting

```bash
# ruff (configured in pyproject.toml)
ruff check .
```

Legacy `flake8rc` also present (used by CI for fatal-error-only pass).

## Architecture

### Pipeline: Source → Graph → Output

```
source files → CallGraphVisitor (analyzer.py) → Node graph → VisualGraph (visgraph.py) → Writer (writers.py) → output
```

### Modules

- **`analyzer.py`** (~1970 lines) — The core: `CallGraphVisitor`, an `ast.NodeVisitor` subclass. Two-pass analysis:
  - Pass 1: visit all files, collect definitions, uses, scopes, class bases.
  - Between passes: resolve base classes → compute MRO.
  - Pass 2: visit all files again, resolving forward references using pass-1 knowledge.
  - Postprocess: expand wildcards, resolve imports, contract nonexistent refs, cull inherited edges, collapse inner scopes.

- **`anutils.py`** (~315 lines) — Analyzer utilities:
  - `Scope` — Tracks names, bindings, and scope type (module/class/function/comprehension). Built from `symtable` analysis. Has `defs` dict mapping names to `Node` or `None`.
  - `ExecuteInInnerScope` — Context manager for entering/leaving scopes during analysis.
  - `get_module_name`, `format_alias`, `get_ast_node_name`, `canonize_exprs` — AST helpers.
  - `resolve_method_resolution_order` — C3 linearization for class hierarchies.

- **`node.py`** (~190 lines) — `Node` class and `Flavor` enum. A `Node` represents one named entity in the analyzed code (function, class, method, module, namespace, etc.). Has `namespace`, `name`, `flavor`, `defined`, and associated AST node. The `Flavor` enum distinguishes: `MODULE`, `CLASS`, `FUNCTION`, `METHOD`, `STATICMETHOD`, `CLASSMETHOD`, `NAME`, `ATTRIBUTE`, `IMPORTEDITEM`, `NAMESPACE`, `UNKNOWN`, `UNSPECIFIED`.

- **`visgraph.py`** (~250 lines) — `VisualGraph`: format-agnostic output graph. Filters edges (defines/uses), groups by namespace, applies coloring (HSL: hue = file, lightness = nesting depth). `Colorizer` handles the HSL assignment.

- **`writers.py`** (~355 lines) — Output format writers, all subclassing `Writer`:
  - `DotWriter` — GraphViz DOT format.
  - `SVGWriter(DotWriter)` — Pipes DOT through `dot` to produce SVG.
  - `HTMLWriter(SVGWriter)` — Interactive HTML (embeds SVG via Jinja2 template `callgraph.html`).
  - `TgfWriter` — Trivial Graph Format (for yEd).
  - `YedWriter` — yEd GraphML.
  - `TextWriter` — Plain-text dependency list.

- **`modvis.py`** (~570 lines) — Module-level import analysis. `ImportVisitor` (separate `ast.NodeVisitor`) finds import statements. `create_modulegraph()` builds a module dependency graph. Includes import cycle detection. Can also be run as a CLI mode via `pyan3 --module-level`.

- **`main.py`** (~380 lines) — CLI entry point and `create_callgraph()` API. Argument parsing, glob expansion, output format dispatch.

- **`sphinx.py`** (~170 lines) — Sphinx extension providing `.. callgraph::` directive for embedding call graphs in documentation.

- **`callgraph.html`** — Jinja2 template for interactive HTML output (pan/zoom SVG viewer).

### Key Design Decisions

**Two-pass analysis**: Forward references are common in Python (function A calls function B defined later in the file). Pass 1 collects everything; pass 2 resolves references that couldn't be resolved in pass 1. Base class resolution happens between passes so that inherited methods are available in pass 2.

**Scope tracking via `symtable`**: The analyzer uses Python's own `symtable` module to determine scope structure, then builds `Scope` objects that track name bindings during the visitor walk. This is more reliable than trying to reimplement Python's scoping rules. **3.12+ caveat**: PEP 709 inlines comprehensions, so `symtable` no longer reports them as child scopes. The analyzer works around this by creating synthetic scopes via `Scope.from_names()`, populated with iteration target names extracted from the AST. This preserves variable isolation but all comprehensions in a function currently share one scope key (see D13 in `TODO_DEFERRED.md`).

**Node naming**: Nodes are named by their fully qualified dotted path (e.g. `module.Class.method`). The `name_stack` tracks the current namespace context during the walk.

**"Node" terminology overload**: The codebase uses "node" for three different things: AST nodes (`ast.AST`), analysis graph nodes (`Node` class), and visualization output nodes. This is a known issue (D14 in `TODO_DEFERRED.md`).

**Wildcard resolution**: When a name can't be resolved, it becomes `*.name` (a wildcard). Postprocessing expands wildcards against known names, then removes references to entities outside the analyzed file set.

## Existing Reference Files

- `DESIGN-NOTES.md` — Future directions: edge confidence scoring, wildcard improvements, type inference.
- `TODO_DEFERRED.md` — Detailed descriptions of all deferred work items.
- `REMAINING-ITEMS.md` — Summary of open items post-2.0.0.
- `DEV-SETUP-UV.md` — Development environment setup using `uv`.

## Code Conventions

- **Line width**: 120 characters (configured in ruff).
- **Python version**: 3.10+ (uses `match` statements, `type` aliases in test code).
- **No external deps** beyond `jinja2` (HTML output only).
- **Test code organization**: version-specific syntax tests go in separate directories (e.g. `tests/test_code_312/`) to avoid `SyntaxError` on older Pythons.
