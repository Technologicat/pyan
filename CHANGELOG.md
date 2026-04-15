# Changelog

## 2.4.2 (in progress)

*No user-visible changes yet.*

### Internal

- **Build system migrated from hatchling+uv to PDM** (`pdm-backend`). No user-visible changes; `pip install pyan3` works as before.
- **Sphinx extension: end-to-end integration test** covering `sphinx-build`, the `.. callgraph::` directive, pan/zoom HTML wiring, and directive option propagation. Uses an in-test `dot` stub, so CI needs no system Graphviz. Closes #114. (#124 — thanks @BlocksecPHD)


---

## 2.4.1 (11 April 2026) — *Hotfix: Terra Generica*

### Bug fixes

- **Crash on PEP 695 generic syntax** — `class C[T]`, `def f[T]`, and
  `type A[T] = ...` (Python 3.12+) caused a `KeyError` in
  `visit_FunctionDef` because CPython's `symtable` inserts an implicit
  type-parameter scope that doubled the namespace path.  The fix
  preserves the type-parameter scope as a proper lexical closure
  (essentially a let-over-lambda), matching Python's actual scoping
  semantics.  Handles all PEP 695 forms: generic classes, generic
  functions, generic methods, nested generics, multiple/bounded type
  parameters, and type parameter shadowing in class bodies.
  (#123 — thanks @uselessscat)

### Internal

- **Visitor scope management via context managers** — `visit_Module`,
  `visit_ClassDef`, `visit_FunctionDef`, and `visit_TypeAlias` now use
  `contextlib.contextmanager`-based helpers (`_module_scope`,
  `_class_scope`, `_function_scope`, `_type_params_scope`) instead of
  manual push/pop pairs, guaranteeing cleanup on exception.


---

## 2.4.0 (3 April 2026) — *Here be dragons*

### New features

- **Node tooltips in DOT output** — all defined nodes now carry a `tooltip`
  attribute containing the fully qualified name plus annotation details
  (filename, line number, flavor).  This is always emitted, independent of
  `--annotated`.  Graph viewers that support the `tooltip` attribute (such
  as [raven-xdot-viewer](https://github.com/Technologicat/raven)) can
  display this information on hover.

### Internal

- **`Node.get_annotation_parts()`** — new method that serves as the single
  source of truth for annotation content, used by both the label methods
  and the tooltip builder.


---

## 2.3.1 (2 April 2026) — *Hotfix*

### Bug fixes

- **Relative imports in `__init__.py` resolve to wrong parent package** —
  `from . import alpha` in a nested package init (e.g. `pkg/sub/__init__.py`)
  resolved to the grandparent (`pkg.alpha`) instead of the package itself
  (`pkg.sub.alpha`).  Affected all `__init__` modules whose fully qualified
  name contains at least one dot; top-level packages were correct by accident.
  The bug was present in both file-based and sans-IO (`from_sources`) modes.
  (#121 — thanks @tristanlatr for spotting this in the #101 follow-up)

### Notes

- **`from_sources()`: `__init__` naming convention** — to get correct relative
  import resolution for package `__init__` modules, pass `"pkg.sub.__init__"`
  as the module name (not just `"pkg.sub"`). The previous behaviour silently
  produced wrong or missing edges. Applies to both `CallGraphVisitor.from_sources()`
  and `ImportVisitor.from_sources()`.


---

## 2.3.0 (2 April 2026) — *Carta marina* edition

### New features

- **File exclusion** (`-x` / `--exclude`) — exclude files matching glob
  patterns before analysis.  Patterns without a path separator match
  against the basename (e.g. `test_*.py`); patterns with a separator
  match against the full path (e.g. `*/tests/*`).  Available in both
  call-graph and module-level modes, via CLI, Python API (`exclude`
  parameter in `create_callgraph` / `create_modulegraph`), and the
  Sphinx directive (`:exclude:` option, comma-separated).
  (#119 — thanks @lightswitch05)

- **Class-level constant attribute access** — accessing class constants
  (e.g. `Color.RED` on an Enum, or `Config.DEBUG`) now creates a uses
  edge to the class itself, so these classes no longer appear
  disconnected in the graph.  (#113)

- **Sans-IO analysis via `from_sources`** — `CallGraphVisitor.from_sources()`
  and `create_callgraph(sources=...)` accept `(source_text, module_name)`
  pairs (or `(ast.Module, module_name)`) for analysis without any file
  I/O.  Useful for embedding pyan in tools that already have source text
  in memory, or for analyzing ASTs from macro expanders.
  (#101 — thanks @tristanlatr)

- **Per-anonymous-scope isolation** — multiple lambdas or comprehensions
  in the same function no longer share a single scope.  Each instance
  now gets a numbered scope key (e.g. `listcomp.0`, `listcomp.1`),
  preventing the second instance's bindings from overwriting the first's.
  Works on both pre-3.12 (symtable-based) and 3.12+ (PEP 709 synthetic)
  scope paths.  (#110)

- **Module-graph multi-project coloring** — modules are now colored by
  top-level directory relative to the project root, matching the
  call-graph analyzer's approach. Previously, modules from different
  projects could share colors if their immediate parent directories
  had the same name.  (#111)

- **Class-prefixed method labels when ungrouped** — when grouping is off,
  method labels are now prefixed with the class name (e.g. `MyClass.run`
  instead of just `run`), making it possible to tell which class a method
  belongs to without annotations.  (#112)


---

## 2.2.2 (23 March 2026) — *Hotfix*

### Bug fixes

- **Namespace packages lose cross-module edges** — when a regular package
  (with `__init__.py`) called into a namespace package (without
  `__init__.py`), the edge was silently lost.  `get_module_name()` used
  `__init__.py` as the sole package marker, stripping namespace-package
  directories from module names and breaking edge resolution.  The analyzer
  now auto-infers the project root from the input filenames and uses it
  consistently for all module name resolution.  (#117 — thanks @doctorgu)

### Internal

- **`infer_root()` promoted to public API** — moved from `modvis._infer_root`
  to `anutils.infer_root`, shared by both the call-graph and module-graph
  analyzers.
- **`get_module_name()` `root=None` mode deprecated** — the heuristic
  walk-up is unreliable for namespace packages.  All internal call sites
  now always pass an explicit root.
- **Root excluded from module names** — `get_module_name()` with an explicit
  root no longer includes the root directory's basename in the output,
  matching Python's `sys.path` semantics.


---

## 2.2.1 (22 March 2026) — *Hotfix*

### Documentation

- **Recommended options in README** — added a section with recommended CLI
  options for common use cases: clean uses-only graphs, `fdp` layout for
  larger projects, and `--depth 1` for high-level overviews.  Re-rendered
  the example graph with `--no-defines --concentrate`.
- **`--concentrate` precision caveat** — noted that GraphViz's edge
  concentration can produce small gaps at split/merge points.

### Bug fixes

- **Missing uses edges for names in default argument values** — the #61 fix
  (2.2.0) correctly moved default-value visiting to the enclosing scope, but
  lost uses edges from the function to names referenced in its defaults.
  `def f(cb=wrapper(func))` now correctly shows `f → wrapper` and
  `f → func`.  (#116)
- **`--depth` dropped almost all uses edges** — `filter_by_depth` counted
  raw dots in the fully qualified name, so modules with dotted names (e.g.
  `pkg.sub.mod`) inflated the depth of every node inside them.  Ancestor
  lookup then created phantom nodes with the wrong namespace/name split,
  which were silently discarded.  Depth is now computed relative to each
  node's containing module, giving consistent behaviour regardless of
  package depth.  The depth scale is: 0 = modules, 1 = classes/top-level
  functions, 2 = methods, etc.


---

## 2.2.0 (16 March 2026) — *Terra cognita* edition

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
- **`__init__` modules omitted by default in modvis** — reduces clutter
  in module dependency graphs.  Use ``--init`` (CLI) or
  ``with_init=True`` (API) to include them.  (#20)
- **Directory input** — passing a directory path as a positional argument
  now auto-globs ``**/*.py``.  Works in both call-graph and module-level
  modes, CLI and API.  (#66)
- **`--concentrate`** — merge bidirectional edges into single
  double-headed arrows (GraphViz ``concentrate`` attribute).  Available
  in both call-graph and module-level modes, CLI and API.  (#21)
- **`--paths-from` / `--paths-to`** — list call paths between two
  functions.  Output is one path per line, sorted shortest first
  (among those found; DFS discovery order, capped by ``--max-paths``,
  default 100).  (#12)
- **`--depth`** — collapse the call graph to a maximum nesting level.
  ``0`` = modules only, ``1`` = + classes/top-level functions,
  ``2`` = + methods, ``max`` = full detail (default).  Edges to deeper
  nodes are redirected to their ancestor; self-edges suppressed.  (#80)

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
