"""Regression tests for specific issues.

Issues #2, #3, #5 were originally just "does it crash" reproduction scripts.
Now they have proper assertions on the analyzer output.
"""

import logging
import os

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)


def test_standalone_file_bare_module_name():
    """A .py file outside any package should get a bare module name."""
    filenames = [os.path.join(TESTS_DIR, "test_code_no_package/standalone.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    defines = get_in_dict(v.defines_edges, "standalone")
    get_node(defines, "standalone.hello")


def test_issue2_annotated_assignment():
    """Issue #2: `a: int = 3` crashed visit_AnnAssign."""
    filenames = [os.path.join(TESTS_DIR, "test_code/issue2/pyan_err.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # Module-level uses: `print(a + b)` and `int` from the annotation.
    uses = get_in_dict(v.uses_edges, "pyan_err")
    get_node(uses, "*.print")


def test_issue3_nested_comprehensions():
    """Issue #3: nested list/dict/generator comprehensions."""
    filenames = [os.path.join(TESTS_DIR, "test_code/issue3/testi.py")]
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
        os.path.join(TESTS_DIR, "test_code/issue5/meas_xrd.py"),
        os.path.join(TESTS_DIR, "test_code/issue5/plot_xrd.py"),
    ]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())

    # MeasXRD class is defined.
    meas_defines = get_in_dict(v.defines_edges, "test_code.issue5.meas_xrd.MeasXRD")
    get_node(meas_defines, "test_code.issue5.meas_xrd.MeasXRD.__init__")

    # plot_xrd function is defined.
    plot_defines = get_in_dict(v.defines_edges, "test_code.issue5.plot_xrd")
    get_node(plot_defines, "test_code.issue5.plot_xrd.plot_xrd")

    # External imports appear as wildcard uses (unresolvable but no crash).
    meas_uses = get_in_dict(v.uses_edges, "test_code.issue5.meas_xrd")
    get_node(meas_uses, "*.numpy")
    get_node(meas_uses, "*.pandas.io.parsers")


# --- Issue #88: wildcard expansion should respect imports ---

ISSUE88_DIR = os.path.join(TESTS_DIR, "test_code/issue88")
ISSUE88_DEFINES = os.path.join(ISSUE88_DIR, "defines_myfunc.py")


def test_issue88_no_import_no_edge():
    """Issue #88: calling myfunc() without importing it should NOT create
    a cross-module edge to defines_myfunc.myfunc."""
    filenames = [os.path.join(ISSUE88_DIR, "no_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    all_targets = {n2.get_name() for n1 in v.uses_edges for n2 in v.uses_edges[n1]}
    assert "defines_myfunc.myfunc" not in all_targets


def test_issue88_with_import_has_edge():
    """Issue #88: calling myfunc() after importing it SHOULD create the edge."""
    filenames = [os.path.join(ISSUE88_DIR, "has_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    uses = get_in_dict(v.uses_edges, "has_import")
    get_node(uses, "defines_myfunc.myfunc")


def test_issue88_function_level_import():
    """Issue #88: a function-level import should create the edge for caller()
    but NOT for non_caller()."""
    filenames = [os.path.join(ISSUE88_DIR, "func_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # caller() imports myfunc and calls it — should have the edge.
    caller_uses = get_in_dict(v.uses_edges, "func_import.caller")
    get_node(caller_uses, "defines_myfunc.myfunc")

    # non_caller() does NOT import myfunc — should NOT have the edge.
    non_caller_targets = set()
    for n in v.uses_edges:
        if n.get_name() == "func_import.non_caller":
            non_caller_targets = {n2.get_name() for n2 in v.uses_edges[n]}
    assert "defines_myfunc.myfunc" not in non_caller_targets


def test_issue88_module_level_import_visible_to_all():
    """A module-level import should be visible to all functions in that module."""
    filenames = [os.path.join(ISSUE88_DIR, "module_import.py"), ISSUE88_DEFINES]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    a_uses = get_in_dict(v.uses_edges, "module_import.caller_a")
    get_node(a_uses, "defines_myfunc.myfunc")

    b_uses = get_in_dict(v.uses_edges, "module_import.caller_b")
    get_node(b_uses, "defines_myfunc.myfunc")


# --- Issue #117: namespace packages (no __init__.py) ---

ISSUE117_DIR = os.path.join(TESTS_DIR, "test_code/issue117")


def test_issue117_namespace_package_edge():
    """Issue #117: cross-module edges are lost when the target module
    lives in a namespace package (directory without __init__.py).

    dir1 (regular package) → dir2 (namespace package):
    func1 → func2 → func3 should all be connected.
    """
    filenames = [
        os.path.join(ISSUE117_DIR, "dir1", "file1.py"),
        os.path.join(ISSUE117_DIR, "dir2", "file2.py"),
        os.path.join(ISSUE117_DIR, "dir2", "file3.py"),
    ]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # func1 uses func2
    func1_uses = get_in_dict(v.uses_edges, "dir1.file1.func1")
    get_node(func1_uses, "dir2.file2.func2")

    # func2 uses func3
    func2_uses = get_in_dict(v.uses_edges, "dir2.file2.func2")
    get_node(func2_uses, "dir2.file3.func3")


# --- Issue #121: relative imports in __init__.py resolve incorrectly ---
#
# get_module_name() folds pkg/__init__.py → "pkg", but the rsplit logic
# in visit_ImportFrom always strips one dotted component for level-1
# imports.  That's correct for regular modules (strip filename to get
# parent package) but wrong for __init__ modules where the module name
# IS the package — they need zero levels stripped.
#
# Result: `from . import alpha` in pkg/sub/__init__.py resolves to
# pkg.alpha instead of pkg.sub.alpha.  The bug affects ALL __init__
# modules whose module name contains at least one dot (i.e. anything
# deeper than a single top-level package).

INIT_IMPORTS_DIR = os.path.join(TESTS_DIR, "test_code/init_imports")
INIT_IMPORTS_PREFIX = "test_code.init_imports"


def _init_imports_visitor():
    """Shared fixture: analyze the init_imports test package."""
    from glob import glob as globfunc

    filenames = sorted(globfunc(os.path.join(INIT_IMPORTS_DIR, "**/*.py"), recursive=True))
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


def test_init_imports_regular_module_relative_import():
    """Control: from . import alpha in a regular module (beta.py) works."""
    v = _init_imports_visitor()
    beta = f"{INIT_IMPORTS_PREFIX}.mypkg.sub.beta"
    beta_uses = get_in_dict(v.uses_edges, beta)
    get_node(beta_uses, f"{INIT_IMPORTS_PREFIX}.mypkg.sub.alpha")


def test_init_imports_nested_init_dot_import():
    """BUG: from . import alpha in sub/__init__.py should resolve to mypkg.sub.alpha."""
    v = _init_imports_visitor()
    sub_init = f"{INIT_IMPORTS_PREFIX}.mypkg.sub"
    sub_uses = get_in_dict(v.uses_edges, sub_init)
    get_node(sub_uses, f"{INIT_IMPORTS_PREFIX}.mypkg.sub.alpha")


def test_init_imports_nested_init_dotdot_import():
    """BUG: from .. import helpers in sub/__init__.py should resolve to mypkg.helpers."""
    v = _init_imports_visitor()
    sub_init = f"{INIT_IMPORTS_PREFIX}.mypkg.sub"
    sub_uses = get_in_dict(v.uses_edges, sub_init)
    get_node(sub_uses, f"{INIT_IMPORTS_PREFIX}.mypkg.helpers")


def test_init_imports_toplevel_init_dot_import():
    """BUG: from . import sub in mypkg/__init__.py should resolve to mypkg.sub."""
    v = _init_imports_visitor()
    mypkg_init = f"{INIT_IMPORTS_PREFIX}.mypkg"
    mypkg_uses = get_in_dict(v.uses_edges, mypkg_init)
    get_node(mypkg_uses, f"{INIT_IMPORTS_PREFIX}.mypkg.sub")


# --- Issue #125: decorator arguments should be attributed to the decorated function ---
#
# Python evaluates decorator expressions at definition time in the enclosing scope,
# so a decorator's argument uses naturally attach to the enclosing module. But for
# call-graph purposes, the *decorated function* also "uses" those names — e.g. in
# ``@app.get("/x", dependencies=[Depends(Guard())]) def fn(): ...`` the function
# fn is meaningfully tied to Depends and Guard, not just the module. Mirrors the
# treatment of default values.

ISSUE125_FILE = os.path.join(TESTS_DIR, "test_code/issue125/fastapi_style.py")


def test_issue125_decorator_args_attributed_to_function():
    """Names inside a decorator's call arguments should appear as uses of the
    decorated function, not only of the enclosing module."""
    v = CallGraphVisitor([ISSUE125_FILE], logger=logging.getLogger())

    secure_uses = get_in_dict(v.uses_edges, "fastapi_style.secure_route")
    # From the decorator call ``@route("/secure", dependencies=[depends(Guard())])``.
    get_node(secure_uses, "fastapi_style.depends")
    get_node(secure_uses, "fastapi_style.Guard")
    # The decorator function itself is also a use.
    get_node(secure_uses, "fastapi_style.route")


def test_issue125_bare_decorator_without_callable_args():
    """A decorator with no callable arguments should still attribute the
    decorator name to the function, but nothing spurious."""
    v = CallGraphVisitor([ISSUE125_FILE], logger=logging.getLogger())

    open_uses = get_in_dict(v.uses_edges, "fastapi_style.open_route")
    get_node(open_uses, "fastapi_style.route")
    target_names = {n.get_name() for n in open_uses}
    assert "fastapi_style.depends" not in target_names
    assert "fastapi_style.Guard" not in target_names


def test_issue125_mixed_decorator_and_default():
    """When a name appears in both a decorator argument and a default value,
    the function should still have exactly one edge to it (edges deduplicate)."""
    v = CallGraphVisitor([ISSUE125_FILE], logger=logging.getLogger())

    mixed_uses = get_in_dict(v.uses_edges, "fastapi_style.mixed_route")
    get_node(mixed_uses, "fastapi_style.depends")
    get_node(mixed_uses, "fastapi_style.Guard")
