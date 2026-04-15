"""Smoke tests for the Sphinx extension."""

import subprocess
import sys
import textwrap

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
            "exclude", "toctree", "zoomable",
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


class TestSphinxBuildIntegration:
    def test_sphinx_build_renders_svg_output(self, tmp_path):
        # The body of a pretend `dot` executable: checks the invocation
        # looks like what Sphinx's graphviz extension emits, then writes
        # a minimal SVG to the output path.  Sphinx launches `graphviz_dot`
        # via subprocess without a shell, so on every platform we need a
        # real launchable file on disk.
        fake_dot_body = textwrap.dedent(
            """\
            import pathlib
            import sys

            args = sys.argv[1:]
            out = next((arg[2:] for arg in args if arg.startswith("-o")), None)
            fmt = next((arg[2:] for arg in args if arg.startswith("-T")), None)
            if fmt != "svg" or out is None:
                raise SystemExit(f"unexpected args: {args!r}")

            sys.stdin.read()
            pathlib.Path(out).write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"><text>fake graphviz render</text></svg>',
                encoding="utf-8",
            )
            """
        )

        if sys.platform == "win32":
            # Windows honors neither `#!` shebangs nor the executable bit, so
            # write the Python script separately and wrap it in a `.bat` that
            # forwards all arguments to the current interpreter.
            fake_dot_py = tmp_path / "fake_dot.py"
            fake_dot_py.write_text(fake_dot_body, encoding="utf-8")
            fake_dot = tmp_path / "fake-dot.bat"
            fake_dot.write_text(
                f'@echo off\r\n"{sys.executable}" "{fake_dot_py}" %*\r\n',
                encoding="utf-8",
            )
        else:
            # POSIX: single self-contained script with a shebang pointing at
            # the interpreter pytest is running under.
            fake_dot = tmp_path / "fake-dot"
            fake_dot.write_text(f"#!{sys.executable}\n{fake_dot_body}", encoding="utf-8")
            fake_dot.chmod(0o755)

        srcdir = tmp_path / "src"
        outdir = tmp_path / "build"
        srcdir.mkdir()

        (srcdir / "conf.py").write_text(
            textwrap.dedent(
                f"""\
                extensions = [
                    "sphinx.ext.graphviz",
                    "pyan.sphinx",
                ]
                master_doc = "index"
                project = "pyan-test"
                graphviz_output_format = "svg"
                graphviz_dot = r"{fake_dot}"
                """
            ),
            encoding="utf-8",
        )
        (srcdir / "index.rst").write_text(
            textwrap.dedent(
                """\
                Pyan Sphinx Test
                ================

                .. callgraph:: pyan.create_callgraph
                   :zoomable:
                   :direction: horizontal
                """
            ),
            encoding="utf-8",
        )

        command = [sys.executable, "-m", "sphinx", "-b", "html", str(srcdir), str(outdir)]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            pytest.fail(
                f"sphinx-build failed (exit {e.returncode})\n"
                f"--- stdout ---\n{e.stdout}\n"
                f"--- stderr ---\n{e.stderr}"
            )

        html = (outdir / "index.html").read_text(encoding="utf-8")
        assert "svg-pan-zoom" in html
        assert "zoomable-callgraph" in html
        assert '<object data="_images/graphviz-' in html
        assert 'type="image/svg+xml"' in html
        assert "rankdir=LR" in html

        images = list((outdir / "_images").glob("graphviz-*.svg"))
        assert len(images) == 1

        svg = images[0].read_text(encoding="utf-8")
        assert "fake graphviz render" in svg
        assert "<svg" in svg


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
