"""Structural pattern-matching tests: class patterns, body calls,
guards, and or-patterns.

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


def test_match_class_pattern(v):
    """MatchClass patterns create uses edges to the matched classes."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_example")
    get_node(uses, f"{PREFIX}.Point")
    get_node(uses, f"{PREFIX}.Circle")


def test_match_class_str(v):
    """case str() as s: creates uses edge to str (builtin)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_example")
    get_node(uses, "*.str")


def test_match_body_calls(v):
    """Body functions inside match cases produce uses edges."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_example")
    get_node(uses, f"{PREFIX}.handle_point")
    get_node(uses, f"{PREFIX}.handle_circle")
    get_node(uses, f"{PREFIX}.handle_str")
    get_node(uses, f"{PREFIX}.handle_list")
    get_node(uses, f"{PREFIX}.handle_action")
    get_node(uses, f"{PREFIX}.handle_default")


def test_match_guard(v):
    """Match statement with guard should not crash and should process body."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_with_guard")
    get_node(uses, f"{PREFIX}.handle_point")


def test_match_or_pattern(v):
    """Match with `int() | float() as n` should process the or-pattern."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_with_guard")
    get_node(uses, f"{PREFIX}.handle_action")
