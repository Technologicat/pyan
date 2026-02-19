#!/usr/bin/env python3
# -*- coding: utf-8; -*-
"""A simple import analyzer. Visualize dependencies between modules."""

import ast
from argparse import ArgumentParser
from glob import glob
import logging
import os

import io

from . import node, visgraph, writers


def _infer_root(filenames):
    """Infer the project root from a list of ``.py`` file paths.

    Finds the deepest common ancestor directory of all *filenames*,
    then walks up while the directory contains ``__init__.py`` (those
    are packages, not the root).  The first directory without
    ``__init__.py`` is returned as the root.

    Falls back to cwd when *filenames* is empty.
    """
    abspaths = [os.path.abspath(f) for f in filenames]
    if not abspaths:
        return os.getcwd()
    if len(abspaths) == 1:
        common = os.path.dirname(abspaths[0])
    else:
        common = os.path.commonpath(abspaths)
    # If commonpath landed on a file (single file, or all files share a name prefix),
    # step up to the containing directory.
    if not os.path.isdir(common):
        common = os.path.dirname(common)
    # Walk up while directory is a package (contains __init__.py).
    while os.path.isfile(os.path.join(common, "__init__.py")):
        parent = os.path.dirname(common)
        if parent == common:  # filesystem root
            break
        common = parent
    return common


def filename_to_module_name(fullpath, root=None):  # Not anutils.get_module_name: module-level analysis needs __init__ as a distinct node (not folded into the package name).
    """'some/path/module.py' -> 'some.path.module'

    Args:
        fullpath: path to a ``.py`` file (relative or absolute).
        root: project root directory.  When given, *fullpath* is made
            relative to *root* before conversion.  When ``None``
            (default), the path is converted as-is — so it must
            already be relative to the project root (or cwd must be
            the project root).
    """
    if not fullpath.endswith(".py"):
        raise ValueError("Expected a .py filename, got '{}'".format(fullpath))
    if root is not None:
        fullpath = os.path.relpath(os.path.abspath(fullpath), os.path.abspath(root))
    rel = ".{}".format(os.path.sep)  # ./
    if fullpath.startswith(rel):
        fullpath = fullpath[len(rel) :]
    fullpath = fullpath[:-3]  # remove .py
    return fullpath.replace(os.path.sep, ".")


def split_module_name(m):
    """'fully.qualified.name' -> ('fully.qualified', 'name')"""
    k = m.rfind(".")
    if k == -1:
        return ("", m)
    return (m[:k], m[(k + 1) :])


# blacklist = (".git", "build", "dist", "test")
# def find_py_files(basedir):
#     py_files = []
#     for root, dirs, files in os.walk(basedir):
#         for x in blacklist:  # don't visit blacklisted dirs
#             if x in dirs:
#                 dirs.remove(x)
#         for filename in files:
#             if filename.endswith(".py"):
#                 fullpath = os.path.join(root, filename)
#                 py_files.append(fullpath)
#     return py_files


def resolve(*, current, target, level):
    """Return fully qualified name of *target* in an import.

    If level == 0, the import is absolute, hence *target* is already the
    fully qualified name (and will be returned as-is).

    Relative imports (level > 0) are resolved by stripping *level* trailing
    components from *current*, then appending *target*.  This matches
    CPython's resolution against ``__package__``: both regular modules and
    ``__init__`` modules have their own name as the final component, so
    stripping one level always lands on the containing package.

    The resolution is correct given correct module names.  When using
    ``filename_to_module_name``, pass the ``root`` parameter (or ensure
    cwd is the project root) so that dotted names are derived correctly.

    For background on Python's import resolution, see:
        https://alex.dzyoba.com/blog/python-import/
        https://stackoverflow.com/questions/14132789/relative-imports-for-the-billionth-time
    """
    if level < 0:
        raise ValueError("Relative import level must be >= 0, got {}".format(level))
    if level == 0:  # absolute import
        return target
    # level > 0
    if level > current.count(".") + 1:  # foo.bar.baz -> max level 3, pointing to top level
        raise ValueError("Relative import level {} too large for module name {}".format(level, current))
    base = current
    for _ in range(level):
        k = base.rfind(".")
        if k == -1:
            base = ""
            break
        base = base[:k]
    return ".".join((base, target))


