# Changelog

## 2.2.0 (in progress)

### Bug fixes

- **Deterministic edge ordering** — all output writers now sort edges by
  `(source, target)`, making output reproducible across runs.  Previously
  the order depended on dict iteration order and could change between calls.
  (#77, PR #78 — thanks @aurelg)
- **DOT identifier quoting** — node IDs and subgraph names in DOT output are
  now double-quoted, so directory names containing dashes (e.g. `my-project`)
  no longer produce invalid DOT files.  (#71)
- **BrokenPipeError on piped output** — `pyan3` now resets SIGPIPE to the
  default handler, so piping to commands like `head` exits cleanly instead
  of printing a traceback.  (#75)
- **Crash on lambda or comprehension as default argument** — default value
  expressions are now visited in the enclosing scope (matching Python's
  evaluation semantics), fixing `ValueError: Unknown scope '...lambda'`
  and similar crashes.  (#61)
- **Spurious cross-module edges from wildcard expansion** — `expand_unknowns()`
  now checks import relationships before expanding `*.name` wildcards,
  preventing false edges between modules that don't import each other.
  Import tracking is per-namespace, so function-level imports are scoped
  correctly — a function-level import does not leak to sibling functions.
  Postprocessing order changed to resolve→contract→expand.  (#88)
- **`get_module_name` mangled paths with `.py` in directory names** — e.g.
  `wheel-0.37.1-py2.py3-none-any/...`.  Now uses `removesuffix(".py")`
  instead of `replace(".py", "")`.  (PR #97 — thanks @CannedFish)
- **`resolve_imports` KeyError** — `self.defines_edges[to_node]` could raise
  `KeyError` for imported items with no defines edges.  Now uses `.get()`
  with a default.  (PR #95, PR #97 — thanks @anetczuk, @CannedFish)

### New features

- **`--dot-ranksep`** — control rank separation in GraphViz output
  (inches).  (PR #74 — thanks @maciejczyzewski)
- **`--graphviz-layout`** — select layout algorithm (`dot`, `fdp`, `neato`,
  `sfdp`, `twopi`, `circo`).  Available in both call-graph and
  module-level modes, and from the Python APIs.  (PR #74 — thanks
  @maciejczyzewski)
- **`--direction`** — control graph filter traversal: ``down`` (callees
  only), ``up`` (callers only), or ``both`` (default).  Requires
  ``--function`` or ``--namespace``.  Also available as a ``direction``
  parameter in the ``create_callgraph()`` API.  (PR #95 — thanks
  @anetczuk for the original idea)

### Housekeeping

- CI linter migrated from flake8 to ruff.
- Converted %-formatting and `.format()` to f-strings throughout.
- Resolved all ruff lint warnings.


## 2.1.0 (2026-03-10)

### New features

- Plain-text output format (`--text` / `format="text"`) for both call-graph
  and module-level modes.  Sorted adjacency list with `[D]`/`[U]` edge tags.
- **`del` statement protocol tracking** — `del obj.attr` now generates a uses
  edge to `__delattr__`, and `del obj[key]` to `__delitem__`.  Complements the
  existing `__enter__`/`__exit__` tracking for `with`.
- **Iterator protocol tracking** — `for` loops, `async for` loops, and
  comprehensions now generate uses edges to `__iter__`/`__next__` (or
  `__aiter__`/`__anext__` for async).  Comprehension generators respect
  the `is_async` flag.
- **Local variable noise suppression** — `visit_Name` no longer creates
  wildcard `UNKNOWN`-flavored nodes for local variables with no resolved value.
  Eliminates spurious edges for loop counters, temporaries, and other locals
  that don't contribute to the call graph.
- **Positional matching for starred tuple unpacking** — `a, b, *c = x, y, z, w`
  now binds `a→x`, `b→y`, `*c→{z, w}` instead of the previous Cartesian
  product (every target bound to every value).  Works for a single star at any position
  on the LHS.  Cartesian fallback remains for cases that can't be resolved
  statically.
- `--version` CLI flag.

### Bug fixes

- Fix `--defines` being off by default due to an argparse quirk —
  `store_true` implicitly sets `default=False`, which won the shared
  dest over `--no-defines`' explicit `default=True`.  Defines edges
  (dashed gray arrows) now appear by default as documented.

### Documentation

- Reorganized README with table of contents.
- Python API example for call-graph mode.
- Updated Features section with all v2.0+ additions.
- Consolidated inline TODO items into `TODO_DEFERRED.md`.
- New synthetic showcase graph (orbital mechanics theme) demonstrating
  uses edges, self-recursion, mutual recursion, HSL coloring, and
  namespace grouping.

### Housekeeping

- Bumped `actions/checkout` to v6, `actions/setup-python` to v6.


## 2.0.0 (2026-02-19)

**Python 3.10–3.14.** This release drops support for Python < 3.10.

### New features

- **Module-level import dependency analysis** — `--module-level` CLI flag and
  `create_modulegraph()` Python API.
  - Visualizes which modules import which, with import cycle detection (`-C`/`--cycles`).
  - This replaces the previous separate `modvis.py` that used to live at the project root.
  - This analyzer now supports `--root` — explicit project root directory; inferred by default
    (walks up past `__init__.py` directories).

- **Supports all new syntax added after Python 3.6, up to and including 3.14.**
  - `type` statement (PEP 695 type aliases, including parameterized aliases)
    and inlined comprehension scopes.
  - Walrus operator (expression assignment, `:=`) — tracked as both a use
    (RHS) and a definition.
  - **`async with`** — `__aenter__`/`__aexit__` protocol edges.
  - **`match` statement** — class patterns, guard expressions, and body calls.
  - **Type annotations** — `AnnAssign`, function argument/return annotations,
    and class-body annotations generate "uses" edges.

- **All five output formats** (`dot`, `svg`, `html`, `tgf`, `yed`) available
  from both `create_callgraph()` and `create_modulegraph()` APIs.

### Internal/maintainability improvements

- Modernized build system (hatchling via `pyproject.toml`).
- Eliminated internal `self.last_value` state — analysis uses return values
  and `_bind_target()` throughout.
- Deduplicated `create_callgraph()` / `main()` analysis pipeline via shared
  `_build_graph()`.
- `resolve()` (modvis) now uses keyword-only parameters.
- `sanitize_exprs` renamed to `canonize_exprs` (the function canonicalizes,
  it does not sanitize).
- Comprehensive test suite: 94 tests (90 on 3.10, 94 on 3.12+), 73% coverage.
- CI: GitHub Actions matrix (3.10–3.14), flake8 lint, Codecov integration.
- Zero flake8 warnings across the codebase.
- Sphinx extension verified and smoke-tested with current Sphinx.

### Bug fixes

- Fix CLI crash on relative paths (contributed by Joenio Marques da Costa).
- Fix `CallGraphVisitor` positional arguments issue (contributed by kuuurt).
- Fix modvis `from`-import to detect submodule dependencies.
- Fix modvis `filename_to_module_name` cwd fragility — paths are now made
  relative to an inferred (or explicit) project root.

### Contributors

Thanks to kuuurt, Joenio Marques da Costa (analizo), and A M (BackBenchDevs)
for contributions included in this release.

Thanks also to Anthropic for Claude Opus 4.6 and Claude Code.


## 1.2.0 (2021-02-11)

Last 1.x release.

The last compatible language version was Python 3.6.

See the git history for details.
