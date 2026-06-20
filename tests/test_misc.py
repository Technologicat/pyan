"""Smaller-feature tests that don't form a large enough cluster of their own:
``del`` (attr / item / bare name), nested attribute access, string-literal
method calls, ``str()``/``repr()`` builtin resolution, and local-variable
noise suppression.

Uses tests/test_code/features.py.
"""

import logging
import os

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)
PREFIX = "test_code.features"


@pytest.fixture
def v():
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


# --- Del statement ---

def test_del_attr(v):
    """del registry.entry creates uses edge to Registry.__delattr__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.clear_entry")
    get_node(uses, f"{PREFIX}.Registry.__delattr__")


def test_del_item(v):
    """del registry["key"] creates uses edge to Registry.__delitem__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.remove_item")
    get_node(uses, f"{PREFIX}.Registry.__delitem__")


def test_del_name_no_protocol_edge(v):
    """del tmp (bare name) should not create protocol method edges."""
    # unbind_local has no uses edges at all — it shouldn't even appear as a key.
    names = [node.get_name() for node in v.uses_edges]
    assert f"{PREFIX}.unbind_local" not in names


# --- Nested attribute access ---

def test_nested_attr(v):
    """o.Inner.method() should create a uses edge to Inner.method."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.access_nested_attr")
    get_node(uses, f"{PREFIX}.Outer.Inner.method")


# --- String literal method ---

def test_string_method(v):
    """'hello'.upper() should create a uses edge to str.upper."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.call_string_method")
    names = [n.get_name() for n in uses]
    assert any("upper" in n for n in names)


# --- str()/repr() built-in resolution ---

def test_str_builtin_resolution(v):
    """str(p) should create a uses edge to Printable.__str__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_str_repr")
    get_node(uses, f"{PREFIX}.Printable.__str__")


def test_repr_builtin_resolution(v):
    """repr(p) should create a uses edge to Printable.__repr__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_str_repr")
    get_node(uses, f"{PREFIX}.Printable.__repr__")


# --- Local variable noise suppression ---

def test_local_no_unknown_node(v):
    """Unresolved local `x` should not produce a wildcard *.x uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.local_noise_example")
    # Should have a uses edge to len (the call), but NOT to *.x (the local).
    get_node(uses, "*.len")
    names = [n.get_name() for n in uses]
    assert not any(n.endswith(".x") for n in names)
