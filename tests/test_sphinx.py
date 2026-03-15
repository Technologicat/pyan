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


class TestCallgraphDirectiveRun:
    """Test CallgraphDirective.run() with a mock environment."""

    def _make_directive(self, content, options=None):
        """Create a CallgraphDirective with minimal mocking.

        Uses object.__setattr__ to bypass Sphinx's property descriptors.
        """
        from unittest.mock import MagicMock

        directive = CallgraphDirective.__new__(CallgraphDirective)
        object.__setattr__(directive, "content", content)
        object.__setattr__(directive, "options", options or {})
        object.__setattr__(directive, "lineno", 1)

        state = MagicMock()
        env = MagicMock()
        env.docname = "test"
        state.document.settings.env = env
        object.__setattr__(directive, "state", state)
        object.__setattr__(directive, "state_machine", MagicMock())

        return directive

    def test_run_basic(self):
        """Run with pyan as the target package (it's importable)."""
        directive = self._make_directive(["pyan"])
        result = directive.run()
        assert len(result) == 1
        node = result[0]
        assert "digraph G" in node["code"]

    def test_run_with_direction(self):
        directive = self._make_directive(["pyan"], {"direction": "horizontal"})
        result = directive.run()
        assert "rankdir=LR" in result[0]["code"]

    def test_run_no_groups(self):
        directive = self._make_directive(["pyan"], {"no-groups": ""})
        result = directive.run()
        assert "digraph G" in result[0]["code"]

    def test_run_annotated(self):
        directive = self._make_directive(["pyan"], {"annotated": ""})
        result = directive.run()
        assert "digraph G" in result[0]["code"]

    def test_run_with_caption(self):
        from unittest.mock import MagicMock, patch
        directive = self._make_directive(["pyan"], {"caption": "My Graph"})
        # figure_wrapper returns a mock figure node
        with patch("pyan.sphinx.figure_wrapper") as mock_fw:
            mock_fw.return_value = MagicMock()
            directive.run()
            mock_fw.assert_called_once()

    def test_run_with_zoomable(self):
        directive = self._make_directive(["pyan"], {"zoomable": ""})
        result = directive.run()
        assert "zoomable-callgraph" in result[0].get("classes", [])


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
