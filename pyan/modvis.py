#!/usr/bin/env python3
# -*- coding: utf-8; -*-
"""A simple import analyzer. Visualize dependencies between modules."""

from argparse import ArgumentParser
import ast
from glob import glob
import io
import logging
import os

from . import node, visgraph, writers
from .anutils import expand_sources, infer_root, resolve_import

__all__ = [
    "ImportVisitor",
    "create_modulegraph",
    "filename_to_module_name",
    "main",
    "split_module_name",
]


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
        raise ValueError(f"Expected a .py filename, got '{fullpath}'")
    if root is not None:
        fullpath = os.path.relpath(os.path.abspath(fullpath), os.path.abspath(root))
    rel = f".{os.path.sep}"  # ./
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




class ImportVisitor(ast.NodeVisitor):
    def __init__(self, filenames, logger, root=None):
        self.modules = {}  # modname: {dep0, dep1, ...}
        self.fullpaths = {}  # modname: fullpath
        self.logger = logger
        self.root = root if root is not None else infer_root(filenames)
        self.analyze(filenames)

    @classmethod
    def from_sources(cls, sources, logger=None):
        """Create an ImportVisitor from in-memory sources (no file I/O).

        Args:
            sources: iterable of ``(source, module_name)`` pairs, where
                *source* is either a ``str`` (source text) or an
                ``ast.Module`` (parsed AST — will be unparsed).
                *module_name* must be the fully qualified dotted name
                (e.g. ``"pkg.sub.mod"``).  For package ``__init__``
                modules, append ``.__init__`` (e.g. ``"pkg.__init__"``)
                so that relative imports resolve correctly.
            logger: optional ``logging.Logger`` instance.

        Returns:
            A fully analyzed ``ImportVisitor``.
        """
        self = cls.__new__(cls)
        self.modules = {}
        self.fullpaths = {}
        self.logger = logger or logging.getLogger(__name__)
        self.root = ""
        for source, module_name in sources:
            if isinstance(source, ast.AST):
                source = ast.unparse(source)
            self.current_module = module_name
            self.fullpaths[module_name] = module_name  # use module name as stand-in
            self.visit(ast.parse(source, module_name))
        return self

    def analyze(self, filenames):
        for fullpath in filenames:
            with open(fullpath, encoding="utf-8") as f:
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
                self.logger.debug(f"    added possible implicit use of '{possible_init}'")

    def visit_Import(self, node):
        self.logger.debug(
            f"{self.current_module}:{node.lineno}: Import {[alias.name for alias in node.names]}"
        )
        for alias in node.names:
            self.add_dependency(alias.name)  # alias.asname not relevant for our purposes

    def visit_ImportFrom(self, node):
        # from foo import bar — bar could be a symbol or a submodule.
        if node.module:
            self.logger.debug(
                f"{self.current_module}:{node.lineno}: ImportFrom '{node.module}', relative import level {node.level}"
            )
            absname = resolve_import(current=self.current_module, target=node.module, level=node.level, logger=self.logger)
            if node.level > 0:
                self.logger.debug(f"    resolved relative import to '{absname}'")
            self.add_dependency(absname)

            # Each imported name might be a submodule (e.g. `from pkg import mod`
            # where mod is a .py file). We speculatively add "{module}.{name}" as
            # a dependency for every imported name. This is safe because both
            # prepare_graph() and detect_cycles() only follow dependencies whose
            # target exists in the analyzed module set — speculative deps that
            # don't match a real module are silently ignored. This is the same
            # pattern add_dependency() already uses for __init__ speculation.
            for alias in node.names:
                self.add_dependency(f"{absname}.{alias.name}")

        # from . import foo  -->  module = None; now the **names** refer to modules
        else:
            for alias in node.names:
                self.logger.debug(
                    "{}:{}: ImportFrom '{}', target module '{}', relative import level {}".format(
                        self.current_module, node.lineno, "." * node.level, alias.name, node.level
                    )
                )
                absname = resolve_import(current=self.current_module, target=alias.name, level=node.level, logger=self.logger)
                if node.level > 0:
                    self.logger.debug(f"    resolved relative import to '{absname}'")
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

    def prepare_graph(self, with_init=False):  # same format as in analyzer
        """Postprocessing. Prepare data for visgraph for graph file generation.

        Args:
            with_init: if True, include ``__init__`` modules.
                Excluded by default to reduce clutter.
        """
        self.nodes = {}  # Node name: list of Node objects (in possibly different namespaces)
        self.uses_edges = {}
        # we have no defines_edges, which doesn't matter as long as we don't enable that option in visgraph.

        # TODO: Right now we care only about modules whose files we read.
        # TODO: If we want to include in the graph also targets that are not in the analyzed set,
        # TODO: then we could create nodes also for the modules listed in the *values* of self.modules.
        for m in self.modules:
            if not with_init and (m.endswith(".__init__") or m == "__init__"):
                continue
            ns, mod = split_module_name(m)
            # The `filename` attribute of the node determines the visual color.
            # Color by top-level directory relative to root, so that modules
            # from different projects get distinct hues in multi-project runs.
            relpath = os.path.relpath(self.fullpaths[m], self.root)
            color_key = relpath.split(os.sep)[0]
            n = node.Node(namespace=ns, name=mod, ast_node=None, filename=color_key, flavor=node.Flavor.MODULE)
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
    filenames=None,
    root=None,
    sources=None,
    format="dot",
    rankdir="LR",
    ranksep="0.5",
    layout="dot",
    nested_groups=True,
    colored=True,
    annotated=False,
    grouped=True,
    with_init=False,
    concentrate=False,
    exclude=None,
    logger=None,
):
    """Create a module-level dependency graph based on static import analysis.

    Args:
        filenames: glob pattern or list of glob patterns
            to identify filenames to parse (``**`` for multiple directories).
            Example: ``"pkg/**/*.py"`` for all Python files in a package.
        root: path to the project root directory.  File paths are made
            relative to *root* before deriving dotted module names.
            Inferred by default. Ignored when *sources* is given.
        sources: alternative to *filenames* and *root* — an iterable of
            ``(source, module_name)`` pairs for analysis without file I/O.
            *source* can be a ``str`` (source text) or ``ast.Module``
            (will be unparsed).  *module_name* must be the fully
            qualified dotted name (e.g. ``"pkg.sub.mod"``).
            When given, *filenames*, *root*, and *exclude* are ignored.
        format: output format — one of ``"dot"``, ``"svg"``, ``"html"``,
            ``"tgf"``, ``"yed"``, ``"text"``.
            SVG and HTML require the Graphviz ``dot`` binary to be installed.
        rankdir: graph layout direction (Graphviz ``rankdir`` attribute).
            ``"LR"`` for left-to-right, ``"TB"`` for top-to-bottom,
            ``"RL"`` and ``"BT"`` for the reverse directions.
            [dot/svg/html only]
        ranksep: desired rank separation in inches (Graphviz ``ranksep``).
            [dot only]
        layout: Graphviz layout algorithm — ``"dot"`` (hierarchical),
            ``"fdp"`` (force-directed), ``"neato"``, ``"sfdp"``, etc.
            [dot/svg/html only]
        nested_groups: create nested subgraph clusters for nested
            namespaces (implies ``grouped``). [dot only]
        colored: color nodes by package directory. [dot only]
        annotated: annotate nodes with module location.
        grouped: group nodes into subgraph clusters by namespace.
            [dot only]
        with_init: include ``__init__`` modules in the output.
            Excluded by default to reduce clutter.
        concentrate: merge bidirectional edges into single double-headed
            arrows (GraphViz ``concentrate`` attribute). [dot/svg/html only]
        exclude: list of exclusion patterns.  Patterns without a path
            separator match against the basename (e.g. ``"test_*.py"``);
            patterns with a separator match against the full path
            (e.g. ``"*/tests/*"``).
        logger: optional ``logging.Logger`` instance.

    Returns:
        The module dependency graph as a string in the requested format.
    """
    if sources is not None:
        filenames = None
    else:
        if isinstance(filenames, str):
            filenames = [filenames]
        filenames = expand_sources(filenames, exclude=exclude)

    if not grouped:
        nested_groups = False
    elif nested_groups:
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

    if sources is not None:
        v = ImportVisitor.from_sources(sources, logger=logger or logging.getLogger(__name__))
    else:
        v = ImportVisitor(filenames, logger or logging.getLogger(__name__), root=root)
    v.prepare_graph(with_init=with_init)
    graph = visgraph.VisualGraph.from_visitor(v, options=graph_options, logger=logger)

    stream = io.StringIO()
    dot_options = ["rankdir=" + rankdir, "ranksep=" + ranksep, "layout=" + layout]
    if concentrate:
        dot_options.append("concentrate=true")
    if format == "dot":
        writer = writers.DotWriter(graph, options=dot_options, output=stream, logger=logger)
    elif format == "svg":
        writer = writers.SVGWriter(graph, options=dot_options, output=stream, logger=logger)
    elif format == "html":
        writer = writers.HTMLWriter(graph, options=dot_options, output=stream, logger=logger)
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
    from . import __version__
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
        "--dot-ranksep",
        default="0.5",
        dest="ranksep",
        help=(
            "specifies the dot graph 'ranksep' property for "
            "controlling desired rank separation, in inches. "
            "[dot only]"
        ),
    )
    parser.add_argument(
        "--graphviz-layout",
        default="dot",
        dest="layout",
        help=(
            "specifies the graphviz layout algorithm. "
            "Commonly used: 'dot' (default, hierarchical), "
            "'fdp' (force-directed), 'neato', 'sfdp', 'twopi', 'circo'. "
            "[dot/svg/html only]"
        ),
    )
    parser.add_argument(
        "-a", "--annotated", action="store_true", default=False, dest="annotated", help="annotate with module location"
    )
    parser.add_argument(
        "--init", action="store_true", default=False, dest="with_init",
        help="include __init__ modules in the output (excluded by default to reduce clutter)",
    )
    parser.add_argument(
        "--concentrate", action="store_true", default=False, dest="concentrate",
        help="merge bidirectional edges into a single double-headed arrow [dot/svg/html only]",
    )
    parser.add_argument(
        "--root",
        default=None,
        dest="root",
        help="Package root directory. Inferred by default.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        action="append",
        default=[],
        dest="exclude",
        metavar="PATTERN",
        help=(
            "exclude files matching PATTERN. "
            "Patterns without a path separator match against the basename; "
            "patterns with a separator match against the full path. "
            "Can be repeated. Quote the pattern to prevent shell expansion "
            "(e.g. --exclude 'test_*.py' --exclude '*/tests/*')."
        ),
    )

    known_args, unknown_args = parser.parse_known_args(cli_args)
    filenames = expand_sources(unknown_args, exclude=known_args.exclude)
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
            for _prefix, cycle in cycles:
                unique_cycles.add(tuple(cycle))
            print(f"Detected the following import cycles (n_results={len(unique_cycles)}).")

            def stats():
                lengths = [len(x) - 1 for x in unique_cycles]  # number of modules in the cycle

                def mean(lst):
                    return sum(lst) / len(lst)

                def median(lst):
                    tmp = sorted(lst)
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
                print(f"    {c}")

    # Postprocessing: format graph report
    make_graph = (known_args.dot or known_args.svg or known_args.html
                  or known_args.tgf or known_args.yed or known_args.text)
    if make_graph:
        v.prepare_graph(with_init=known_args.with_init)
        graph = visgraph.VisualGraph.from_visitor(v, options=graph_options, logger=logger)

    dot_options = [
        "rankdir=" + known_args.rankdir,
        "ranksep=" + known_args.ranksep,
        "layout=" + known_args.layout,
    ]
    if known_args.concentrate:
        dot_options.append("concentrate=true")

    if known_args.dot:
        writer = writers.DotWriter(graph, options=dot_options, output=known_args.filename, logger=logger)
    if known_args.svg:
        writer = writers.SVGWriter(graph, options=dot_options, output=known_args.filename, logger=logger)
    if known_args.html:
        writer = writers.HTMLWriter(graph, options=dot_options, output=known_args.filename, logger=logger)
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
