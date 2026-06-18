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


def test_issue125_class_decorator_bare():
    """Class decorators were previously ignored entirely. The decorator name
    should now appear as a use of the decorated class."""
    v = CallGraphVisitor([ISSUE125_FILE], logger=logging.getLogger())

    api_uses = get_in_dict(v.uses_edges, "fastapi_style.ApiHandler")
    get_node(api_uses, "fastapi_style.route")


def test_issue125_class_decorator_with_callable_args():
    """Names inside a class decorator's arguments should be attributed to the
    decorated class, mirroring the function-decorator behavior."""
    v = CallGraphVisitor([ISSUE125_FILE], logger=logging.getLogger())

    secure_uses = get_in_dict(v.uses_edges, "fastapi_style.SecureApiHandler")
    get_node(secure_uses, "fastapi_style.route")
    get_node(secure_uses, "fastapi_style.depends")
    get_node(secure_uses, "fastapi_style.Guard")


# --- Issue #126: name lookups through __init__.py re-exports and wildcard imports ---
#
# When a package's __init__.py re-exports names from submodules
# (``from .file2 import fn2``) or a downstream module imports via wildcard
# (``from pkg import *``), pyan should resolve the call back to the actual
# defining submodule — ``pkg.file2.fn2``, not ``pkg.fn2`` or ``*.fn2``.

ISSUE126_DIR = os.path.join(TESTS_DIR, "test_code/issue126")
ISSUE126_PREFIX = "test_code.issue126"


def _issue126_visitor():
    from glob import glob as globfunc

    filenames = sorted(globfunc(os.path.join(ISSUE126_DIR, "**/*.py"), recursive=True))
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


def test_issue126_direct_submodule_import():
    """Control: ``from common.file1 import fn1`` already works — the import path
    itself carries the full dotted location."""
    v = _issue126_visitor()
    fn_parent = f"{ISSUE126_PREFIX}.test_sample.fn_parent"
    uses = get_in_dict(v.uses_edges, fn_parent)
    get_node(uses, f"{ISSUE126_PREFIX}.common.file1.fn1")


def test_issue126_package_reexport_resolves_to_submodule():
    """``from common import fn2`` where common/__init__.py does
    ``from .file2 import fn2`` should resolve to ``common.file2.fn2``."""
    v = _issue126_visitor()
    fn_parent = f"{ISSUE126_PREFIX}.test_sample.fn_parent"
    uses = get_in_dict(v.uses_edges, fn_parent)
    get_node(uses, f"{ISSUE126_PREFIX}.common.file2.fn2")


def test_issue126_wildcard_import_resolves_to_submodule():
    """``from common import *`` plus a bare ``fn3()`` call should resolve to
    ``common.file3.fn3`` — the wildcard brings in names re-exported by
    common/__init__.py."""
    v = _issue126_visitor()
    fn_parent = f"{ISSUE126_PREFIX}.test_sample.fn_parent"
    uses = get_in_dict(v.uses_edges, fn_parent)
    get_node(uses, f"{ISSUE126_PREFIX}.common.file3.fn3")


def test_issue126_no_spurious_wildcard_edge_at_module_level():
    """After wildcard desugaring (v2.5), ``from common import *`` should not
    leave a ``*.*`` residue edge at the importer's module level."""
    v = _issue126_visitor()
    mod_uses = get_in_dict(v.uses_edges, f"{ISSUE126_PREFIX}.test_sample")
    targets = {n.get_name() for n in mod_uses}
    assert "*.*" not in targets, f"unexpected wildcard residue: {sorted(targets)}"


# --- Wildcard imports: __all__ vs. public-names rule ---

DUNDER_ALL_DIR = os.path.join(TESTS_DIR, "test_code/dunder_all")
DUNDER_ALL_PREFIX = "test_code.dunder_all"


def _dunder_all_visitor():
    from glob import glob as globfunc

    filenames = sorted(globfunc(os.path.join(DUNDER_ALL_DIR, "**/*.py"), recursive=True))
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


