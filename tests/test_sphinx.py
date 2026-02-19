"""Smoke tests for the Sphinx extension."""

import pytest

sphinx = pytest.importorskip("sphinx")
docutils = pytest.importorskip("docutils")

from pyan import sphinx as pyan_sphinx  # noqa: E402
from pyan.sphinx import CallgraphDirective  # noqa: E402


class FakeApp:
    """Minimal stand-in for a Sphinx application object."""

    def __init__(self):
        self.directives = {}
        self.js_files = []

    def add_directive(self, name, cls):
        self.directives[name] = cls

    def add_js_file(self, filename, **kwargs):
        self.js_files.append((filename, kwargs))


class TestSphinxSetup:
    def test_setup_returns_metadata(self):
        app = FakeApp()
        result = pyan_sphinx.setup(app)
        assert result["parallel_read_safe"] is True
        assert result["parallel_write_safe"] is True

    def test_setup_registers_callgraph_directive(self):
        app = FakeApp()
        pyan_sphinx.setup(app)
        assert "callgraph" in app.directives
        assert app.directives["callgraph"] is CallgraphDirective

    def test_setup_adds_js_files(self):
        app = FakeApp()
        pyan_sphinx.setup(app)
        # svg-pan-zoom CDN + inline init script
        assert len(app.js_files) == 2
        cdn_url, _ = app.js_files[0]
        assert "svg-pan-zoom" in cdn_url

    def test_directive_option_spec(self):
        """Verify that the directive declares the expected options."""
        expected = {
            "alt", "align", "caption", "name", "class",
            "no-groups", "no-defines", "no-uses", "no-colors",
            "nested-groups", "annotated", "direction",
            "toctree", "zoomable",
        }
        assert set(CallgraphDirective.option_spec.keys()) == expected


class TestSphinxImports:
    def test_graphviz_node_class(self):
        from sphinx.ext.graphviz import graphviz
        # graphviz is a docutils node class
        assert hasattr(graphviz, "__mro__")

    def test_figure_wrapper_callable(self):
        from sphinx.ext.graphviz import figure_wrapper
        assert callable(figure_wrapper)

    def test_align_spec_callable(self):
        from sphinx.ext.graphviz import align_spec
        assert callable(align_spec)