class ImportVisitor(ast.NodeVisitor):
    def __init__(self, filenames, logger, root=None):
        self.modules = {}  # modname: {dep0, dep1, ...}
        self.fullpaths = {}  # modname: fullpath
        self.logger = logger
        self.root = root if root is not None else _infer_root(filenames)
        self.analyze(filenames)

    def analyze(self, filenames):
        for fullpath in filenames:
            with open(fullpath, "rt", encoding="utf-8") as f:
                content = f.read()
            m = filename_to_module_name(fullpath, root=self.root)
            self.current_module = m
            self.fullpaths[m] = fullpath
            self.visit(ast.parse(content, fullpath))

    def add_dependency(self, target_module):  # source module is always self.current_module
        m = self.current_module
        if m not in self.modules:
            self.modules[m] = set()
        self.modules[m].add(target_module)
        # Just in case the target (or one or more of its parents) is a package
        # (we don't know that), add a dependency on the relevant __init__ module.
        #
        # If there's no matching __init__ (either no __init__.py provided, or
        # the target is just a module), this is harmless - we just generate a
        # spurious dependency on a module that doesn't even exist.
        #
        # Since nonexistent modules are not in the analyzed set (i.e. do not
        # appear as keys of self.modules), prepare_graph will ignore them.
        #
        # NOTE: A plain-text output reading raw self.modules would see these
        # spurious deps.  Fix: always go through prepare_graph().
        # See TODO_DEFERRED.md "modvis plain-text output".
        modpath = target_module.split(".")
        for k in range(1, len(modpath) + 1):
            base = ".".join(modpath[:k])
            possible_init = base + ".__init__"
            if possible_init != m:  # will happen when current_module is somepackage.__init__ itself
                self.modules[m].add(possible_init)
                self.logger.debug("    added possible implicit use of '{}'".format(possible_init))

    def visit_Import(self, node):
        self.logger.debug(
            "{}:{}: Import {}".format(self.current_module, node.lineno, [alias.name for alias in node.names])
        )
        for alias in node.names:
            self.add_dependency(alias.name)  # alias.asname not relevant for our purposes

    def visit_ImportFrom(self, node):
        # from foo import bar — bar could be a symbol or a submodule.
        if node.module:
            self.logger.debug(
                "{}:{}: ImportFrom '{}', relative import level {}".format(
                    self.current_module, node.lineno, node.module, node.level
                )
            )
            absname = resolve(current=self.current_module, target=node.module, level=node.level)
            if node.level > 0:
                self.logger.debug("    resolved relative import to '{}'".format(absname))
            self.add_dependency(absname)

            # Each imported name might be a submodule (e.g. `from pkg import mod`
            # where mod is a .py file). We speculatively add "{module}.{name}" as
            # a dependency for every imported name. This is safe because both
            # prepare_graph() and detect_cycles() only follow dependencies whose
            # target exists in the analyzed module set — speculative deps that
            # don't match a real module are silently ignored. This is the same
            # pattern add_dependency() already uses for __init__ speculation.
            for alias in node.names:
                self.add_dependency("{}.{}".format(absname, alias.name))

        # from . import foo  -->  module = None; now the **names** refer to modules
        else:
            for alias in node.names:
                self.logger.debug(
                    "{}:{}: ImportFrom '{}', target module '{}', relative import level {}".format(
                        self.current_module, node.lineno, "." * node.level, alias.name, node.level
                    )
                )
                absname = resolve(current=self.current_module, target=alias.name, level=node.level)
                if node.level > 0:
                    self.logger.debug("    resolved relative import to '{}'".format(absname))
                self.add_dependency(absname)

    # --------------------------------------------------------------------------------

    def detect_cycles(self):
        """Detect import cycles via exhaustive DFS from every module.

        Because this is a static analysis, it doesn't care about the order
        the code runs in any particular invocation of the software.  Every
        analyzed module is considered as a possible entry point, and all
        cycles (considering *all* possible branches at *any* step of *each*
        import chain) are mapped recursively.

        This easily leads to combinatorial explosion.  In a mid-size project
        (~20k SLOC), the analysis may find thousands of unique import cycles,
        most of which are harmless.

        Many cycles appear because package A imports from package B (possibly
        from one of its submodules) and vice versa, when both packages have an
        ``__init__`` module.  If they don't actually try to import any names
        that only become defined after the init has finished running, it's
        usually fine.  (Init modules often import names from their submodules
        to the package's top-level namespace; those names can be reliably
        accessed only after the init module has finished running.  But
        importing names directly from the submodule where they are defined is
        fine also during the init.)

        In practice, if your program is crashing due to a cyclic import, you
        already know *which* cycle is causing it from the stack trace.  This
        analysis provides extra information about what *other* cycles exist.

        Returns:
            List of ``(prefix, cycle)`` tuples, where *prefix* is the
            non-cyclic part of the import chain and *cycle* contains only
            the cyclic part (first and last elements are the same module).
        """
        cycles = []

        def walk(m, seen=None, trace=None):
            trace = (trace or []) + [m]
            seen = seen or set()
            if m in seen:
                cycles.append(trace)
                return
            seen = seen | {m}
            deps = self.modules[m]
            for d in sorted(deps):
                if d in self.modules:
                    walk(d, seen, trace)

        for root in sorted(self.modules):
            walk(root)

        # For each detected cycle, report the non-cyclic prefix and the cycle separately
        out = []
        for cycle in cycles:
            offender = cycle[-1]
            k = cycle.index(offender)
            out.append((cycle[:k], cycle[k:]))
        return out

    def prepare_graph(self):  # same format as in analyzer
        """Postprocessing. Prepare data for visgraph for graph file generation."""
        self.nodes = {}  # Node name: list of Node objects (in possibly different namespaces)
        self.uses_edges = {}
        # we have no defines_edges, which doesn't matter as long as we don't enable that option in visgraph.

        # TODO: Right now we care only about modules whose files we read.
        # TODO: If we want to include in the graph also targets that are not in the analyzed set,
        # TODO: then we could create nodes also for the modules listed in the *values* of self.modules.
        for m in self.modules:
            ns, mod = split_module_name(m)
            package = os.path.dirname(self.fullpaths[m])
            # print("{}: ns={}, mod={}, fn={}".format(m, ns, mod, fn))
            # HACK: The `filename` attribute of the node determines the visual color.
            # HACK: We are visualizing at module level, so color by package.
            # See TODO_DEFERRED.md "modvis multi-project coloring".
            n = node.Node(namespace=ns, name=mod, ast_node=None, filename=package, flavor=node.Flavor.MODULE)
            n.defined = True
            # Pyan's analyzer.py allows several nodes to share the same short name,
            # which is used as the key to self.nodes; but we use the fully qualified
            # name as the key. Nevertheless, visgraph expects a format where the
            # values in the visitor's `nodes` attribute are lists.
            self.nodes[m] = [n]

        def add_uses_edge(from_node, to_node):
            if from_node not in self.uses_edges:
                self.uses_edges[from_node] = set()
            self.uses_edges[from_node].add(to_node)

        for m, deps in self.modules.items():
            for d in deps:
                n_from = self.nodes.get(m)
                n_to = self.nodes.get(d)
                if n_from and n_to:
                    add_uses_edge(n_from[0], n_to[0])

        # sanity check output
        for m, deps in self.uses_edges.items():
            assert m.get_name() in self.nodes
            for d in deps:
                assert d.get_name() in self.nodes


