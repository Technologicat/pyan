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


# --- Annotated parameters as types ---

ANNOTATED_PREFIX = "test_code.annotated_params"


def _annotated_visitor(use_parameter_annotations=True):
    # submodule1 comes along because one parameter is annotated with it: a
    # module only resolves as a type when it is in the analyzed set.
    filenames = [os.path.join(TESTS_DIR, "test_code/annotated_params.py"),
                 os.path.join(TESTS_DIR, "test_code/submodule1.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger(),
                            use_parameter_annotations=use_parameter_annotations)


def _uses_names(v, func):
    node = get_node(v.uses_edges.keys(), f"{ANNOTATED_PREFIX}.{func}")
    return {n.get_name() for n in v.uses_edges[node]}


def test_annotated_parameter_resolves_attribute_call():
    """`def f(obj: Thing): obj.method()` reaches Thing.method."""
    v = _annotated_visitor()
    assert f"{ANNOTATED_PREFIX}.Thing.method" in _uses_names(v, "annotated")


def test_annotated_parameter_matches_the_local_case():
    """The asymmetry this removes.

    A local assigned from `Thing()` always resolved; the parameter did not,
    though the signature states the type just as plainly.
    """
    v = _annotated_visitor()
    method = f"{ANNOTATED_PREFIX}.Thing.method"
    assert method in _uses_names(v, "via_local")  # true before this feature too
    assert method in _uses_names(v, "annotated")  # now true as well


def test_annotations_can_be_ignored():
    """`use_parameter_annotations=False` restores the unresolved reading."""
    v = _annotated_visitor(use_parameter_annotations=False)
    assert f"{ANNOTATED_PREFIX}.Thing.method" not in _uses_names(v, "annotated")


def test_unannotated_parameter_is_unaffected():
    """Nothing states the type, so there is nothing to bind, either way."""
    for flag in (True, False):
        v = _annotated_visitor(use_parameter_annotations=flag)
        assert f"{ANNOTATED_PREFIX}.Thing.method" not in _uses_names(v, "unannotated")


def test_module_annotated_parameter_binds():
    """A module's scope is its attribute namespace too, so it binds like a class."""
    v = _annotated_visitor()
    assert "test_code.submodule1.test_func1" in _uses_names(v, "module_annotated")


@pytest.mark.parametrize("func", ["varargs", "kwargs_only"])
def test_star_args_annotations_do_not_bind(func):
    """`*items: Thing` says the elements are Things; `items` itself is a tuple."""
    v = _annotated_visitor()
    assert f"{ANNOTATED_PREFIX}.Thing.method" not in _uses_names(v, func)


@pytest.mark.parametrize("func", ["varargs_subscript", "kwargs_subscript"])
def test_subscripting_star_args_reaches_the_element_type(func):
    """`items[0]` is one element, which is what the annotation describes."""
    v = _annotated_visitor()
    assert f"{ANNOTATED_PREFIX}.Thing.method" in _uses_names(v, func)


def test_star_args_element_survives_a_local():
    """`first = items[0]` carries the element type into the local."""
    v = _annotated_visitor()
    assert f"{ANNOTATED_PREFIX}.Thing.method" in _uses_names(v, "varargs_element_via_local")
