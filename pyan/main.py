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
from typing import List, Union

from .analyzer import CallGraphVisitor
from .visgraph import VisualGraph
from .writers import DotWriter, HTMLWriter, SVGWriter, TgfWriter, YedWriter


def _build_graph(filenames, root=None, function=None, namespace=None,
                 max_iter=1000, logger=None, graph_options=None):
    """Analyze source files, optionally filter, and build a VisualGraph.

    Shared core of ``create_callgraph()`` and ``main()``.
    """
    v = CallGraphVisitor(filenames, root=root, logger=logger)
    if function or namespace:
        if function:
            function_name = function.split(".")[-1]
            function_namespace = ".".join(function.split(".")[:-1])
            node = v.get_node(function_namespace, function_name)
        else:
            node = None
        v.filter(node=node, namespace=namespace, max_iter=max_iter)
    return VisualGraph.from_visitor(v, options=graph_options, logger=logger)


def create_callgraph(
    filenames: Union[List[str], str] = "**/*.py",
    root: str = None,
    function: Union[str, None] = None,
    namespace: Union[str, None] = None,
    format: str = "dot",
    rankdir: str = "LR",
    nested_groups: bool = True,
    draw_defines: bool = True,
    draw_uses: bool = True,
    colored: bool = True,
    grouped_alt: bool = False,
    annotated: bool = False,
    grouped: bool = True,
    max_iter: int = 1000,
    logger=None,
) -> str:
    """
    create callgraph based on static code analysis

    Args:
        filenames: glob pattern or list of glob patterns
            to identify filenames to parse (`**` for multiple directories)
            example: **/*.py for all python files
        root: path to known root directory at which package root sits. Defaults to None, i.e. it will be inferred.
        function: if defined, function name to filter for, e.g. "my_module.my_function"
            to only include calls that are related to `my_function`
        namespace: if defined, namespace to filter for, e.g. "my_module", it is highly
            recommended to define this filter
        format: format to write callgraph to, of of "dot", "svg", "html". you need to have graphviz
            installed for svg or html output
        rankdir: direction of graph, e.g. "LR" for horizontal or "TB" for vertical
        nested_groups: if to group by modules and submodules
        draw_defines: if to draw defines edges (functions that are defines)
        draw_uses: if to draw uses edges (functions that are used)
        colored: if to color graph
        grouped_alt: if to use alternative grouping
        annotated: if to annotate graph with filenames
        grouped: if to group by modules
        max_iter: maximum number of iterations for filtering. Defaults to 1000.
        logger: optional logging.Logger instance

    Returns:
        str: callgraph
    """
    if isinstance(filenames, str):
        filenames = [filenames]
    filenames = [fn2 for fn in filenames for fn2 in glob(fn, recursive=True)]

    if nested_groups:
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

    graph = _build_graph(filenames, root=root, function=function,
                         namespace=namespace, max_iter=max_iter,
                         logger=logger, graph_options=graph_options)

    stream = io.StringIO()
    if format == "dot":
        writer = DotWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
        writer.run()
    elif format == "html":
        writer = HTMLWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
        writer.run()
    elif format == "svg":
        writer = SVGWriter(graph, options=["rankdir=" + rankdir], output=stream, logger=logger)
        writer.run()
    else:
        raise ValueError(f"format {format} is unknown")

    return stream.getvalue()


def main(cli_args=None):
    usage = """%(prog)s FILENAME... [--dot|--tgf|--yed|--svg|--html]"""
    desc = (
        "Analyse one or more Python source files and generate an"
        "approximate call graph of the modules, classes and functions"
        " within them."
    )

    parser = ArgumentParser(usage=usage, description=desc)

    parser.add_argument("--dot", action="store_true", default=False, help="output in GraphViz dot format")

    parser.add_argument("--tgf", action="store_true", default=False, help="output in Trivial Graph Format")

    parser.add_argument("--svg", action="store_true", default=False, help="output in SVG Format")

    parser.add_argument("--html", action="store_true", default=False, help="output in HTML Format")

    parser.add_argument("--yed", action="store_true", default=False, help="output in yEd GraphML Format")

    parser.add_argument("--file", dest="filename", help="write graph to FILE", metavar="FILE", default=None)

    parser.add_argument("--namespace", dest="namespace", help="filter for NAMESPACE", metavar="NAMESPACE", default=None)

    parser.add_argument("--function", dest="function", help="filter for FUNCTION", metavar="FUNCTION", default=None)

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
        dest="draw_defines",
        help="add edges for 'defines' relationships [default]",
    )

    parser.add_argument(
        "-n",
        "--no-defines",
        action="store_false",
        default=True,
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
        default=True,
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
        "-a",
        "--annotated",
        action="store_true",
        default=False,
        dest="annotated",
        help="annotate with module and source line number",
    )

    parser.add_argument(
        "--root",
        default=None,
        dest="root",
        help="Package root directory. Is inferred by default.",
    )

    known_args, unknown_args = parser.parse_known_args(cli_args)

    filenames = [os.path.abspath(fn2) for fn in unknown_args for fn2 in glob(fn, recursive=True)]

    # determine root
    if known_args.root is not None:
        root = os.path.abspath(known_args.root)
    else:
        root = None

    if len(unknown_args) == 0:
        parser.error("Need one or more filenames to process")
    elif len(filenames) == 0:
        parser.error("No files found matching given glob: %s" % " ".join(unknown_args))

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

    graph = _build_graph(filenames, root=root, function=known_args.function,
                         namespace=known_args.namespace, logger=logger,
                         graph_options=graph_options)

    writer = None

    if known_args.dot:
        writer = DotWriter(graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger)

    if known_args.html:
        writer = HTMLWriter(graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger)

    if known_args.svg:
        writer = SVGWriter(graph, options=["rankdir=" + known_args.rankdir], output=known_args.filename, logger=logger)

    if known_args.tgf:
        writer = TgfWriter(graph, output=known_args.filename, logger=logger)

    if known_args.yed:
        writer = YedWriter(graph, output=known_args.filename, logger=logger)

    if writer:
        writer.run()


if __name__ == "__main__":
    main()
