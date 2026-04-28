"""Reads attributes off the namespace-style binding from #127's fixture."""

from namespace_module import store


def use_attr():
    return store.dataset


def write_attr(value):
    store.flag = value
