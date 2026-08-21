# Names its own package absolutely, where pkg_a/__init__.py uses the relative
# form. This one resolves to the package's own node, so it is where a self-loop
# would appear.
from pkg_b import beta  # noqa: F401  # test fixture

# A name that lives in the package itself, so that importing it depends on
# pkg_b and on no submodule of it.
PKG_B_CONST = 17
