"""A file Python would not compile is left out with a warning, and the rest is still analyzed.

Two ways a file fails: it does not parse, or it parses and is rejected by the compiler's scoping
check — a `nonlocal` after an assignment, say, which code using macros can contain before expansion.
The module graph does not consult scopes, so only the first applies to it.
"""

import logging

from pyan.analyzer import CallGraphVisitor
from pyan.modvis import ImportVisitor

GOOD = "def g():\n    pass\n"
BAD_SYNTAX = "def f(:\n"
BAD_SCOPE = "def f():\n    x = 1\n    nonlocal x\n"


def _write(tmp_path, **sources):
    for name, text in sources.items():
        (tmp_path / f"{name}.py").write_text(text)
    return [str(tmp_path / f"{name}.py") for name in sources]


def _skip_warnings(caplog):
    return [r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and "leaving this file out" in r.getMessage()]


def test_callgraph_leaves_out_what_does_not_compile(tmp_path, caplog):
    files = _write(tmp_path, good=GOOD, bad_syntax=BAD_SYNTAX, bad_scope=BAD_SCOPE)
    v = CallGraphVisitor(files, root=str(tmp_path), logger=logging.getLogger("pyan-test"))
    warnings = _skip_warnings(caplog)
    assert len(warnings) == 2, f"expected both bad files reported: {warnings}"
    assert any("bad_syntax.py:1:" in w for w in warnings)
    assert any("bad_scope.py:3:" in w and "nonlocal" in w for w in warnings)
    defined = {n.get_name() for targets in v.defines_edges.values() for n in targets}
    assert "good.g" in defined
    assert not any(name.startswith(("bad_syntax", "bad_scope")) for name in defined)


def test_callgraph_from_sources_leaves_out_what_does_not_compile(caplog):
    v = CallGraphVisitor.from_sources([(GOOD, "good"), (BAD_SCOPE, "bad_scope")],
                                      logger=logging.getLogger("pyan-test"))
    assert len(_skip_warnings(caplog)) == 1
    assert "good.g" in {n.get_name() for targets in v.defines_edges.values() for n in targets}


def test_modulegraph_leaves_out_what_does_not_parse(tmp_path, caplog):
    files = _write(tmp_path, good=GOOD, bad_syntax=BAD_SYNTAX, user="import good\nimport bad_syntax\n")
    v = ImportVisitor(files, logger=logging.getLogger("pyan-test"), root=str(tmp_path))
    assert len(_skip_warnings(caplog)) == 1
    # Not drawn as a module importing nothing: what it imports is unknown.
    assert set(v.modules) == {"good", "user"}


def test_modulegraph_from_sources_leaves_out_what_does_not_parse(caplog):
    v = ImportVisitor.from_sources([(GOOD, "good"), (BAD_SYNTAX, "bad_syntax")],
                                   logger=logging.getLogger("pyan-test"))
    assert len(_skip_warnings(caplog)) == 1
    assert "bad_syntax" not in v.modules
