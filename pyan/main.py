#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
    pyan.py - Generate approximate call graphs for Python programs.

    This program takes one or more Python source files, does a superficial
    analysis, and constructs a directed graph of the objects in the combined
    source, and how they define or use each other.  The graph can be output
    for rendering by e.g. GraphViz or yEd.
"""

from argparse import ArgumentParser
from glob import glob
import io
import logging
import os
import signal
import sys

from .analyzer import CallGraphVisitor
from .anutils import expand_sources
from .visgraph import VisualGraph
from .writers import DotWriter, HTMLWriter, SVGWriter, TextWriter, TgfWriter, YedWriter


def _build_graph(filenames=None, root=None, sources=None, function=None, namespace=None,
                 max_iter=1000, direction="both", depth=None,
                 logger=None, graph_options=None):
    """Analyze source files, optionally filter, and build a VisualGraph.

    If `sources` is given (source mode / sans-IO mode), it overrides `filenames` and `root`.

    Shared core of ``create_callgraph()`` and ``main()``.
    """
    if sources is not None:
        v = CallGraphVisitor.from_sources(sources, logger=logger)
    else:
        v = CallGraphVisitor(filenames, root=root, logger=logger)
    if function or namespace:
        if function:
            function_name = function.split(".")[-1]
            function_namespace = ".".join(function.split(".")[:-1])
            node = v.get_node(function_namespace, function_name)
        else:
            node = None
        v.filter(node=node, namespace=namespace, max_iter=max_iter, direction=direction)
    if depth is not None:
        v.filter_by_depth(depth)
    return VisualGraph.from_visitor(v, options=graph_options, logger=logger)


def create_callgraph(
    filenames: list[str] | str = "**/*.py",
    root: str = None,
    sources: list[tuple] | None = None,
    function: str | None = None,
    namespace: str | None = None,
    format: str = "dot",
    rankdir: str = "LR",
    ranksep: str = "0.5",
    layout: str = "dot",
    nested_groups: bool = True,
    draw_defines: bool = True,
    draw_uses: bool = True,
    colored: bool = True,
    grouped_alt: bool = False,
    annotated: bool = False,
    grouped: bool = True,
    max_iter: int = 1000,
    direction: str = "both",
    concentrate: bool = False,
    depth: int | None = None,
    exclude: list[str] | None = None,
    logger=None,
) -> str:
    """Create a call graph based on static code analysis.

    Args:
        filenames: glob pattern or list of glob patterns
            to identify filenames to parse (``**`` for multiple directories).
            Example: ``**/*.py`` for all Python files.
        root: path to the package root directory. Defaults to ``None``
            (inferred automatically). Ignored when *sources* is given.
        sources: alternative to *filenames* and *root* — an iterable of
            ``(source, module_name)`` pairs for analysis without file I/O.
            *source* can be a ``str`` (source text) or ``ast.Module``
            (will be unparsed).  *module_name* must be the fully
            qualified dotted name (e.g. ``"pkg.sub.mod"``).  For
            package ``__init__`` modules, append ``.__init__``
            (e.g. ``"pkg.__init__"``) so that relative imports resolve
            correctly.  When given, *filenames*, *root*, and *exclude*
            are ignored.
        function: fully qualified function name to filter for, e.g.
            ``"my_module.my_function"``. Only calls related to this
            function will be included.
        namespace: namespace to filter for, e.g. ``"my_module"``.
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
        draw_defines: draw "defines" edges. A defines edge from A to B
            means A lexically contains the definition of B (e.g. a class
            containing a method, or a module containing a function).
            Rendered as dashed lines.
        draw_uses: draw "uses" edges. A uses edge from A to B means
            A references B — function calls, class instantiation,
            attribute access, and imports all generate uses edges.
            Rendered as solid lines.
        colored: color nodes by namespace (hue) and depth (lightness).
            [dot only]
        grouped_alt: emit invisible defines edges to nudge Graphviz's
            layout engine into placing structurally related nodes closer
            together, without actually drawing the defines edges.
            Useful with ``draw_defines=False`` to get defines-like
            clustering from the layout while showing only uses edges.
            [dot only]
        annotated: annotate nodes with source filename and line number.
        grouped: group nodes into subgraph clusters by namespace.
            [dot only]
        max_iter: maximum iterations for the graph filter. Defaults to 1000.
        direction: traversal direction when filtering by ``function`` or
            ``namespace`` — ``"both"`` (default), ``"down"`` (callees only),
            or ``"up"`` (callers only).
        concentrate: merge bidirectional edges into single double-headed
            arrows (GraphViz ``concentrate`` attribute). [dot/svg/html only]
        depth: collapse the graph to at most this many nesting levels.
            0 = modules only, 1 = + classes/top-level functions,
            2 = + methods. ``None`` (default) = full detail.
        exclude: list of exclusion patterns.  Patterns without a path
            separator match against the basename (e.g. ``"test_*.py"``);
            patterns with a separator match against the full path
            (e.g. ``"*/tests/*"``).
        logger: optional ``logging.Logger`` instance.

    Returns:
        The call graph as a string in the requested format.
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
        "draw_defines": draw_defines,
        "draw_uses": draw_uses,
        "colored": colored,
        "grouped_alt": grouped_alt,
        "grouped": grouped,
        "nested_groups": nested_groups,
        "annotated": annotated,
    }

    graph = _build_graph(filenames=filenames, root=root, sources=sources,
                         function=function, namespace=namespace,
                         max_iter=max_iter, direction=direction, depth=depth,
                         logger=logger, graph_options=graph_options)

    stream = io.StringIO()
    dot_options = ["rankdir=" + rankdir, "ranksep=" + ranksep, "layout=" + layout]
    if concentrate:
        dot_options.append("concentrate=true")
    if format == "dot":
        writer = DotWriter(graph, options=dot_options, output=stream, logger=logger)
    elif format == "html":
        writer = HTMLWriter(graph, options=dot_options, output=stream, logger=logger)
    elif format == "svg":
        writer = SVGWriter(graph, options=dot_options, output=stream, logger=logger)
    elif format == "tgf":
        writer = TgfWriter(graph, output=stream, logger=logger)
    elif format == "yed":
        writer = YedWriter(graph, output=stream, logger=logger)
    elif format == "text":
        writer = TextWriter(graph, output=stream, logger=logger)
    else:
        raise ValueError(f"Unknown format {format!r}; expected one of: dot, svg, html, tgf, yed, text")
    writer.run()

    return stream.getvalue()


def main(cli_args=None):
    # Exit cleanly on broken pipe (e.g. `pyan3 --dot file.py | head`).
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    if cli_args is None:
        cli_args = sys.argv[1:]

    # Handle --version before mode dispatch so it works with or without --module-level.
    if "--version" in cli_args:
        from . import __version__
        print(f"pyan3 {__version__}")
        return

    # Dispatch to module-level analysis mode before building the call-graph parser.
    if "--module-level" in cli_args:
        from .modvis import main as modvis_main
        return modvis_main([a for a in cli_args if a != "--module-level"])

    usage = """%(prog)s FILENAME... [--dot|--tgf|--yed|--svg|--html|--text]"""
    desc = (
        "Analyse one or more Python source files and generate an "
        "approximate call graph of the modules, classes and functions "
        "within them."
    )

    parser = ArgumentParser(usage=usage, description=desc)

    from . import __version__
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument("--dot", action="store_true", default=False, help="output in GraphViz dot format")

    parser.add_argument("--tgf", action="store_true", default=False, help="output in Trivial Graph Format")

    parser.add_argument("--svg", action="store_true", default=False, help="output in SVG Format")

    parser.add_argument("--html", action="store_true", default=False, help="output in HTML Format")

    parser.add_argument("--yed", action="store_true", default=False, help="output in yEd GraphML Format")

    parser.add_argument("--text", action="store_true", default=False, help="output in plain text")

    parser.add_argument("--file", dest="filename", help="write graph to FILE", metavar="FILE", default=None)

    parser.add_argument("--namespace", dest="namespace", help="filter for NAMESPACE", metavar="NAMESPACE", default=None)

    parser.add_argument("--function", dest="function", help="filter for FUNCTION", metavar="FUNCTION", default=None)

    parser.add_argument(
        "--direction",
        default="both",
        dest="direction",
        choices=["both", "down", "up"],
        help=(
            "filter traversal direction (requires --function or --namespace). "
            "'down' = callees only, 'up' = callers only, 'both' = default"
        ),
    )

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
        "-d",
        "--defines",
        action="store_true",
        default=True,
        dest="draw_defines",
        help="add edges for 'defines' relationships [default]",
    )

    parser.add_argument(
        "-n",
        "--no-defines",
        action="store_false",
        dest="draw_defines",
        help="do not add edges for 'defines' relationships",
    )

    parser.add_argument(
        "-u",
        "--uses",
        action="store_true",
        default=True,
        dest="draw_uses",
        help="add edges for 'uses' relationships [default]",
    )

    parser.add_argument(
        "-N",
        "--no-uses",
        action="store_false",
        dest="draw_uses",
        help="do not add edges for 'uses' relationships",
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
        "-G",
        "--grouped-alt",
        action="store_true",
        default=False,
        dest="grouped_alt",
        help="suggest grouping by adding invisible defines edges [only useful with --no-defines]",
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
        "--concentrate",
        action="store_true",
        default=False,
        dest="concentrate",
        help="merge bidirectional edges into a single double-headed arrow [dot/svg/html only]",
    )

    parser.add_argument(
        "-a",
        "--annotated",
        action="store_true",
        default=False,
        dest="annotated",
        help="annotate with module and source line number",
    )

    parser.add_argument(
        "--paths-from",
        default=None,
        dest="paths_from",
        metavar="FUNCTION",
        help="list call paths from FUNCTION to --paths-to target",
    )

    parser.add_argument(
        "--paths-to",
        default=None,
        dest="paths_to",
        metavar="FUNCTION",
        help="list call paths from --paths-from source to FUNCTION",
    )

    parser.add_argument(
        "--max-paths",
        default=100,
        type=int,
        dest="max_paths",
        help="maximum number of paths to list (default: 100)",
    )

    parser.add_argument(
        "--depth",
        default=None,
        dest="depth",
        help=(
            "collapse the graph to at most DEPTH nesting levels. "
            "0 = modules only, 1 = modules + classes/top-level functions, "
            "2 = + methods, 'max' = full detail (default)"
        ),
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

    parser.add_argument(
        "--module-level",
        action="store_true",
        default=False,
        dest="module_level",
        help="module-level import dependency analysis (use --module-level --help for full options)",
    )

    known_args, unknown_args = parser.parse_known_args(cli_args)

    filenames = [os.path.abspath(fn2) for fn2 in expand_sources(unknown_args, exclude=known_args.exclude)]

    # determine root
    root = os.path.abspath(known_args.root) if known_args.root is not None else None

    if len(unknown_args) == 0:
        parser.error("Need one or more filenames to process")
    elif len(filenames) == 0:
        parser.error("No files found matching given glob: {}".format(" ".join(unknown_args)))

    if known_args.nested_groups:
        known_args.grouped = True

    graph_options = {
        "draw_defines": known_args.draw_defines,
        "draw_uses": known_args.draw_uses,
        "colored": known_args.colored,
        "grouped_alt": known_args.grouped_alt,
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

    if root:
        root = os.path.abspath(root)

    # --paths-from / --paths-to: list call paths and exit.
    if known_args.paths_from and known_args.paths_to:
        v = CallGraphVisitor(filenames, root=root, logger=logger)
        src_ns, src_name = known_args.paths_from.rsplit(".", 1)
        tgt_ns, tgt_name = known_args.paths_to.rsplit(".", 1)
        from_node = v.get_node(src_ns, src_name)
        to_node = v.get_node(tgt_ns, tgt_name)
        paths = v.find_paths(from_node, to_node, max_paths=known_args.max_paths)
        if paths:
            print(v.format_paths(paths))
        else:
            print(f"No paths found from {known_args.paths_from} to {known_args.paths_to}.")
        return
    elif known_args.paths_from or known_args.paths_to:
        parser.error("--paths-from and --paths-to must both be specified")

    # Parse --depth: integer or "max" (= None internally).
    depth = None
    if known_args.depth is not None and known_args.depth != "max":
        try:
            depth = int(known_args.depth)
        except ValueError:
            parser.error(f"--depth must be an integer or 'max', got {known_args.depth!r}")

    graph = _build_graph(filenames, root=root, function=known_args.function,
                         namespace=known_args.namespace,
                         direction=known_args.direction, depth=depth,
                         logger=logger, graph_options=graph_options)

    writer = None
    dot_options = [
        "rankdir=" + known_args.rankdir,
        "ranksep=" + known_args.ranksep,
        "layout=" + known_args.layout,
    ]
    if known_args.concentrate:
        dot_options.append("concentrate=true")

    if known_args.dot:
        writer = DotWriter(graph, options=dot_options, output=known_args.filename, logger=logger)

    if known_args.html:
        writer = HTMLWriter(graph, options=dot_options, output=known_args.filename, logger=logger)

    if known_args.svg:
        writer = SVGWriter(graph, options=dot_options, output=known_args.filename, logger=logger)

    if known_args.tgf:
        writer = TgfWriter(graph, output=known_args.filename, logger=logger)

    if known_args.yed:
        writer = YedWriter(graph, output=known_args.filename, logger=logger)

    if known_args.text:
        writer = TextWriter(graph, output=known_args.filename, logger=logger)

    if writer:
        writer.run()


if __name__ == "__main__":
    main()
