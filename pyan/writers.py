#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Graph markup writers."""

import io
import logging
import os
import subprocess
import sys

from jinja2 import Template


class Writer:
    def __init__(self, graph, output=None, logger=None, tabstop=4):
        self.graph = graph
        self.output = output
        self.logger = logger or logging.getLogger(__name__)
        self.indent_level = 0
        self.tabstop = tabstop * " "

    def log(self, msg):
        self.logger.info(msg)

    def indent(self, level=1):
        self.indent_level += level

    def dedent(self, level=1):
        self.indent_level -= level

    def write(self, line):
        self.outstream.write(self.tabstop * self.indent_level + line + "\n")

    def run(self):
        self.log(f"{type(self)} running")
        try:
            if isinstance(self.output, io.StringIO):  # write to stream
                self.outstream = self.output
            else:
                self.outstream = open(self.output, "w")  # noqa: SIM115 — closed in finally below
        except TypeError:
            self.outstream = sys.stdout
        self.start_graph()
        self.write_subgraph(self.graph)
        self.write_edges()
        self.finish_graph()
        if self.output and not isinstance(self.output, io.StringIO):
            self.outstream.close()

    def write_subgraph(self, graph):
        self.start_subgraph(graph)
        for node in graph.nodes:
            self.write_node(node)
        for subgraph in graph.subgraphs:
            self.write_subgraph(subgraph)
        self.finish_subgraph(graph)

    def write_edges(self):
        self.start_edges()
        for edge in sorted(self.graph.edges, key=lambda e: (e.source.id, e.target.id)):
            self.write_edge(edge)
        self.finish_edges()

    def start_graph(self):
        pass

    def start_subgraph(self, graph):
        pass

    def write_node(self, node):
        pass

    def start_edges(self):
        pass

    def write_edge(self, edge):
        pass

    def finish_edges(self):
        pass

    def finish_subgraph(self, graph):
        pass

    def finish_graph(self):
        pass


class TgfWriter(Writer):
    def __init__(self, graph, output=None, logger=None):
        Writer.__init__(self, graph, output=output, logger=logger)
        self.i = 1
        self.id_map = {}

    def write_node(self, node):
        self.write(f"{self.i} {node.label}")
        self.id_map[node] = self.i
        self.i += 1

    def start_edges(self):
        self.write("#")

    def write_edge(self, edge):
        flavor = "U" if edge.flavor == "uses" else "D"
        self.write(f"{self.id_map[edge.source]} {self.id_map[edge.target]} {flavor}")


class TextWriter(Writer):
    """Plain-text dependency list.

    Each node is printed with its outgoing edges indented below it,
    tagged ``[D]`` for defines or ``[U]`` for uses.
    """
    def run(self):
        self.log(f"{type(self)} running")
        try:
            if isinstance(self.output, io.StringIO):
                self.outstream = self.output
            else:
                self.outstream = open(self.output, "w")  # noqa: SIM115 — closed below
        except TypeError:
            self.outstream = sys.stdout

        # Build adjacency: source label → sorted list of (flavor, target label)
        adj = {}
        for edge in self.graph.edges:
            src = edge.source.label
            tgt = edge.target.label
            tag = "D" if edge.flavor == "defines" else "U"
            adj.setdefault(src, []).append((tag, tgt))

        for src in sorted(adj):
            self.outstream.write(src + "\n")
            for tag, tgt in sorted(adj[src]):
                self.outstream.write(f"    [{tag}] {tgt}\n")

        if self.output and not isinstance(self.output, io.StringIO):
            self.outstream.close()


class DotWriter(Writer):
    def __init__(self, graph, options=None, output=None, logger=None, tabstop=4):
        Writer.__init__(self, graph, output=output, logger=logger, tabstop=tabstop)
        options = options or []
        if graph.grouped:
            options += ['clusterrank="local"']
        self.options = ", ".join(options)
        self.grouped = graph.grouped

    def start_graph(self):
        self.write("digraph G {")
        self.write("    graph [" + self.options + "];")
        self.indent()

    def start_subgraph(self, graph):
        self.log(f"Start subgraph {graph.label}")
        # Name must begin with "cluster" to be recognized as a cluster by GraphViz.
        self.write("subgraph {} {{\n".format(self._dot_id("cluster_" + graph.id)))
        self.indent()

        # translucent gray (no hue to avoid visual confusion with any
        # group of colored nodes)
        self.write(f'graph [style="filled,rounded", fillcolor="#80808018", label="{graph.label}"];')

    def finish_subgraph(self, graph):
        self.log(f"Finish subgraph {graph.label}")
        # terminate previous subgraph
        self.dedent()
        self.write("}")

    @staticmethod
    def _dot_id(identifier):
        """Quote a DOT identifier so that special characters (dashes, etc.) are safe."""
        return '"{}"'.format(identifier.replace("\\", "\\\\").replace('"', '\\"'))

    def write_node(self, node):
        self.log(f"Write node {node.label}")
        tooltip_attr = f', tooltip="{node.tooltip}"' if node.tooltip else ""
        self.write(
            f'{self._dot_id(node.id)} [label="{node.label}", style="filled", fillcolor="{node.fill_color}",'
            f' fontcolor="{node.text_color}", group="{node.group}"{tooltip_attr}];'
        )

    def write_edge(self, edge):
        source = edge.source
        target = edge.target
        color = edge.color
        if edge.flavor == "defines":
            self.write(f'    {self._dot_id(source.id)} -> {self._dot_id(target.id)} [style="dashed",  color="{color}"];')
        else:  # edge.flavor == 'uses':
            self.write(f'    {self._dot_id(source.id)} -> {self._dot_id(target.id)} [style="solid",  color="{color}"];')

    def finish_graph(self):
        self.write("}")  # terminate "digraph G {"


