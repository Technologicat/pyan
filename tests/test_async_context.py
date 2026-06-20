"""Async and context-manager feature tests: with-statement protocol,
async function calls, and async-with protocol.

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


def test_context_manager(v):
    """with MyCtx() as ctx: creates uses edges to __enter__, __exit__, and constructor."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_ctx")
    get_node(uses, f"{PREFIX}.MyCtx")
    get_node(uses, f"{PREFIX}.MyCtx.__enter__")
    get_node(uses, f"{PREFIX}.MyCtx.__exit__")


def test_async_function_call(v):
    """async process() awaits fetch() -> uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.process")
    get_node(uses, f"{PREFIX}.fetch")


def test_async_with(v):
    """async with AsyncCM() creates uses edges to __aenter__ and __aexit__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_async_cm")
    get_node(uses, f"{PREFIX}.AsyncCM")
    get_node(uses, f"{PREFIX}.AsyncCM.__aenter__")
    get_node(uses, f"{PREFIX}.AsyncCM.__aexit__")
