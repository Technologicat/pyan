# Pyan3 Revival — Reconnaissance Brief

This document is a task brief for Claude Code. The goal is to analyze the Pyan3 codebase and produce a reconnaissance report — no code changes yet.

## Context

Pyan3 is a static call graph analyzer for Python. It parses Python source files using the `ast` module, builds a graph of definitions and uses edges, and can output to DOT, SVG, HTML, and yEd formats. The codebase is ~3400 lines across 8 Python modules.

The project has been unmaintained for a few years. A contributor recently modernized the build system to UV + hatchling (November 2025), but no functional changes have been made since 2021.

**Owner**: Juha Jeronen (@Technologicat). This is a revival, not a rewrite.

## Target Python versions

We want Pyan3 to both **run on** and **analyze code written for** Python 3.10 through 3.14.

Currently supported Python versions (Feb 2026):

| Version | Security support until |
|---------|----------------------|
| 3.10    | Oct 2026             |
| 3.11    | Oct 2027             |
| 3.12    | Oct 2028             |
| 3.13    | Oct 2029             |
| 3.14    | Oct 2030             |

3.9 went EOL Oct 2025. We drop it.

## Known issues

### 1. Import crash in dev mode

`pyan/__init__.py` line 7: `__version__ = version("pyan3")` uses `importlib.metadata.version()`, which only works when the package is pip-installed. Running from a dev checkout crashes immediately with `PackageNotFoundError`. This needs a fallback.

### 2. AST compatibility — running on newer Pythons

**Python 3.14 removed** `ast.Num`, `ast.Str`, `ast.Bytes`, `ast.NameConstant`, `ast.Ellipsis` (deprecated since 3.8). Line 1203 in `analyzer.py` uses `isinstance(ast_node.value, (ast.Num, ast.Str))` which will crash on 3.14.

**Python 3.13** tightened AST constructor validation — missing required fields now emit `DeprecationWarning` (will be errors in 3.15). Check whether Pyan3 constructs any AST nodes manually.

### 3. AST compatibility — analyzing newer Python syntax

The analyzer currently understands syntax up to roughly Python 3.6. It has no visitor methods for:

- `ast.NamedExpr` (walrus operator `:=`, Python 3.8)
- `ast.Match` and related pattern matching nodes (Python 3.10)
- `ast.TryStar` (exception groups `except*`, Python 3.11)
- `ast.TypeAlias` and type parameter nodes (Python 3.12)
- `ast.TypeVar` `default_value` field (Python 3.13)
- Template strings / t-strings (Python 3.14)

For the recon, catalog what each of these would mean for the call graph (some may be no-ops for call graph purposes — e.g., `except*` probably doesn't affect call edges).

### 4. Reference material for AST changes

- Pyan3 issue tracker: https://github.com/Technologicat/pyan/issues/51 (3.8 changes)
- unpythonic issue tracker: https://github.com/Technologicat/unpythonic/issues/93 (3.10–3.12 changes)
- mcpyrate unparser (supports up to 3.12): https://github.com/Technologicat/mcpyrate/blob/master/mcpyrate/unparser.py
- No AST changes in Python 3.7 (intentional gap in coverage).
- Python 3.13 "What's New": https://docs.python.org/3/whatsnew/3.13.html
- Python 3.14 "What's New": https://docs.python.org/3/whatsnew/3.14.html
- Jelle Zijlstra's post on AST strictness changes: https://jellezijlstra.github.io/ast313.html

### 5. `last_value` mechanism

Somewhere in the analyzer there is a `last_value` tracking mechanism that tracks the most recently seen rvalue during AST traversal. The owner considers it architecturally unsound. **Do not remove or modify it now**, but analyze it in depth.

The core issue is philosophical: `last_value` attempts dynamic-analysis reasoning (simulating execution order) inside a static analyzer. It gives exactly one answer ("the last thing assigned to `x` was `Foo()`") where the honest static answer is "could be several" — `x` might be bound to any of the things assigned to it in this scope.

This matters because:

- It's order-dependent in a way AST visiting shouldn't be — "last" depends on traversal order, not execution order (which diverge at branches, loops, exceptions).
- It conflates "most recently seen by the visitor" with "most recently executed at runtime."
- It gives a false sense of precision — one edge where there should be several.

The likely replacement is a proper name-binding analysis that collects *all* possible bindings for a name in a given scope and creates call graph edges for all of them. This is still a static overapproximation, but an honest one.

The analyzer's overall job is to produce a graph that helps a human understand the structure of a codebase. The right balance is: overapproximation is fine (extra edges are less harmful than missing ones), but *too much* overapproximation makes the graph useless (everything-calls-everything defeats the purpose). The `last_value` hack is an attempt to reduce overapproximation in the common case — a valid *goal* even if the mechanism is wrong.

For the recon, characterize `last_value` in terms of:
- **Where** it lives (which methods, what state it maintains)
- **What static-analysis question** it's trying to answer
- **How deeply** it's wired into the analysis (what breaks if you remove it)
- **What a proper replacement would look like** — would a "set of all bindings in scope" approach be sufficient, or does the analyzer need something closer to a points-to analysis?

### 6. `modvis.py` — standalone module dependency analyzer

`modvis.py` in the project root is a separate analyzer that maps module-level dependencies (rather than function-level call graphs). It has its own independent analysis logic. Future plan: integrate it as a lower-granularity mode in the same CLI (e.g., `pyan3 --module-level`), keeping both analyzers as separate code paths selected by CLI options. For the recon, just characterize what it does and how it differs from the main analyzer.

### 7. Test coverage

Current tests are minimal (`tests/test_analyzer.py` is ~60 lines). We will need to add substantial unit tests. For the recon, note what the existing tests cover and identify the most important areas for new tests.

## Reconnaissance tasks

Please produce a report covering:

1. **AST node usage audit**: Every AST node type the analyzer visits or checks for. Map these against what's been added/changed/removed in Python 3.8–3.14.

2. **`last_value` mechanism**: Locate and describe it. How deeply is it wired into the analysis? What depends on it?

3. **`modvis.py` characterization**: What does it analyze? How does its approach differ from the main analyzer? What would integration look like?

4. **Import/boot issues**: The `__version__` crash, plus any other import-time problems you find.

5. **Test coverage assessment**: What do existing tests cover? What are the highest-priority gaps?

6. **Dependency audit**: Current dependencies (`jinja2`, `graphviz`). Are they all still needed? Any version constraints?

7. **Architecture overview**: Module dependency map of Pyan3 itself. What calls what, what are the layers?

8. **Actionable issue list**: Prioritized list of changes needed, roughly categorized as:
   - **Must fix**: Blocks running on 3.10–3.14
   - **Should fix**: Needed for analyzing 3.10–3.14 code correctly
   - **Nice to have**: Improvements, but not blocking

## What NOT to do

- Do not make any code changes.
- Do not attempt a style conversion.
- Do not attempt to fix the `last_value` mechanism.
- Do not integrate `modvis.py`.
