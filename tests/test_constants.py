"""Reading a name bound to a literal resolves to the name, not to its type.

Binding `LIMIT = 42` to a Node standing for `int` made every read of `LIMIT`
point at `int` instead. The builtin types are never in the analyzed set, so
those edges were wildcards no output draws — and the constant, having no
incoming or outgoing uses edge of its own, was dropped from the graph as an
unused module-level name.
"""

import logging
import os

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)
PREFIX = "test_code.constants"


@pytest.fixture
def v():
    filenames = [os.path.join(TESTS_DIR, "test_code/constants.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


def uses_of(v, name):
    return {n.get_name() for n in get_in_dict(v.uses_edges, f"{PREFIX}.{name}")}


def test_reading_a_numeric_constant_reaches_the_constant(v):
    assert f"{PREFIX}.LIMIT" in uses_of(v, "read_number")


def test_reading_a_constant_does_not_reach_its_type(v):
    """`*.int` is undefined, so such an edge is drawn nowhere and says nothing."""
    assert not any(name.endswith((".int", ".str")) for name in uses_of(v, "read_number"))


def test_a_class_body_reading_a_constant_reaches_it(v):
    assert f"{PREFIX}.LIMIT" in uses_of(v, "Holder")


def test_container_constants_were_already_right(v):
    """A dict literal never bound a type, which is what made the two disagree."""
    assert f"{PREFIX}.TABLE" in uses_of(v, "read_mapping")


def test_enum_member_access_reaches_the_member(v):
    """Every enum member is a name bound to a literal, so all of them were lost."""
    uses = uses_of(v, "read_enum_member")
    assert f"{PREFIX}.Color.RED" in uses
    assert f"{PREFIX}.Color" in uses


def test_method_call_on_a_literal_expression_is_unaffected(v):
    """`"hello".upper()` resolves through `resolve_attribute`, not through binding."""
    assert "*.upper" in uses_of(v, "method_on_a_literal")


def test_an_unread_constant_is_still_defined_but_unused(v):
    """`UNUSED` keeps its Node; nothing points at it, so no output draws it."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.UNUSED")
    assert all(f"{PREFIX}.UNUSED" not in {n.get_name() for n in targets}
               for targets in v.uses_edges.values())