def test_dunder_all_literal_governs_wildcard():
    """With literal ``__all__ = ["alpha", "_helper"]`` in the package, a
    downstream ``from pkg_with_all import *; alpha(); _helper()`` should
    resolve both — ``__all__`` is authoritative and overrides the default
    underscore-is-private rule."""
    v = _dunder_all_visitor()
    use = f"{DUNDER_ALL_PREFIX}.consumer.use_with_all"
    uses = get_in_dict(v.uses_edges, use)
    get_node(uses, f"{DUNDER_ALL_PREFIX}.pkg_with_all.exports.alpha")
    get_node(uses, f"{DUNDER_ALL_PREFIX}.pkg_with_all.exports._helper")


def test_dunder_all_literal_excludes_unlisted_names():
    """Names bound in the module but absent from ``__all__`` should not be
    reachable through ``import *``. ``beta`` and ``gamma`` are imported into
    pkg_with_all's namespace but not listed, so consumer's wildcard shouldn't
    bind them — there should be no edge from use_with_all to beta/gamma."""
    v = _dunder_all_visitor()
    use = f"{DUNDER_ALL_PREFIX}.consumer.use_with_all"
    uses = get_in_dict(v.uses_edges, use)
    targets = {n.get_name() for n in uses}
    assert f"{DUNDER_ALL_PREFIX}.pkg_with_all.exports.beta" not in targets
    assert f"{DUNDER_ALL_PREFIX}.pkg_with_all.exports.gamma" not in targets


def test_public_names_rule_without_dunder_all():
    """When ``__all__`` is absent, wildcard brings in every non-underscore
    name bound at module scope. ``pub`` should resolve; ``_priv`` should not
    — it's leading-underscore and not whitelisted."""
    v = _dunder_all_visitor()
    use = f"{DUNDER_ALL_PREFIX}.consumer.use_private"
    uses = get_in_dict(v.uses_edges, use)
    get_node(uses, f"{DUNDER_ALL_PREFIX}.pkg_private.exports.pub")


def test_dunder_all_recorded_only_when_literal():
    """The extractor should record pkg_with_all's __all__ but leave
    pkg_private absent (no __all__ statement at all)."""
    v = _dunder_all_visitor()
    assert f"{DUNDER_ALL_PREFIX}.pkg_with_all" in v.module_all
    assert v.module_all[f"{DUNDER_ALL_PREFIX}.pkg_with_all"] == {"alpha", "_helper"}
    assert f"{DUNDER_ALL_PREFIX}.pkg_private" not in v.module_all


# --- Issue #127: cross-module attribute access on namespace-style bindings ---

ISSUE127_DIR = os.path.join(TESTS_DIR, "test_code/issue127")


def _issue127_visitor(*basenames):
    filenames = [os.path.join(ISSUE127_DIR, b) for b in basenames]
    return CallGraphVisitor(filenames, logger=logging.getLogger())


def test_issue127_unresolved_attr_read_emits_edge_to_binding():
    """Reading ``store.dataset`` where ``dataset`` isn't statically known
    should still produce a uses edge to ``namespace_module.store`` (the
    binding), so the cross-module coupling stays visible. The binding is
    a defined ``Flavor.NAME`` Node, so the edge lands on it directly —
    no climb needed. (Pre-#129-prequisite, the binding wasn't a Node and
    the edge had to fall back to the enclosing module.)"""
    v = _issue127_visitor("namespace_module.py", "consumer.py")
    uses = get_in_dict(v.uses_edges, "consumer.use_attr")
    get_node(uses, "namespace_module.store")


def test_issue127_unresolved_attr_write_emits_edge_to_binding():
    """Writing ``store.flag = value`` should also produce the
    binding-level edge — same mechanism, applied through
    ``set_attribute`` / the Attribute-in-Store path."""
    v = _issue127_visitor("namespace_module.py", "consumer.py")
    uses = get_in_dict(v.uses_edges, "consumer.write_attr")
    get_node(uses, "namespace_module.store")


