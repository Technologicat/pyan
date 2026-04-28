"""Chained attribute access through a namespace-style binding (#127).

Neither ``foo`` nor ``bar`` exists statically on ``store``; the fallback
should attribute the coupling to the nearest defined ancestor — ``store``
itself — and emit exactly one edge to it (no edges to undefined intermediate
synthetic nodes).
"""

from namespace_module import store


def use_chained():
    return store.foo.bar
