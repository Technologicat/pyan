# Changelog

## 2.0.1 (unreleased)

### Bug fixes

- Fix `--defines` being off by default due to an argparse quirk —
  `store_true` implicitly sets `default=False`, which won the shared
  dest over `--no-defines`' explicit `default=True`.  Defines edges
  (dashed gray arrows) now appear by default as documented.

### New features

- Plain-text output format (`--text` / `format="text"`) for both call-graph
  and module-level modes.  Sorted adjacency list with `[D]`/`[U]` edge tags.
- **`del` statement protocol tracking** — `del obj.attr` now generates a uses
  edge to `__delattr__`, and `del obj[key]` to `__delitem__`.  Complements the
  existing `__enter__`/`__exit__` tracking for `with`.

### Other

- Regenerate example graph image (pyan analyzing its own `modvis.py`).


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