def test_issue127_chained_access_climbs_to_defined_ancestor():
    """``store.foo.bar`` — neither ``foo`` nor ``bar`` is statically known.
    The intermediate access ``store.foo`` produces an undefined synthetic
    ATTRIBUTE Node, and the outer ``.bar`` access has to climb past it to
    reach a defined ancestor. After the prequisite to #129, the climb
    terminates at ``namespace_module.store`` (the binding's NAME Node)
    rather than at the enclosing module. No edges should point at the
    undefined ATTRIBUTE intermediates — those are invisible in the
    rendered graph and just noise in ``uses_edges``."""
    v = _issue127_visitor("namespace_module.py", "chained_consumer.py")
    uses = get_in_dict(v.uses_edges, "chained_consumer.use_chained")
    get_node(uses, "namespace_module.store")
    # No edges to undefined non-wildcard nodes (e.g. namespace_module.store.foo).
    for n in uses:
        assert n.defined or n.namespace is None, (
            f"Unexpected edge to undefined non-wildcard node {n.get_name()}"
        )


def test_issue127_no_double_counting_on_resolved_call():
    """``defines_func.myfunc()`` — the attr resolves to a real defined
    function. There should be exactly one uses edge from ``calls_func.caller``
    to ``defines_func.myfunc``, with no fallback edge to the module (since
    the attr resolved cleanly). Locks in the no-double-counting invariant."""
    v = _issue127_visitor("defines_func.py", "calls_func.py")
    uses = get_in_dict(v.uses_edges, "calls_func.caller")
    get_node(uses, "defines_func.myfunc")
    targets = {n.get_name() for n in uses}
    assert "defines_func" not in targets, (
        "Unexpected fallback edge to module when attr resolved to a defined Node"
    )


def test_issue127_within_class_self_reference_suppressed():
    """A method reading an undefined attribute on its own class should
    NOT produce a fallback edge to the class — that's just normal scoping
    inside the class, not a coupling worth surfacing.  Same for writes."""
    v = _issue127_visitor("within_scope.py")
    read_uses = get_in_dict(v.uses_edges, "within_scope.Holder.reads_self")
    targets = {n.get_name() for n in read_uses}
    assert "within_scope.Holder" not in targets, (
        "Within-class self-read should not emit fallback edge to its own class"
    )
    write_uses = get_in_dict(v.uses_edges, "within_scope.Holder.writes_self")
    targets = {n.get_name() for n in write_uses}
    assert "within_scope.Holder" not in targets, (
        "Within-class self-write should not emit fallback edge to its own class"
    )


def test_issue127_cross_class_reference_still_emits():
    """A method reading an undefined attribute on a *different* class in
    the same module SHOULD still emit the fallback edge — the suppression
    only kicks in for within-scope references, not for sibling coupling."""
    v = _issue127_visitor("within_scope.py")
    uses = get_in_dict(v.uses_edges, "within_scope.Sibling.reads_holder")
    get_node(uses, "within_scope.Holder")


# --- Issue #134: Wildcard expansion creates false uses edges to unrelated functions in the same module ---


WILDCARD_DIR = os.path.join(TESTS_DIR, "test_code/issue_wildcard")

def _wildcard_visitor():
    filenames = [os.path.join(WILDCARD_DIR, "test_module.py")]
    return CallGraphVisitor(filenames, logger=logging.getLogger())

def test_wildcard_expansion_does_not_create_false_edges():
    """Regression test: wildcard should not expand to unrelated functions.

    This tests the fix for the ``expand_unknowns`` over-expansion bug, where
    a wildcard created by an attribute access (e.g. ``app.state.cache``) was
    incorrectly expanded to a function with the same name, even though the
    name wasn't used in that scope.
    """
    v = _wildcard_visitor()
    func_a_uses = get_in_dict(v.uses_edges, "test_module.func_a")
    targets = {n.get_name() for n in func_a_uses}
    # The wildcard *.cache should NOT expand to the function cache().
    assert "test_module.cache" not in targets