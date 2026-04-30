"""Assignment-related feature tests: walrus operator, chained assignment,
positional star-unpacking, and AnnAssign annotation uses.

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


# --- Walrus operator ---

def test_walrus_uses_len(v):
    """Walrus `if (n := len(data))` creates uses edge to len."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.walrus_caller")
    get_node(uses, "*.len")


def test_walrus_uses_target(v):
    """After walrus binding, walrus_target(n) is called."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.walrus_caller")
    get_node(uses, f"{PREFIX}.walrus_target")


def test_walrus_attr_resolution(v):
    """Walrus-bound name resolves attribute access: (r := Result()).process()."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.walrus_method")
    get_node(uses, f"{PREFIX}.Result")
    get_node(uses, f"{PREFIX}.Result.process")


# --- Chained assignment ---

def test_chained_assign(v):
    """Chained assignment `a = b = Alpha()` should resolve through."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.chained_assign")
    get_node(uses, f"{PREFIX}.Alpha.alpha_method")


# --- Starred unpacking (positional matching) ---

def test_star_at_end(v):
    """a, b, *c = Alpha(), Beta(), Gamma(), Delta() — positional binding."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.star_at_end")
    # a binds to Alpha, b binds to Beta — positional, not Cartesian
    get_node(uses, f"{PREFIX}.Alpha.alpha_method")
    get_node(uses, f"{PREFIX}.Beta.beta_method")
    # alpha_method should NOT resolve on Beta (would happen with Cartesian)
    names = [n.get_name() for n in uses]
    assert f"{PREFIX}.Beta.alpha_method" not in names


def test_star_in_middle(v):
    """a, *b, c = Alpha(), Beta(), Gamma(), Delta() — positional binding."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.star_in_middle")
    # a binds to Alpha, c binds to Delta — positional
    get_node(uses, f"{PREFIX}.Alpha.alpha_method")
    get_node(uses, f"{PREFIX}.Delta.delta_method")
    names = [n.get_name() for n in uses]
    assert f"{PREFIX}.Delta.alpha_method" not in names


def test_star_at_start(v):
    """*a, b = Alpha(), Beta(), Gamma() — positional binding."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.star_at_start")
    # b binds to Gamma (last element) — positional
    get_node(uses, f"{PREFIX}.Gamma.gamma_method")
    names = [n.get_name() for n in uses]
    assert f"{PREFIX}.Alpha.gamma_method" not in names


# --- AnnAssign annotation uses ---

def test_annassign_annotation_uses(v):
    """result: MyType = None creates uses edge to MyType (from annotation)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.MyType")
