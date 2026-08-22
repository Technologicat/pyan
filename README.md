# Pyan3

Offline call graph generator for Python 3

![100% Python](https://img.shields.io/github/languages/top/Technologicat/pyan) ![supported language versions](https://img.shields.io/pypi/pyversions/pyan3) ![supported implementations](https://img.shields.io/pypi/implementation/pyan3) ![CI status](https://img.shields.io/github/actions/workflow/status/Technologicat/pyan/ci.yml?branch=master) [![codecov](https://codecov.io/gh/Technologicat/pyan/branch/master/graph/badge.svg)](https://codecov.io/gh/Technologicat/pyan)
![version on PyPI](https://img.shields.io/pypi/v/pyan3) ![PyPI package format](https://img.shields.io/pypi/format/pyan3) ![dependency status](https://img.shields.io/librariesio/github/Technologicat/pyan)
![license: GPL v2+](https://img.shields.io/pypi/l/pyan3) ![open issues](https://img.shields.io/github/issues/Technologicat/pyan) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](http://makeapullrequest.com/)

For my stance on AI contributions, see the [collaboration guidelines](https://github.com/Technologicat/substrate-independent/blob/main/collaboration.md).

We use [semantic versioning](https://semver.org/).

Pyan takes one or more Python source files, performs a (rather superficial) static analysis, and constructs a directed graph of the objects in the combined source, and how they define or use each other. The graph can be output for rendering by GraphViz or yEd, or as a plain-text dependency list.

## Note

The static analysis approach Pyan takes is different from running the code and seeing which functions are called and how often. There are various tools that will generate a call graph that way, usually using a debugger or profiling trace hooks, such as [Python Call Graph](https://pycallgraph.readthedocs.org/).

Instead, Pyan reads through the source code, and makes deductions from its structure.

## Revived! [February 2026]

Pyan3 is back in development. The analyzer has been modernized and tested on **Python 3.10–3.14**, with fixes for all modern syntax (walrus operator, `match` statements, `async with`, type aliases, and more). The plan is to keep Pyan3 up to date with new language releases.

**What's new in the revival:**

- Full support for Python 3.10–3.14 syntax
- Module-level import dependency analysis (`--module-level` flag and `create_modulegraph()` API), with import cycle detection
- Graph depth control (`--depth`), directional filtering (`--direction`), call path listing (`--paths-from`/`--paths-to`)
- Comprehensive test suite (200+ tests, 91% branch coverage)
- Modernized build system and dependencies

This revival was carried out by [Technologicat](https://github.com/Technologicat) with [Claude](https://claude.ai/) (Anthropic) as AI pair programmer. See [AUTHORS.md](AUTHORS.md) for the full contributor history.

The project **previously had** 2 official repositories:

- The original stable [davidfraser/pyan](https://github.com/davidfraser/pyan).
- The development repository [Technologicat/pyan](https://github.com/Technologicat/pyan)

> The PyPI package [pyan3](https://pypi.org/project/pyan3/) is built from development

The original stable has been archived; the development repository is now the sole official repository of Pyan3.


<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [Pyan3](#pyan3)
  - [Note](#note)
  - [Revived! [February 2026]](#revived-february-2026)
- [Overview](#overview)
- [Usage](#usage)
  - [CLI usage](#cli-usage)
    - [Recommended options](#recommended-options)
    - [Choosing inputs and `--root`](#choosing-inputs-and---root)
    - [Graph depth control](#graph-depth-control)
    - [Filtering](#filtering)
    - [Namespace-style modules](#namespace-style-modules)
    - [Excluding files](#excluding-files)
    - [Call path listing](#call-path-listing)
    - [GraphViz layout options](#graphviz-layout-options)
  - [Python API](#python-api)
    - [Sans-IO / in-memory analysis](#sans-io--in-memory-analysis)
  - [Troubleshooting](#troubleshooting)
    - [GraphViz trouble in init_rank](#graphviz-trouble-in-init_rank)
    - [Too much detail?](#too-much-detail)
  - [Sphinx integration](#sphinx-integration)
- [Module-level analysis](#module-level-analysis)
  - [CLI usage](#cli-usage-1)
    - [Cycle detection](#cycle-detection)
  - [Python API](#python-api-1)
- [Install](#install)
  - [Development setup](#development-setup)
- [Features](#features)
  - [TODO](#todo)
- [How Pyan works](#how-pyan-works)
  - [What a parameter's annotation means](#what-a-parameters-annotation-means)
  - [What the graph leaves out](#what-the-graph-leaves-out)
    - [Uses edges that a more specific edge already conveys](#uses-edges-that-a-more-specific-edge-already-conveys)
    - [Module nodes, when grouping](#module-nodes-when-grouping)
    - [Lambdas, comprehensions, and unused module-level names](#lambdas-comprehensions-and-unused-module-level-names)
- [Authors](#authors)
- [License](#license)

<!-- markdown-toc end -->


# Overview

<!-- To regenerate graph0:
     pyan3 tests/orbital/*.py --dot --colored --no-defines --concentrate --file graph0.dot
     dot -Tsvg graph0.dot -o graph0.svg
     dot -Tpng graph0.dot -o graph0.png
     rm graph0.dot
-->
[![Example output](graph0.png "Example: GraphViz rendering of Pyan output (click for .svg)")](graph0.svg)

This example was rendered with the [recommended options](#recommended-options): `--colored --no-defines --concentrate`.

**Uses** relations are drawn with _black solid arrows_. Recursion is indicated by an arrow from a node to itself. [Mutual recursion](https://en.wikipedia.org/wiki/Mutual_recursion#Basic_examples) between nodes X and Y is indicated by a pair of arrows, one pointing from X to Y, and the other from Y to X. With `--concentrate`, bidirectional edges are merged into double-headed arrows.

**Defines** relations (drawn with _dotted gray arrows_) can be enabled with `--defines`.

**Nodes** are always filled, and made translucent to clearly show any arrows passing underneath them. This is especially useful for large graphs with GraphViz's `fdp` filter. If colored output is not enabled, the fill is white.

In **node coloring**, the [HSL](https://en.wikipedia.org/wiki/HSL_and_HSV) color model is used. The **hue** is determined by the _filename_ the node comes from. The **lightness** is determined by _depth of namespace nesting_, with darker meaning more deeply nested. Saturation is constant. The spacing between different hues depends on the number of files analyzed; better results are obtained for fewer files.

**Groups** can be enabled with `--grouped` (and `--nested-groups` for nested subgraph clusters). Groups are filled with translucent gray to avoid clashes with any node color.

The nodes can be **annotated** by _filename and source line number_ information. When `--annotated` is used, the node label is extended to include the source file, line number, and flavor (for functions/classes/methods) or just the filename (for modules).

Additionally, all defined nodes always receive a **tooltip** attribute in the DOT output, regardless of `--annotated`. The tooltip contains the fully qualified name plus annotation details. Graph viewers that support the `tooltip` attribute (such as [raven-xdot-viewer](https://github.com/Technologicat/raven)) can display this information on hover.


# Usage

Both CLI and Python API modes are available.


## CLI usage

See `pyan3 --help`.

Basic examples:

```bash
# Generate DOT, then render with GraphViz
pyan3 *.py --uses --no-defines --colored --grouped --annotated --dot >myuses.dot
dot -Tsvg myuses.dot >myuses.svg

# Pass a directory — auto-globs **/*.py
pyan3 src/ --dot --colored --grouped >project.dot

# Generate SVG / HTML directly
pyan3 *.py --uses --no-defines --colored --grouped --annotated --svg >myuses.svg
pyan3 *.py --uses --no-defines --colored --grouped --annotated --html >myuses.html

# Output plain text — especially useful for feeding call graph info to coding AI agents
pyan3 src/ --uses --no-defines --text
```

### Recommended options

For a clean uses-only call graph:

```bash
pyan3 src/*.py --dot --colored --no-defines --concentrate --file output.dot
dot -Tsvg output.dot -o output.svg
```

This omits defines edges (which tend to clutter the graph) and merges bidirectional uses edges into double-headed arrows. The `dot` layout works well for hierarchical call graphs; for larger graphs, `fdp` (force-directed) can produce more readable results:

```bash
pyan3 src/*.py --dot --colored --no-defines --concentrate --graphviz-layout fdp --file output.dot
fdp -Tsvg output.dot -o output.svg
```

For a high-level overview, add `--depth 1` to collapse everything down to modules, classes, and top-level functions:

```bash
pyan3 src/*.py --dot --colored --no-defines --concentrate --depth 1 --file overview.dot
```


### Choosing inputs and `--root`

Pyan derives module names from file paths relative to a *package root*. By default the root is inferred by walking up from the input files while `__init__.py` files are present, stopping at the first directory that doesn't have one. That works for ordinary projects but not for two layouts:

1. **Top-level PEP 420 namespace package.** Layout: `proj/pyproject.toml` and `proj/ns_pkg/sub/__init__.py` with no `__init__.py` at `ns_pkg/` itself. Inference stops one level too deep and module names lose the namespace-package prefix.
2. **Namespace subpackage as input.** Running e.g. `pyan3 raven/visualizer/*.py` where `visualizer/` has no `__init__.py` but `raven/` does. Inference doesn't walk up at all (the input directory itself isn't a regular package), and the result is bare basenames like `app` instead of `raven.visualizer.app`. Any relative imports fail.

Pyan emits a `WARNING` when it detects either situation. The fix is to pass `--root` explicitly, pointing at the *project* root — the directory above the top-level package, typically the one containing `pyproject.toml`. Note that this is **not** the package directory itself; pointing `--root` at the package strips the package's name from the inferred module names and breaks any relative imports that cross the package boundary.

```bash
# Layout 1: top-level namespace package
pyan3 --root . ns_pkg/sub/*.py --dot

# Layout 2: bare-subpackage input
pyan3 --root . raven/visualizer/*.py --dot
```

For layout 2, an alternative is to anchor with the parent's `__init__.py` instead of using `--root` — but only when the parent is a regular (non-namespace) package, since otherwise the file doesn't exist:

```bash
pyan3 raven/__init__.py raven/visualizer/*.py --dot
```

Pyan can't auto-walk past these stopping points: the same filesystem shape (a non-package directory whose parent is a package) also occurs benignly for `tests/`, `examples/`, and similar workspace dirs that sit alongside a package within a project, where escalating would land on the wrong root.


### Graph depth control

Collapse the graph to a desired level of detail:

```bash
pyan3 src/ --dot --depth 0      # modules only (call-graph view, not import deps)
pyan3 src/ --dot --depth 1      # + classes and top-level functions
pyan3 src/ --dot --depth 2      # + methods
pyan3 src/ --dot --depth max    # full detail (default)
```

### Filtering

Focus on a specific function or namespace:

```bash
pyan3 src/ --dot --function pkg.mod.MyClass.method
pyan3 src/ --dot --namespace pkg.mod

# Control traversal direction (requires --function or --namespace)
pyan3 src/ --dot --function pkg.mod.func --direction down   # callees only (what does this function call?)
pyan3 src/ --dot --function pkg.mod.func --direction up     # callers only (what calls this function?)
```

### Namespace-style modules

Some libraries expose a runtime-built namespace value as their public surface — typically `unpythonic.env.env`, `types.SimpleNamespace`, or `argparse.Namespace`. For these, pyan recognises the constructor call and treats its kwargs as attribute bindings, so that an external `config.thingy` access resolves to the kwarg's target. The built-in registry covers four FQNs: `unpythonic.env.env`, the top-level re-export `unpythonic.env`, `types.SimpleNamespace`, and `argparse.Namespace`. To extend it for a project-specific constructor:

```bash
pyan3 src/ --dot --namespace-constructor mylib.MyNamespace
```

Repeatable, or comma-separated (`--namespace-constructor a.b,c.d`). The option also recognises `setattr(config, "k", v)` writes against a registered namespace value.

For ad-hoc shims like `class _NS: pass; store = _NS()` — i.e. instances of project-local classes used as namespaces — pyan can't follow the construction statically (the class is local, not a known constructor), but cross-module `store.attr` access still surfaces the coupling: the edge lands on the binding's Node (the `store = ...` itself) rather than degrading to a wildcard. Add the class to `--namespace-constructor` if you want full attribute resolution.

### Excluding files

Use `-x` / `--exclude` to filter out files before analysis. Patterns without a path separator match against the basename; patterns with a separator match against the full path. The option can be repeated. **Quote the pattern** to prevent the shell from expanding glob characters.

```bash
# Exclude test files
pyan3 'src/**/*.py' --dot -x 'test_*.py' -x 'conftest.py'

# Exclude an entire directory
pyan3 'src/**/*.py' --dot --exclude '*/tests/*'

# Combine both
pyan3 'src/**/*.py' --dot -x 'test_*.py' -x '*/tests/*' -x '*/fixtures/*'
```

### Call path listing

List all call paths between two functions:

```bash
pyan3 src/ --paths-from pkg.mod.caller --paths-to pkg.mod.target
```

Uses depth-first search (DFS); results are sorted shortest first among those found, capped by `--max-paths` (default 100).

### GraphViz layout options

```bash
pyan3 src/ --dot --graphviz-layout fdp   # force-directed layout (also: neato, sfdp, twopi, circo)
pyan3 src/ --dot --dot-ranksep 1.5       # increase rank separation (inches)
pyan3 src/ --dot --concentrate           # merge bidirectional edges into double-headed arrows
```

**Note on `--concentrate`:** GraphViz's edge concentration can produce small gaps at edge split/merge points (endpoint coordinates differ by ~0.02–0.09 graph units). This is a known GraphViz precision issue, visible at high zoom in interactive viewers. The visual output is still useful — just be aware that concentrated edges may not join perfectly.


## Python API

```python
import pyan

# Generate a call graph as a DOT string
dot_source = pyan.create_callgraph(
    filenames="pkg/**/*.py",   # also accepts a directory path
    format="dot",              # also: "svg", "html", "tgf", "yed", "text"
    colored=True,
    nested_groups=True,
    draw_defines=True,
    draw_uses=True,
    depth=2,                   # 0=modules, 1=+classes, 2=+methods, None=full
    direction="both",          # "down" (callees), "up" (callers), "both"
    concentrate=True,          # merge bidirectional edges
    exclude=["test_*.py", "*/tests/*"],  # exclude files matching these patterns
    layout="dot",              # GraphViz layout algorithm
    ranksep="0.5",             # rank separation (inches)
)

# Find call paths between two functions
from pyan.analyzer import CallGraphVisitor
v = CallGraphVisitor(["pkg/mod.py"])
src = v.get_node("pkg.mod", "caller")
tgt = v.get_node("pkg.mod", "target")
paths = v.find_paths(src, tgt, max_paths=100)
print(v.format_paths(paths))
```

See `pyan.create_callgraph()` for the full list of parameters.


### Sans-IO / in-memory analysis

For tools that already have source text in memory (e.g. macro expanders, code editors, notebook kernels), the analysis can run without any file I/O:

```python
from pyan.analyzer import CallGraphVisitor

# From source text — module_name must be fully qualified (dotted).
# For package __init__ modules, append ".__init__" so that relative
# imports resolve correctly (e.g. "pkg.sub.__init__", not "pkg.sub").
v = CallGraphVisitor.from_sources([
    (src_init, "pkg.__init__"),
    (src_alpha, "pkg.alpha"),
    (src_beta, "pkg.beta"),
])

# From a pre-parsed AST (ast.unparse recovers source for symtable)
import ast
tree = ast.parse(src_alpha)
v = CallGraphVisitor.from_sources([
    (tree, "pkg.alpha"),
])

# Or via the high-level API
import pyan
dot = pyan.create_callgraph(
    sources=[(src_alpha, "pkg.alpha"), (src_beta, "pkg.beta")],
    format="dot",
)
```


## Troubleshooting

### GraphViz trouble in init_rank

When you render a Pyan-generated `.dot` file with GraphViz, if GraphViz says _trouble in init_rank_, try adding `-Gnewrank=true`, as in:

`dot -Gnewrank=true -Tsvg myuses.dot >myuses.svg`

Usually either old or new rank (but often not both) works; this is a long-standing GraphViz issue with complex graphs.

### Too much detail?

Several strategies for reducing clutter:

- **`--depth`** — collapse to less detail: `--depth 2` for classes + methods, `--depth 1` for classes only, `--depth 0` for modules only
- **`--function` / `--namespace`** — filter to show only calls related to a specific function or namespace
- **`--direction down`** — show only callees (or `up` for callers); requires `--function` or `--namespace`
- **`--exclude`** / **`-x`** — exclude files by pattern (e.g. `-x 'test_*.py' -x '*/tests/*'`)
- **`--module-level`** — switch to module-level import dependency view (see below)
- Analyze only a subset of your project's files — references outside the analyzed set are not drawn

Pyan also drops some relations on its own, when another part of the drawing already states them — see [What the graph leaves out](#what-the-graph-leaves-out) if an edge you expected is missing.


## Sphinx integration

You can integrate callgraphs into Sphinx.

Install graphviz (e.g. via `sudo apt install graphviz`) and modify `source/conf.py` so that:

```
# modify extensions
extensions = [
  ...
  "sphinx.ext.graphviz"
  "pyan.sphinx",
]

# add graphviz options
graphviz_output_format = "svg"
```

This adds a callgraph directive which has all the options of the [graphviz directive](https://www.sphinx-doc.org/en/master/usage/extensions/graphviz.html), and in addition:

- **:no-groups:** (boolean flag): do not group
- **:no-defines:** (boolean flag): if to not draw edges that show which functions, methods and classes are defined by a class or module
- **:no-uses:** (boolean flag): if to not draw edges that show how a function uses other functions
- **:no-colors:** (boolean flag): if to not color in callgraph (default is coloring)
- **:nested-groups:** (boolean flag): if to group by modules and submodules
- **:annotated:** (boolean flag): annotate callgraph node labels with file names, line numbers, and flavors
- **:direction:** (string): "horizontal" or "vertical" callgraph
- **:exclude:** (string): comma-separated list of exclusion patterns (e.g. `test_*.py, */tests/*`)
- **:toctree:** (string): path to toctree (as used with autosummary) to link elements of callgraph to documentation (makes all nodes clickable)
- **:zoomable:** (boolean flag): enables users to zoom and pan callgraph

Example to create a callgraph for the function `pyan.create_callgraph` that is
zoomable, is defined from left to right and links each node to the API documentation that
was created at the toctree path `api`:

```
.. callgraph:: pyan.create_callgraph
   :toctree: api
   :zoomable:
   :direction: horizontal
```


# Module-level analysis

The `--module-level` flag switches pyan3 from call-graph mode to **module-level import dependency analysis**. Instead of graphing uses and defines relationships, it shows which modules import which other modules. This is useful for a high-level view of a large project.

Both CLI and Python API modes are available.


## CLI usage

```bash
pyan3 --module-level pkg/**/*.py --dot -c -e >modules.dot
pyan3 --module-level pkg/**/*.py --dot -c -e | dot -Tsvg >modules.svg

# Pass a directory — auto-globs **/*.py
pyan3 --module-level src/ --dot -c -e >modules.dot
```

The module-level mode has its own set of options (separate from the call-graph mode). Use `pyan3 --module-level --help` for the full list. Key options:

- `--dot`, `--svg`, `--html`, `--tgf`, `--yed`, `--text` — output format (default: dot)
- `-c`, `--colored` — color by package
- `-g`, `--grouped` — group by namespace
- `-e`, `--nested-groups` — nested subgraph clusters (implies `-g`)
- `-C`, `--cycles` — detect and report import cycles to stdout
- `--dot-rankdir` — layout direction (`TB`, `LR`, `BT`, `RL`)
- `--dot-ranksep` — rank separation in inches
- `--graphviz-layout` — layout algorithm (`dot`, `fdp`, `neato`, etc.)
- `--concentrate` — merge bidirectional edges into double-headed arrows (note: may produce small gaps at split points due to GraphViz precision; see above)
- `-x`, `--exclude` — exclude files matching a pattern (repeatable; see [Excluding files](#excluding-files))
- `--init` — draw a package's `__init__` as its own node, named `pkg.__init__`, together with the implicit dependency every module under `pkg` has on it. By default the `__init__` is drawn as the package itself, under the name `pkg`, and only dependencies that name the package are edges
- `--root` — project root directory (file paths are made relative to this before deriving module names; if omitted, inferred automatically)


### Cycle detection

The `-C` flag performs exhaustive import cycle detection using depth-first search (DFS) from every module:

```
pyan3 --module-level pkg/**/*.py -C
```

This finds all unique import cycles in the analyzed module set, and reports statistics (count, min/average/median/max cycle length). Note that for large codebases, the number of cycles can be large — most are harmless consequences of cross-package imports.

The cycle report works on the raw import records rather than the drawn graph, so it names a package `pkg.__init__` where the graph says `pkg`, and it counts the implicit dependency every module under a package has on that package's `__init__`. That is deliberate for the counting — those implicit imports are exactly how a cycle between two packages usually arises — but it does mean the two views name the same module differently.

If a cycle is actually causing an `ImportError`, you usually already know which cycle from the traceback. The `-C` flag provides a broader view of what other cycles exist.


## Python API

```python
import pyan

# Generate a module dependency graph as a DOT string
dot_source = pyan.create_modulegraph(
    filenames="pkg/**/*.py",   # also accepts a directory path
    root=".",                  # project root; paths made relative to this
    format="dot",              # also: "svg", "html", "tgf", "yed", "text"
    colored=True,
    nested_groups=True,
    with_init=False,           # draw a package's __init__ as the package (default)
    concentrate=True,          # merge bidirectional edges
    exclude=["test_*.py"],     # exclude files matching these patterns
    layout="dot",              # GraphViz layout algorithm
    ranksep="0.5",             # rank separation (inches)
)
```

The sans-IO mode works here too:

```python
dot = pyan.create_modulegraph(
    sources=[
        (src_alpha, "pkg.alpha"),
        (src_beta, "pkg.beta"),
    ],
    format="dot",
)
```

See `pyan.create_modulegraph()` for the full list of parameters.


# Install

```
pip install pyan3
```

or

```
python -m pip install pyan3
```

To install the latest development version from GitHub:

```bash
pip install git+https://github.com/Technologicat/pyan.git
```

Pyan3 requires Python 3.10 or newer.

For SVG and HTML output, you need the `dot` command from [Graphviz](https://graphviz.org/) installed on your system (e.g. `sudo apt install graphviz` on Debian/Ubuntu, `brew install graphviz` on macOS).

DOT and plain-text output require no extra system dependencies.


## Development setup

This repository uses [PDM](https://pdm-project.org/en/latest/) for development.

```bash
# install PDM if needed
python -m pip install pdm

# set up a development venv (creates .venv/, installs pyan3 and dev deps)
pdm install

# run tests
pdm run pytest tests/ -v

# run the CLI locally
pdm run pyan3 --help

# lint
pdm run ruff check .

# coverage report
pdm run pytest tests/ --cov-branch --cov-report=term-missing
```

Activate the venv with `$(pdm venv activate)`, or prefix commands with `pdm run`.

See [open issues](https://github.com/Technologicat/pyan/issues) if you are looking for contribution ideas.


# Features

_Items tagged with ☆ are new in Pyan3 (the Python 3 fork). Items tagged with ★ are new in v2.0+._

**Graph creation**:

- Nodes for functions and classes
- Edges for defines
- Edges for uses
  - This includes recursive calls ☆
- Grouping to represent defines, with or without nesting
- Coloring of nodes by filename
  - Unlimited number of hues ☆

**Analysis**:

- Name lookup across the given set of files
- Nested function definitions
- Nested class definitions ☆
- Nested attribute accesses like `self.a.b` ☆
- Inherited attributes ☆
  - Pyan3 looks up also in base classes when resolving attributes. In the old Pyan, calls to inherited methods used to be picked up by `contract_nonexistents()` followed by `expand_unknowns()`, but that often generated spurious uses edges (because the wildcard to `*.name` expands to `X.name` _for all_ `X` that have an attribute called `name`.).
- Resolution of `super()` based on the static type at the call site ☆
- MRO is (statically) respected in looking up inherited attributes and `super()` ☆
- Assignment tracking with lexical scoping
  - E.g. if `self.a = MyFancyClass()`, the analyzer knows that any references to `self.a` point to `MyFancyClass`
  - All binding forms are supported (assign, augassign, for, comprehensions, generator expressions, with) ☆
    - Name clashes between `for` loop counter variables and functions or classes defined elsewhere no longer confuse Pyan.
- `self` is defined by capturing the name of the first argument of a method definition, like Python does. ☆
- Simple item-by-item tuple assignments like `x,y,z = a,b,c` ☆
- Positional starred tuple unpacking like `a, b, *c = x, y, z, w` ★
- Chained assignments `a = b = c` ☆
- Local scope for lambda, listcomp, setcomp, dictcomp, genexpr ☆
- Walrus operator (`:=`) ★
- `match` statements (PEP 634) ★
- `async with` statements ★
- Type annotations (parameter, return, variable, class-level) ★
- Type aliases (PEP 695, Python 3.12+) ★
- Iterator protocol tracking (`__iter__`/`__next__`, `__aiter__`/`__anext__` for async) ★
- `del` statement protocol tracking (`__delattr__`, `__delitem__`) ★
- Local variable noise suppression — unresolved locals no longer create spurious wildcard nodes ★
- Import-aware wildcard resolution — `*.name` wildcards only expand to targets whose module is actually imported ★
- Source filename and line number annotation ☆
  - The annotation is appended to the node label. If grouping is off, namespace is included in the annotation. If grouping is on, only source filename and line number information is included, because the group title already shows the namespace.

**Querying**:

- Graph depth control — collapse to module, class, or full method level ★
- Directional filtering — show only callers (`up`) or callees (`down`) of a function ★
- Call path listing — find all call paths between two functions ★
- File exclusion by pattern — skip test files, fixtures, etc. before analysis ★

**GraphViz options**:

- Layout algorithm selection (`dot`, `fdp`, `neato`, `sfdp`, `twopi`, `circo`) ★
- Rank separation control ★
- Bidirectional edge merging (`concentrate`) ★

**Module-level analysis** ★:

- A package's `__init__` drawn as the package itself, or separately with `--init` ★
- Directory input — pass a directory path, auto-globs `**/*.py` ★

## TODO

For planned improvements and known limitations, see [TODO_DEFERRED.md](TODO_DEFERRED.md).

# How Pyan works

From the viewpoint of graphing the defines and uses relations, the interesting parts of the [AST](https://en.wikipedia.org/wiki/Abstract_syntax_tree) are bindings (defining new names, or assigning new values to existing names), and any name that appears in an `ast.Load` context (i.e. a use). The latter includes function calls; the function's name then appears in a load context inside the `ast.Call` node that represents the call site.

Bindings are tracked, with lexical scoping, to determine which type of object, or which function, each name points to at any given point in the source code being analyzed. This allows tracking things like:

```python
def some_func():
    pass

class MyClass:
    def __init__(self):
        self.f = some_func

    def dostuff(self)
        self.f()
```

By tracking the name `self.f`, the analyzer will see that `MyClass.dostuff()` uses `some_func()`.

The analyzer also needs to keep track of what type of object `self` currently points to. In a method definition, the literal name representing `self` is captured from the argument list, as Python does; then in the lexical scope of that method, that name points to the current class (since Pyan cares only about object types, not instances).

Of course, this simple approach cannot correctly track cases where the current binding of `self.f` depends on the order in which the methods of the class are executed. To keep things simple, Pyan decides to ignore this complication, just reads through the code in a linear fashion (twice so that any forward-references are picked up), and uses the most recent binding that is currently in scope.

When a binding statement is encountered, the current namespace determines in which scope to store the new value for the name. Similarly, when encountering a use, the current namespace determines which object type or function to tag as the user.

## What a parameter's annotation means

`def f(obj: Thing): obj.method()` draws an edge to `Thing.method`. The annotation is treated as the parameter's type, so attribute access on it resolves — the same as it already did for a local: `thing = Thing(); thing.method()`.

This is a static reading, and it can be wrong in the ordinary way: the value that actually arrives may be a subclass that overrides `method`, in which case the edge points at the base's version. Where a codebase's annotations are loose enough that this misleads more than it helps, `--ignore-parameter-annotations` turns it off (`use_parameter_annotations=False` from the API), and the call falls back to resolving against nothing.

Only classes and modules bind, and only ordinary parameters.

Classes and modules, because pyan resolves an attribute by looking in the target's *scope*, and for both of those the scope is exactly the attribute namespace. `def f(mod: mymodule): mod.helper()` resolves, provided `mymodule` is in the analyzed set.

A function's scope is not — though not because functions have no attributes. `helper.marker = Thing` is recorded, and `helper.marker()` resolves; the binding simply lands in the same dictionary as `helper`'s local variables, and nothing separates the two at the point of lookup. So binding a parameter to a function would resolve `cb.stash.method()` against a local named `stash` and draw a call that cannot happen. That is a limitation of this analyzer rather than a fact about Python, and a fixable one — the scope already records which names are locals — but nothing exploits that yet.

Ordinary parameters, because on `*args` / `**kwargs` the annotation describes the *element* type while the parameter itself is a tuple or a dict. Subscripting one does resolve, though, since a single element is exactly what the annotation describes — both `def f(*items: Thing): items[0].method()` and `def g(**opts: Thing): opts["k"].method()` reach `Thing.method`. Any other subscript resolves to nothing, pyan not tracking what a container holds.

A string annotation, `Optional[X]`, or a union resolves to nothing. Binding every arm of a union would be defensible — pyan already binds a wildcard to several candidates elsewhere — but distinguishing the arms needs to know which value actually arrives, and that is dynamic analysis.

## What the graph leaves out

Pyan draws less than it knows. A call graph that shows every relation the analyzer found is unreadable, so several rules drop relations that another part of the drawing already states. They are listed here because a missing edge is otherwise hard to tell from a bug.

### Uses edges that a more specific edge already conveys

A bare `import harbor` produces a uses edge whether or not the name is ever referenced. A module node therefore collects one edge per imported name, on top of whatever its body actually does — and each of those runs parallel to the edges of the functions that use the name.

A uses edge `S → T` is dropped when either:

- **`S` is a module, and something defined in that module's own file also uses `T`.** The function's edge says it more precisely.
- **`T` is a module, and `S` also uses something under `T`.** Reaching into a module implies depending on it.

The first case in full — the module-level edge goes, the function's stays:

```python
# boat.py
from harbor import Berth   # boat -> harbor.Berth           ...dropped

def cast_off():
    Berth()                # boat.cast_off -> harbor.Berth  ...kept
```

The second case needs one node to do both — to use the module *and* to reach inside it. Here that node is `boat` itself:

```python
# boat.py
import harbor              # boat -> harbor          ...dropped
harbor.signal()            # boat -> harbor.signal   ...kept
```

Move the call into a function and the import edge stays, because the node reaching inside `harbor` is then `boat.cast_off`, and `boat` is left using nothing but `harbor`:

```python
# boat.py
import harbor              # boat -> harbor                 ...kept

def cast_off():
    harbor.Berth()         # boat.cast_off -> harbor.Berth  ...kept
```

Note what this is *not*. A module that merely **defines** a function has a `defines` edge to it, and defines edges are never touched — so in a module where `cast_off()` calls `moor()`, nothing is dropped, there being no module-level *use* of `moor` in the first place. The rule needs the module's own body to use something, which in practice means an import.

Both cases work by narrowing one end of the edge to something inside it, and asking whether that narrower edge exists. Three restrictions on the narrowing keep the rule from eating real information:

- **Only a module narrows.** A class and a module make the same shape — an edge to `X`, and an edge to something inside `X` — and mean different things by it. Write `b = Berth(); b.assign()` in `cast_off` and you get `cast_off → Berth` *and* `cast_off → Berth.assign`, both kept: the first is a constructor call, and a call graph exists to show calls. Write `import harbor; harbor.signal()` in that same function and you get `cast_off → harbor` and `cast_off → harbor.signal`, and the first goes — it is the import statement written to enable the second.
- **Only one end narrows at a time.** In `harbor → harbor.quay`, the source already contains the target. Narrowing both would look for the finer edge anywhere inside `harbor` on one end and anywhere inside `harbor.quay` on the other — and `harbor.quay.bollard → harbor.quay.crane` fits that, being inside both. It is not code in `harbor/__init__.py` and it never reaches `harbor.quay`, so it says nothing about whether that import can go.
- **Narrowing the source reaches only same-file members**, since a package's dotted-name descendants are separate files: `quay/bollard.py` importing `crane` says nothing about what `quay/__init__.py` imports.

The last two are both about packages, and one arrangement shows each:

```python
# harbor/__init__.py
from harbor import quay             # harbor -> harbor.quay                    ...kept

# harbor/quay/__init__.py
from harbor.quay import crane       # harbor.quay -> harbor.quay.crane         ...kept

# harbor/quay/bollard.py
from harbor.quay import crane       # harbor.quay.bollard -> harbor.quay.crane ...dropped

def tie_up():
    return crane                    # harbor.quay.bollard.tie_up -> harbor.quay.crane  ...kept
```

`harbor → harbor.quay` is the both-ends case: `tie_up` lies under `harbor` and `crane` lies under `harbor.quay`, so if both ends narrowed at once, the `tie_up → crane` edge at the bottom would qualify as the finer edge — though it is written in `bollard.py` rather than in `harbor/__init__.py`, and neither of its ends is one of the two in question. `harbor.quay → harbor.quay.crane` is the source-side one — `tie_up` does use exactly that target, but it lives in `bollard.py`, and only what `quay/__init__.py` itself defines can account for what `quay/__init__.py` imports. But inside `bollard.py`, `tie_up` *is* a same-file member, so the ordinary first case applies and the module-level import goes.

What survives is anything nothing else records — a module-level use no function reproduces, and an import whose name is never referenced:

```python
# boat.py
from harbor import make_manifest, tide_table  # boat -> harbor.tide_table    ...kept, nothing else uses it

manifest = make_manifest()                    # boat -> harbor.make_manifest ...kept, no function repeats it
```

The rule never removes the last evidence of a dependency: an edge goes only when a finer edge runs between the same pair, so `--depth 0` still shows every module-to-module dependency.

Applies in every mode, including `--text` and the Python API. Switch it off with `--keep-subsumed-edges`, or `cull_subsumed_edges=False` in `create_callgraph()`, `CallGraphVisitor` and `CallGraphVisitor.from_sources` — worth doing when you are asking questions *about imports* rather than about calls.

### Module nodes, when grouping

With `-g` / `--grouped` (or `-e` / `--nested-groups`), every module is drawn as a cluster. Drawing the module node beside that cluster would label the same thing twice, so the node moves *inside* its own cluster and is labelled `<module>` — the name CPython gives the module-level code object.

- `<module>` appears where the module body uses something, where something uses the module, or where it is the only thing its box would hold. A module that merely contains definitions is left to its members.
- A module's defines edges to its own members are not drawn: the box already states containment.

All three clauses of the first bullet come up in three files:

```python
# harbor/__init__.py               (empty)

# harbor/pier.py
from harbor.crane import lift

def unload():
    lift()

# harbor/crane.py
def lift():
    pass
```

Three boxes, one edge:

- **`harbor`** holds `<module>` alone. It has no members, and an empty box would represent the module by an absence.
- **`harbor.pier`** holds `unload` alone. Its module-level import edge was subsumed by `unload`'s (above), leaving the body using nothing, and nothing uses `harbor.pier` either.
- **`harbor.crane`** holds `lift` alone, for the same reason.
- The only edge drawn is `unload → lift`. `harbor.pier`'s defines edge to `unload` is not, the box having said it.

Neither bullet applies without grouping. There, module nodes keep their full dotted names and all their defines edges, because those edges are then the only thing showing what contains what.

### Lambdas, comprehensions, and unused module-level names

An analyzed module is drawn even when it connects to nothing — a package whose `__init__.py` is empty appears as a node with no edges, and that is the point: you handed pyan the file, so "this links nowhere" is an answer rather than clutter. When grouping, it becomes a box holding `<module>`, like any other module. Modules that were only ever imported, never analyzed, are not drawn at all.

- **Lambdas and comprehensions are folded into the function that contains them.** A lambda that calls `knot` is drawn as its enclosing function calling `knot`.
- **A module-level binding that nothing uses is not drawn.** Names like `__version__` or a private constant become nodes during analysis so that other modules can import them; when nothing does, they would be isolated dots.

Both, in one module:

```python
# rigging.py
__version__ = "1.0"                # not drawn — no other module imports it

def knot(x):
    return x

def rig(lines):
    fasten = lambda x: knot(x)     # rigging.rig -> rigging.knot
    return [knot(y) for y in lines]  # rigging.rig -> rigging.knot, again
```

The graph holds `rigging` defining `knot` and `rig`, and `rig` using `knot`. There is no node for the lambda, none for the comprehension, and none for `__version__`.

# Authors

See [AUTHORS.md](AUTHORS.md).

# License

[GPL v2](LICENSE.md), as per [comments here](https://ejrh.wordpress.com/2012/08/18/coloured-call-graphs/).
