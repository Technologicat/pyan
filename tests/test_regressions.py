"""Regression tests for specific issues.

Issues #2, #3, #5 were originally just "does it crash" reproduction scripts.
Now they have proper assertions on the analyzer output.
"""

import logging
import os

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)


def test_issue2_annotated_assignment():
    """Issue #2: `a: int = 3` crashed visit_AnnAssign."""
    filenames = [os.path.join(TESTS_DIR, "old_tests/issue2/pyan_err.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # Module-level uses: `print(a + b)` and `int` from the annotation.
    uses = get_in_dict(v.uses_edges, "pyan_err")
    get_node(uses, "*.print")


def test_issue3_nested_comprehensions():
    """Issue #3: nested list/dict/generator comprehensions."""
    filenames = [os.path.join(TESTS_DIR, "old_tests/issue3/testi.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # All three functions are defined under the module.
    defines = get_in_dict(v.defines_edges, "testi")
    get_node(defines, "testi.f")
    get_node(defines, "testi.g")
    get_node(defines, "testi.h")

    # f and g both call range() inside their comprehensions.
    f_uses = get_in_dict(v.uses_edges, "testi.f")
    get_node(f_uses, "*.range")

    g_uses = get_in_dict(v.uses_edges, "testi.g")
    get_node(g_uses, "*.range")

    # h calls sorted() and .keys().
    h_uses = get_in_dict(v.uses_edges, "testi.h")
    get_node(h_uses, "*.sorted")


def test_issue5_external_deps_and_class_defs():
    """Issue #5: unresolvable external imports (numpy, pandas, plotly)
    should not crash the analyzer. Class and function definitions
    should still be found."""
    filenames = [
        os.path.join(TESTS_DIR, "old_tests/issue5/meas_xrd.py"),
        os.path.join(TESTS_DIR, "old_tests/issue5/plot_xrd.py"),
    ]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())

    # MeasXRD class is defined.
    meas_defines = get_in_dict(v.defines_edges, "tests.old_tests.issue5.meas_xrd.MeasXRD")
    get_node(meas_defines, "tests.old_tests.issue5.meas_xrd.MeasXRD.__init__")

    # plot_xrd function is defined.
    plot_defines = get_in_dict(v.defines_edges, "tests.old_tests.issue5.plot_xrd")
    get_node(plot_defines, "tests.old_tests.issue5.plot_xrd.plot_xrd")

    # External imports appear as wildcard uses (unresolvable but no crash).
    meas_uses = get_in_dict(v.uses_edges, "tests.old_tests.issue5.meas_xrd")
    get_node(meas_uses, "*.numpy")
    get_node(meas_uses, "*.pandas.io.parsers")


# --- Issue #88: wildcard expansion should respect imports ---

ISSUE88_DIR = os.path.join(TESTS_DIR, "test_code/issue88")
ISSUE88_DEFINES = os.path.join(ISSUE88_DIR, "defines_myfunc.py")
ISSUE88_PREFIX = "test_code.issue88"


def test_issue88_no_import_no_edge():
    """Issue #88: calling myfunc() without importing it should NOT create
    a cross-module edge to defines_myfunc.myfunc."""
    filenames = [os.path.join(ISSUE88_DIR, "no_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    all_targets = {n2.get_name() for n1 in v.uses_edges for n2 in v.uses_edges[n1]}
    assert f"{ISSUE88_PREFIX}.defines_myfunc.myfunc" not in all_targets


def test_issue88_with_import_has_edge():
    """Issue #88: calling myfunc() after importing it SHOULD create the edge."""
    filenames = [os.path.join(ISSUE88_DIR, "has_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    uses = get_in_dict(v.uses_edges, f"{ISSUE88_PREFIX}.has_import")
    get_node(uses, f"{ISSUE88_PREFIX}.defines_myfunc.myfunc")


def test_issue88_function_level_import():
    """Issue #88: a function-level import should create the edge for caller()."""
    filenames = [os.path.join(ISSUE88_DIR, "func_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # caller() imports myfunc and calls it — should have the edge.
    caller_uses = get_in_dict(v.uses_edges, f"{ISSUE88_PREFIX}.func_import.caller")
    get_node(caller_uses, f"{ISSUE88_PREFIX}.defines_myfunc.myfunc")

    # NOTE: Ideally non_caller() would NOT get the edge, since it doesn't
    # import myfunc. Currently resolve_imports maps the IMPORTEDITEM globally,
    # which also resolves non_caller's wildcard. Tightening this to per-scope
    # import resolution is a future improvement.
