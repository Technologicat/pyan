"""Comprehension unpacking feature tests (PEP 798, Python 3.15+).

Uses tests/test_code_315/comprehensions.py.

The dict form is the one that used to crash: `{**mapping for x in xs}` parses to
`DictComp(key=mapping, value=None)`, and the analyzer visited `value`
unconditionally, so any analyzed codebase containing one raised AttributeError.

Edges are asserted on the comprehension's own inner scope node (``dictcomp.0`` and
friends) rather than on the enclosing function. Both carry the edge, but only the
inner one shows that the output expression itself was traversed.
"""

import logging
import os
import sys

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)

PREFIX = "test_code_315.comprehensions"

requires_315 = pytest.mark.skipif(
    sys.version_info < (3, 15), reason="comprehension unpacking requires Python 3.15+"
)


@pytest.fixture
def v315():
    filenames = [os.path.join(TESTS_DIR, "test_code_315/comprehensions.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


@requires_315
def test_dict_unpacking_analyzed(v315):
    """`{**make_mapping(k) for k in keys}` resolves the call in its mapping expression."""
    uses = get_in_dict(v315.uses_edges, f"{PREFIX}.merged.dictcomp.0")
    get_node(uses, f"{PREFIX}.make_mapping")


@requires_315
def test_starred_list_comprehension(v315):
    """`[*make_items(k) for k in keys]` resolves the call inside the starred element."""
    uses = get_in_dict(v315.uses_edges, f"{PREFIX}.flattened_list.listcomp.0")
    get_node(uses, f"{PREFIX}.make_items")


@requires_315
def test_starred_set_comprehension(v315):
    """`{*make_items(k) for k in keys}` resolves the call inside the starred element."""
    uses = get_in_dict(v315.uses_edges, f"{PREFIX}.flattened_set.setcomp.0")
    get_node(uses, f"{PREFIX}.make_items")


@requires_315
def test_starred_generator_expression(v315):
    """`(*make_items(k) for k in keys)` resolves the call inside the starred element."""
    uses = get_in_dict(v315.uses_edges, f"{PREFIX}.flattened_gen.genexpr.0")
    get_node(uses, f"{PREFIX}.make_items")


@requires_315
def test_ordinary_dict_comprehension_still_works(v315):
    """The `k: v` form still has its `value` expression traversed.

    Control for the unpacking fix: skipping the `value` field outright would
    pass the tests above and fail this one.
    """
    uses = get_in_dict(v315.uses_edges, f"{PREFIX}.ordinary_dict.dictcomp.0")
    get_node(uses, f"{PREFIX}.make_value")
