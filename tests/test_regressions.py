"""Regression tests for old crash demos (issues #2, #3, #5).

Each of these was originally just a "does it crash" reproduction script.
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