class SVGWriter(DotWriter):
    def run(self):
        # write dot file
        self.log(f"{type(self)} running")
        self.outstream = io.StringIO()
        self.start_graph()
        self.write_subgraph(self.graph)
        self.write_edges()
        self.finish_graph()

        # convert to svg
        svg = subprocess.run(
            "dot -Tsvg", shell=True, stdout=subprocess.PIPE, input=self.outstream.getvalue().encode()
        ).stdout.decode()

        if self.output:
            if isinstance(self.output, io.StringIO):
                self.output.write(svg)
            else:
                with open(self.output, "w") as f:
                    f.write(svg)
        else:
            print(svg)


class HTMLWriter(SVGWriter):
    def run(self):
        with io.StringIO() as svg_stream:
            # run SVGWriter with stream as output
            output = self.output
            self.output = svg_stream
            super().run()
            svg = svg_stream.getvalue()
            self.output = output

        # insert svg into html
        with open(os.path.join(os.path.dirname(__file__), "callgraph.html")) as f:
            template = Template(f.read())

        html = template.render(svg=svg)
        if self.output:
            if isinstance(self.output, io.StringIO):
                self.output.write(html)
            else:
                with open(self.output, "w") as f:
                    f.write(html)
        else:
            print(html)


class YedWriter(Writer):
    def __init__(self, graph, output=None, logger=None, tabstop=2):
        Writer.__init__(self, graph, output=output, logger=logger, tabstop=tabstop)
        self.grouped = graph.grouped
        self.indent_level = 0
        self.edge_id = 0

    def start_graph(self):
        self.write('<?xml version="1.0" encoding="UTF-8" standalone="no"?>')
        self.write(
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"'
            " xmlns:java="
            '"http://www.yworks.com/xml/yfiles-common/1.0/java"'
            " xmlns:sys="
            '"http://www.yworks.com/xml/yfiles-common/markup/primitives'
            '/2.0" xmlns:x="http://www.yworks.com/xml/yfiles-common/'
            'markup/2.0" xmlns:xsi="http://www.w3.org/2001/'
            'XMLSchema-instance" xmlns:y="http://www.yworks.com/xml/'
            'graphml" xmlns:yed="http://www.yworks.com/xml/yed/3"'
            ' xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns'
            " http://www.yworks.com/xml/schema/graphml/1.1/"
            'ygraphml.xsd">'
        )
        self.indent()
        self.write('<key for="node" id="d0" yfiles.type="nodegraphics"/>')
        self.write('<key for="edge" id="d1" yfiles.type="edgegraphics"/>')
        self.write('<graph edgedefault="directed" id="Graph">')
        self.indent()

    def start_subgraph(self, graph):
        self.log(f"Start subgraph {graph.label}")

        self.write(f'<node id="{graph.id}:" yfiles.foldertype="group">')
        self.indent()
        self.write('<data key="d0">')
        self.indent()
        self.write("<y:ProxyAutoBoundsNode>")
        self.indent()
        self.write('<y:Realizers active="0">')
        self.indent()
        self.write("<y:GroupNode>")
        self.indent()
        self.write('<y:Fill color="#CCCCCC" transparent="false"/>')
        self.write(
            f'<y:NodeLabel modelName="internal" modelPosition="t" alignment="right">{graph.label}</y:NodeLabel>'
        )
        self.write('<y:Shape type="roundrectangle"/>')
        self.dedent()
        self.write("</y:GroupNode>")
        self.dedent()
        self.write("</y:Realizers>")
        self.dedent()
        self.write("</y:ProxyAutoBoundsNode>")
        self.dedent()
        self.write("</data>")
        self.write(f'<graph edgedefault="directed" id="{graph.id}::">')
        self.indent()

    def finish_subgraph(self, graph):
        self.log(f"Finish subgraph {graph.label}")
        self.dedent()
        self.write("</graph>")
        self.dedent()
        self.write("</node>")

    def write_node(self, node):
        self.log(f"Write node {node.label}")
        width = 20 + 10 * len(node.label)
        self.write(f'<node id="{node.id}">')
        self.indent()
        self.write('<data key="d0">')
        self.indent()
        self.write("<y:ShapeNode>")
        self.indent()
        self.write('<y:Geometry height="{}" width="{}"/>'.format("30", width))
        self.write(f'<y:Fill color="{node.fill_color}" transparent="false"/>')
        self.write('<y:BorderStyle color="#000000" type="line" width="1.0"/>')
        self.write(f"<y:NodeLabel>{node.label}</y:NodeLabel>")
        self.write('<y:Shape type="ellipse"/>')
        self.dedent()
        self.write("</y:ShapeNode>")
        self.dedent()
        self.write("</data>")
        self.dedent()
        self.write("</node>")

    def write_edge(self, edge):
        self.edge_id += 1
        source = edge.source
        target = edge.target
        self.write(f'<edge id="{self.edge_id}" source="{source.id}" target="{target.id}">')
        self.indent()
        self.write('<data key="d1">')
        self.indent()
        self.write("<y:PolyLineEdge>")
        self.indent()
        if edge.flavor == "defines":
            self.write(f'<y:LineStyle color="{edge.color}" type="dashed" width="1.0"/>')
        else:
            self.write(f'<y:LineStyle color="{edge.color}" type="line" width="1.0"/>')
        self.write('<y:Arrows source="none" target="standard"/>')
        self.write('<y:BendStyle smoothed="true"/>')
        self.dedent()
        self.write("</y:PolyLineEdge>")
        self.dedent()
        self.write("</data>")
        self.dedent()
        self.write("</edge>")

    def finish_graph(self):
        self.dedent(2)
        self.write("  </graph>")
        self.dedent()
        self.write("</graphml>")
