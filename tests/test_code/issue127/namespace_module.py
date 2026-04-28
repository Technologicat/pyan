"""Test fixture for #127: a module whose public surface is a namespace-style object.

The binding `store` is what other modules import, then read attributes on
(`store.dataset`, `store.flag`, ...). Those attributes are set at runtime,
so static analysis can't resolve them — the fallback should still attribute
the coupling to ``namespace_module.store`` (and, after depth-0 collapsing,
to ``namespace_module``).
"""


class _NS:
    pass


store = _NS()