def create_modulegraph(
    filenames,
    root=None,
    format="dot",
    rankdir="LR",
    nested_groups=True,
    colored=True,
    annotated=False,
    grouped=True,
    logger=None,
):
    """Create a module-level dependency graph based on static import analysis.

    Args:
        filenames: glob pattern or list of glob patterns
            to identify filenames to parse (``**`` for multiple directories).
            Example: ``"pkg/**/*.py"`` for all Python files in a package.
        root: path to the project root directory.  File paths are made
            relative to *root* before deriving dotted module names.
            Inferred by default.
        format: output format — one of ``"dot"``, ``"svg"``, ``"html"``,
            ``"tgf"``, ``"yed"``, ``"text"``.
            SVG and HTML require the Graphviz ``dot`` binary to be installed.
        rankdir: graph layout direction (Graphviz ``rankdir`` attribute).
            ``"LR"`` for left-to-right, ``"TB"`` for top-to-bottom,
            ``"RL"`` and ``"BT"`` for the reverse directions.
            [dot/svg/html only]
        nested_groups: create nested subgraph clusters for nested
            namespaces (implies ``grouped``). [dot only]
        colored: color nodes by package directory. [dot only]
        annotated: annotate nodes with module location.
        grouped: group nodes into subgraph clusters by namespace.
            [dot only]
        logger: optional ``logging.Logger`` instance.

    Returns:
        The module dependency graph as a string in the requested format.
    """
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [fn2 for fn in filenames for fn2 in glob(fn, recursive=True)]

    if nested_groups:
        grouped = True
    graph_options = {
        "draw_defines": False,
        "draw_uses": True,
        "colored": colored,
        "grouped_alt": False,
        "grouped": grouped,
        "nested_groups": nested_groups,
        "annotated": annotated,
    }

    v = ImportVisitor(filenames, logger or logging.getLogger(__name__), root=root)
    v.prepare_graph()
    graph = visgraph.VisualGraph.from_visitor(v, options=graph_options, logger=logger)

    stream = io.StringIO()
    if format == "dot":
        writer = writers.DotWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
    elif format == "svg":
        writer = writers.SVGWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
    elif format == "html":
        writer = writers.HTMLWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
    elif format == "tgf":
        writer = writers.TgfWriter(graph, output=stream, logger=logger)
    elif format == "yed":
        writer = writers.YedWriter(graph, output=stream, logger=logger)
    elif format == "text":
        writer = writers.TextWriter(graph, output=stream, logger=logger)
    else:
        raise ValueError(f"format {format!r} is unknown")
    writer.run()

    return stream.getvalue()


