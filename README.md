# Pyan3

Offline call graph generator for Python 3

![100% Python](https://img.shields.io/github/languages/top/Technologicat/pyan) ![supported language versions](https://img.shields.io/pypi/pyversions/pyan3) ![supported implementations](https://img.shields.io/pypi/implementation/pyan3) ![CI status](https://img.shields.io/github/actions/workflow/status/Technologicat/pyan/tests.yml?branch=master) [![codecov](https://codecov.io/gh/Technologicat/pyan/branch/master/graph/badge.svg)](https://codecov.io/gh/Technologicat/pyan)
![version on PyPI](https://img.shields.io/pypi/v/pyan3) ![PyPI package format](https://img.shields.io/pypi/format/pyan3) ![dependency status](https://img.shields.io/librariesio/github/Technologicat/pyan)
![license: GPL v2+](https://img.shields.io/pypi/l/pyan3) ![open issues](https://img.shields.io/github/issues/Technologicat/pyan) [![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](http://makeapullrequest.com/)

We use [semantic versioning](https://semver.org/).

Pyan takes one or more Python source files, performs a (rather superficial) static analysis, and constructs a directed graph of the objects in the combined source, and how they define or use each other. The graph can be output for rendering by GraphViz or yEd, or as a plain-text dependency list.

This project has 2 official repositories:

- The original stable [davidfraser/pyan](https://github.com/davidfraser/pyan).
- The development repository [Technologicat/pyan](https://github.com/Technologicat/pyan)

> The PyPI package [pyan3](https://pypi.org/project/pyan3/) is built from development

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


<!-- markdown-toc start - Don't edit this section. Run M-x markdown-toc-refresh-toc -->
**Table of Contents**

- [Pyan3](#pyan3)
    - [Note](#note)
    - [Revived! [February 2026]](#revived-february-2026)
- [Overview](#overview)
- [Usage](#usage)
    - [CLI usage](#cli-usage)
        - [Graph depth control](#graph-depth-control)
        - [Filtering](#filtering)
        - [Call path listing](#call-path-listing)
        - [GraphViz layout options](#graphviz-layout-options)
    - [Python API](#python-api)
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
- [Authors](#authors)
- [License](#license)

<!-- markdown-toc end -->


# Overview

[![Example output](graph0.png "Example: GraphViz rendering of Pyan output (click for .svg)")](graph0.svg)

**Defines** relations are drawn with _dotted gray arrows_.

**Uses** relations are drawn with _black solid arrows_. Recursion is indicated by an arrow from a node to itself. [Mutual recursion](https://en.wikipedia.org/wiki/Mutual_recursion#Basic_examples) between nodes X and Y is indicated by a pair of arrows, one pointing from X to Y, and the other from Y to X.

**Nodes** are always filled, and made translucent to clearly show any arrows passing underneath them. This is especially useful for large graphs with GraphViz's `fdp` filter. If colored output is not enabled, the fill is white.

In **node coloring**, the [HSL](https://en.wikipedia.org/wiki/HSL_and_HSV) color model is used. The **hue** is determined by the _filename_ the node comes from. The **lightness** is determined by _depth of namespace nesting_, with darker meaning more deeply nested. Saturation is constant. The spacing between different hues depends on the number of files analyzed; better results are obtained for fewer files.

**Groups** are filled with translucent gray to avoid clashes with any node color.

The nodes can be **annotated** by _filename and source line number_ information.


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
- **`--module-level`** — switch to module-level import dependency view (see below)
- Analyze only a subset of your project's files — references outside the analyzed set are not drawn


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
- **:annotated:** (boolean flag): annotate callgraph with file names
- **:direction:** (string): "horizontal" or "vertical" callgraph
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
- `--concentrate` — merge bidirectional edges into double-headed arrows
- `--init` — include `__init__` modules (excluded by default to reduce clutter)
- `--root` — project root directory (file paths are made relative to this before deriving module names; if omitted, inferred automatically)


### Cycle detection

The `-C` flag performs exhaustive import cycle detection using depth-first search (DFS) from every module:

```
pyan3 --module-level pkg/**/*.py -C
```

This finds all unique import cycles in the analyzed module set, and reports statistics (count, min/average/median/max cycle length). Note that for large codebases, the number of cycles can be large — most are harmless consequences of cross-package imports.

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
    with_init=False,           # exclude __init__ modules (default)
    concentrate=True,          # merge bidirectional edges
    layout="dot",              # GraphViz layout algorithm
    ranksep="0.5",             # rank separation (inches)
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

This repository uses [uv](https://github.com/astral-sh/uv) for development.

```bash
# install uv if needed (see https://docs.astral.sh/uv/getting-started/installation/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# set up a development environment (editable install + test extras)
uv sync --extra test

# run tests
uv run pytest tests/ -v

# run the CLI locally
uv run pyan3 --help

# lint
uv run ruff check .

# coverage report
uv run pytest tests/ --cov=pyan --cov-branch --cov-report=term-missing
```

See [DEV-SETUP-UV.md](DEV-SETUP-UV.md) for a more detailed onboarding guide, and [open issues](https://github.com/Technologicat/pyan/issues) if you are looking for contribution ideas.


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

**GraphViz options**:

- Layout algorithm selection (`dot`, `fdp`, `neato`, `sfdp`, `twopi`, `circo`) ★
- Rank separation control ★
- Bidirectional edge merging (`concentrate`) ★

**Module-level analysis** ★:

- `__init__` modules excluded by default (opt-in with `--init`) ★
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

# Authors

See [AUTHORS.md](AUTHORS.md).

# License

[GPL v2](LICENSE.md), as per [comments here](https://ejrh.wordpress.com/2012/08/18/coloured-call-graphs/).
