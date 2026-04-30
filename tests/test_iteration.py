"""Iteration-related feature tests: for loops (sync and async),
comprehensions (list / set / dict / generator), iter-protocol edges,
multi-comprehension scope isolation, and for-else.

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
    return CallGraphVisitor(filenames, logger=logging.getLogger())


# --- For-loop call ---

def test_for_loop_call(v):
    """Function call inside for loop creates uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.process_items")
    get_node(uses, f"{PREFIX}.handle")


# --- Iterator protocol on for / async-for / comprehension ---

def test_for_iter_protocol(v):
    """for item in seq: creates uses edges to Sequence.__iter__ and __next__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.iterate_sequence")
    get_node(uses, f"{PREFIX}.Sequence.__iter__")
    get_node(uses, f"{PREFIX}.Sequence.__next__")


def test_async_for_iter_protocol(v):
    """async for chunk in stream: creates uses edges to AsyncStream.__aiter__ and __anext__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.iterate_async_stream")
    get_node(uses, f"{PREFIX}.AsyncStream.__aiter__")
    get_node(uses, f"{PREFIX}.AsyncStream.__anext__")


def test_comprehension_iter_protocol(v):
    """[x for x in seq] creates uses edges to Sequence.__iter__ and __next__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.comprehend_sequence")
    get_node(uses, f"{PREFIX}.Sequence.__iter__")
    get_node(uses, f"{PREFIX}.Sequence.__next__")


def test_setcomp_iter_protocol(v):
    """Set comprehension should create __iter__/__next__ edges."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_setcomp")
    get_node(uses, f"{PREFIX}.Sequence.__iter__")


def test_dictcomp_iter_protocol(v):
    """Dict comprehension should create __iter__/__next__ edges."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_dictcomp")
    get_node(uses, f"{PREFIX}.Sequence.__iter__")


def test_genexpr_iter_protocol(v):
    """Generator expression should create __iter__/__next__ edges."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_genexpr")
    get_node(uses, f"{PREFIX}.Sequence.__iter__")


# --- Multi-listcomp scope isolation (#110) ---

def test_multi_listcomp_isolated_scopes(v):
    """Two listcomps in the same function should get separate scope nodes."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.multi_listcomp")
    get_node(defines, f"{PREFIX}.multi_listcomp.listcomp.0")
    get_node(defines, f"{PREFIX}.multi_listcomp.listcomp.1")


# --- For-else ---

def test_for_else(v):
    """for-else: the else clause should create a uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.for_with_else")
    get_node(uses, "*.len")