def main(cli_args=None):
    usage = """%(prog)s FILENAME... [--dot|--tgf|--yed|--svg|--html|--text]"""
    desc = "Analyse one or more Python source files and generate an approximate module dependency graph."
    parser = ArgumentParser(usage=usage, description=desc)
    parser.add_argument("--dot", action="store_true", default=False, help="output in GraphViz dot format")
    parser.add_argument("--svg", action="store_true", default=False, help="output in SVG format")
    parser.add_argument("--html", action="store_true", default=False, help="output in HTML format")
    parser.add_argument("--tgf", action="store_true", default=False, help="output in Trivial Graph Format")
    parser.add_argument("--yed", action="store_true", default=False, help="output in yEd GraphML Format")
    parser.add_argument("--text", action="store_true", default=False, help="output in plain text")
    parser.add_argument("-f", "--file", dest="filename", help="write graph to FILE", metavar="FILE", default=None)
    parser.add_argument("-l", "--log", dest="logname", help="write log to LOG", metavar="LOG")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, dest="verbose", help="verbose output")
    parser.add_argument(
        "-V",
        "--very-verbose",
        action="store_true",
        default=False,
        dest="very_verbose",
        help="even more verbose output (mainly for debug)",
    )
    parser.add_argument(
        "-c",
        "--colored",
        action="store_true",
        default=False,
        dest="colored",
        help="color nodes according to namespace [dot only]",
    )
    parser.add_argument(
        "-g",
        "--grouped",
        action="store_true",
        default=False,
        dest="grouped",
        help="group nodes (create subgraphs) according to namespace [dot only]",
    )
    parser.add_argument(
        "-e",
        "--nested-groups",
        action="store_true",
        default=False,
        dest="nested_groups",
        help="create nested groups (subgraphs) for nested namespaces (implies -g) [dot only]",
    )
    parser.add_argument(
        "-C",
        "--cycles",
        action="store_true",
        default=False,
        dest="cycles",
        help="detect import cycles and print report to stdout",
    )
    parser.add_argument(
        "--dot-rankdir",
        default="TB",
        dest="rankdir",
        help=(
            "specifies the dot graph 'rankdir' property for "
            "controlling the direction of the graph. "
            "Allowed values: ['TB', 'LR', 'BT', 'RL']. "
            "[dot only]"
        ),
    )
    parser.add_argument(
        "-a", "--annotated", action="store_true", default=False, dest="annotated", help="annotate with module location"
    )
    parser.add_argument(
        "--root",
        default=None,
        dest="root",
        help="Package root directory. Inferred by default.",
    )

    known_args, unknown_args = parser.parse_known_args(cli_args)
    filenames = [fn2 for fn in unknown_args for fn2 in glob(fn, recursive=True)]
    if len(unknown_args) == 0:
        parser.error("Need one or more filenames to process")

    if known_args.nested_groups:
        known_args.grouped = True

    graph_options = {
        "draw_defines": False,  # we have no defines edges
        "draw_uses": True,
        "colored": known_args.colored,
        "grouped_alt": False,
        "grouped": known_args.grouped,
        "nested_groups": known_args.nested_groups,
        "annotated": known_args.annotated,
    }

    # TODO: use an int argument for verbosity
    logger = logging.getLogger(__name__)
    if known_args.very_verbose:
        logger.setLevel(logging.DEBUG)
    elif known_args.verbose:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARN)
    logger.addHandler(logging.StreamHandler())
    if known_args.logname:
        handler = logging.FileHandler(known_args.logname)
        logger.addHandler(handler)

    # determine root
    root = None
    if known_args.root is not None:
        root = os.path.abspath(known_args.root)

    # run the analysis
    v = ImportVisitor(filenames, logger, root=root)

    # Cycle detection (see detect_cycles() docstring for semantics)
    if known_args.cycles:
        cycles = v.detect_cycles()
        if not cycles:
            print("No import cycles detected.")
        else:
            unique_cycles = set()
            for prefix, cycle in cycles:
                unique_cycles.add(tuple(cycle))
            print("Detected the following import cycles (n_results={}).".format(len(unique_cycles)))

            def stats():
                lengths = [len(x) - 1 for x in unique_cycles]  # number of modules in the cycle

                def mean(lst):
                    return sum(lst) / len(lst)

                def median(lst):
                    tmp = list(sorted(lst))
                    n = len(lst)
                    if n % 2 == 1:
                        return tmp[n // 2]  # e.g. tmp[5] if n = 11
                    else:
                        return (tmp[n // 2 - 1] + tmp[n // 2]) / 2  # e.g. avg of tmp[4] and tmp[5] if n = 10

                return min(lengths), mean(lengths), median(lengths), max(lengths)

            print(
                "Number of modules in a cycle: min = {}, average = {:0.2g}, median = {:0.2g}, max = {}".format(*stats())
            )
            for c in sorted(unique_cycles):
                print("    {}".format(c))

    # Postprocessing: format graph report
    make_graph = (known_args.dot or known_args.svg or known_args.html
                  or known_args.tgf or known_args.yed or known_args.text)
    if make_graph:
        v.prepare_graph()
        graph = visgraph.VisualGraph.from_visitor(v, options=graph_options, logger=logger)

    if known_args.dot:
        writer = writers.DotWriter(
            graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger
        )
    if known_args.svg:
        writer = writers.SVGWriter(
            graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger
        )
    if known_args.html:
        writer = writers.HTMLWriter(
            graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger
        )
    if known_args.tgf:
        writer = writers.TgfWriter(graph, output=known_args.filename, logger=logger)
    if known_args.yed:
        writer = writers.YedWriter(graph, output=known_args.filename, logger=logger)
    if known_args.text:
        writer = writers.TextWriter(graph, output=known_args.filename, logger=logger)
    if make_graph:
        writer.run()


if __name__ == "__main__":
    main()
