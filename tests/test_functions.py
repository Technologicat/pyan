"""Function-related feature tests: lambdas, closures, defaults
(positional, keyword-only, lambda/call/func-as-default), multi-lambda
scope isolation, and function-signature annotations (arg & return).

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


# --- Lambda / closure ---

def test_lambda_definition(v):
    """Lambda is defined as a child of the enclosing function."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.make_adder")
    get_node(defines, f"{PREFIX}.make_adder.lambda.0")


def test_closure_definition(v):
    """Inner function defined within outer; outer calls inner."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.outer")
    get_node(defines, f"{PREFIX}.outer.inner")

    uses = get_in_dict(v.uses_edges, f"{PREFIX}.outer")
    get_node(uses, f"{PREFIX}.outer.inner")


# --- Defaults (#61, #116) ---

def test_lambda_default_no_crash(v):
    """A lambda used as a default argument value must not crash the analyzer."""
    # The function should be defined.
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.func_with_lambda_default")


def test_call_in_default_no_crash(v):
    """A function call used as a default argument value must not crash the analyzer."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.func_with_call_default")


def test_function_as_default_arg_uses(v):
    """Function passed as arg in a default value should create uses edges from the function (#116)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.func_with_func_as_default_arg")
    get_node(uses, f"{PREFIX}.wrapper")
    get_node(uses, f"{PREFIX}.identity")


def test_kwonly_defaults_defined(v):
    """Function with keyword-only default args should be defined."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.kwonly_defaults")


def test_lambda_with_defaults(v):
    """Lambda with positional default should be defined."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.lambda.0")


# --- Multi-lambda scope isolation (#110) ---

def test_multi_lambda_isolated_scopes(v):
    """Two lambdas in the same function should get separate scope nodes."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.multi_lambda")
    get_node(defines, f"{PREFIX}.multi_lambda.lambda.0")
    get_node(defines, f"{PREFIX}.multi_lambda.lambda.1")


# --- Function-signature annotations ---

def test_funcdef_arg_annotation_uses(v):
    """def annotated_func(x: MyType) creates uses edge to MyType (from arg annotation)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.MyType")


def test_funcdef_return_annotation_uses(v):
    """def annotated_func(...) -> ReturnType creates uses edge to ReturnType."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.ReturnType")


# --- Anonymous scopes nested in anonymous scopes ---

NESTED_PREFIX = "test_code.nested_anon_scopes"


@pytest.fixture
def nested():
    filenames = [os.path.join(TESTS_DIR, "test_code/nested_anon_scopes.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


def test_lambda_inside_lambda(nested):
    """The inner lambda is numbered like any other anonymous scope.

    The visitor asks for the scope by the name it generates, so a scope
    registered under a different name is not a naming quirk — it aborts the
    whole analysis with ValueError.
    """
    defines = get_in_dict(nested.defines_edges, f"{NESTED_PREFIX}.lambda_in_lambda.lambda.0")
    get_node(defines, f"{NESTED_PREFIX}.lambda_in_lambda.lambda.0.lambda.0")


def test_nested_lambdas_reach_the_function_they_call(nested):
    """Collapsing folds the inner scopes into the parent, so the call survives."""
    uses = get_in_dict(nested.uses_edges, f"{NESTED_PREFIX}.lambda_in_lambda")
    get_node(uses, f"{NESTED_PREFIX}.target")


def test_two_outer_lambdas_each_keep_their_own_inner(nested):
    """Two lambdas in one function, each wrapping one more.

    Numbering is per (namespace, kind), so each inner lambda counts from zero
    inside its own outer one rather than continuing a shared sequence.
    """
    for outer in ("lambda.0", "lambda.1"):
        defines = get_in_dict(nested.defines_edges, f"{NESTED_PREFIX}.two_nested_lambdas.{outer}")
        get_node(defines, f"{NESTED_PREFIX}.two_nested_lambdas.{outer}.lambda.0")


def test_two_lambdas_inside_one_lambda_are_numbered_apart(nested):
    """A lambda returning a tuple of two lambdas: the inner pair must not collide."""
    parent = f"{NESTED_PREFIX}.two_inner_lambdas.lambda.0"
    defines = get_in_dict(nested.defines_edges, parent)
    get_node(defines, f"{parent}.lambda.0")
    get_node(defines, f"{parent}.lambda.1")


@pytest.mark.parametrize("func", ["comprehension_in_lambda", "lambda_in_comprehension", "stub_factory"])
def test_other_nestings_analyze(nested, func):
    """Comprehension in lambda, lambda in comprehension, and the monkeypatch-stub shape."""
    uses = get_in_dict(nested.uses_edges, f"{NESTED_PREFIX}.{func}")
    get_node(uses, f"{NESTED_PREFIX}.target")
