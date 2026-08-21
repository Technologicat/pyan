# Depends on a package and on nothing else in it.
#
# Regression fixture for the bug where a dependency on a package itself was
# silently dropped: `PKG_B_CONST` is defined in pkg_b/__init__.py, so the only
# module this file needs is pkg_b — and the analyzed set knows that module as
# `pkg_b.__init__`, while the import records a dependency on `pkg_b`.

from pkg_b import PKG_B_CONST  # noqa: F401  # test fixture
