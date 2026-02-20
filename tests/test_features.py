"""Feature coverage tests for the analyzer.

Exercises: decorators, inheritance, MRO, lambdas, closures,
context managers, async functions, for-loop calls, walrus operator,
async with, match statement, type annotations, type aliases (3.12+).

Uses tests/test_code/features.py as input (and tests/test_code_312/ for 3.12+ syntax).
"""

import logging
import os
import sys

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)
PREFIX = "test_code.features"


@pytest.fixture
def v():
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    return CallGraphVisitor(filenames, logger=logging.getLogger())


# --- Decorators ---

def test_decorator_detection(v):
    """Decorated class defines all four methods; uses edges to decorator builtins."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.Decorated")
    get_node(defines, f"{PREFIX}.Decorated.static_method")
    get_node(defines, f"{PREFIX}.Decorated.class_method")
    get_node(defines, f"{PREFIX}.Decorated.my_prop")
    get_node(defines, f"{PREFIX}.Decorated.regular")

    uses = get_in_dict(v.uses_edges, f"{PREFIX}.Decorated")
    get_node(uses, "*.staticmethod")
    get_node(uses, "*.classmethod")
    get_node(uses, "*.property")


# --- Inheritance ---

def test_inheritance_edges(v):
    """Derived inherits from Base; method calls resolve via MRO."""
    # Derived -> Base (inheritance edge)
    derived_uses = get_in_dict(v.uses_edges, f"{PREFIX}.Derived")
    get_node(derived_uses, f"{PREFIX}.Base")

    # Base.bar calls self.foo() -> resolves to Base.foo
    bar_uses = get_in_dict(v.uses_edges, f"{PREFIX}.Base.bar")
    get_node(bar_uses, f"{PREFIX}.Base.foo")

    # Derived.baz calls self.foo() and self.bar() -> resolved to Base via MRO
    baz_uses = get_in_dict(v.uses_edges, f"{PREFIX}.Derived.baz")
    get_node(baz_uses, f"{PREFIX}.Base.foo")
    get_node(baz_uses, f"{PREFIX}.Base.bar")


# --- Multiple inheritance ---

def test_multiple_inheritance(v):
    """Combined inherits from both MixinA and MixinB."""
    combined_uses = get_in_dict(v.uses_edges, f"{PREFIX}.Combined")
    get_node(combined_uses, f"{PREFIX}.MixinA")
    get_node(combined_uses, f"{PREFIX}.MixinB")


# --- Lambda ---

def test_lambda_definition(v):
    """Lambda is defined as a child of the enclosing function."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.make_adder")
    get_node(defines, f"{PREFIX}.make_adder.lambda")


# --- Closures ---

def test_closure_definition(v):
    """Inner function defined within outer; outer calls inner."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.outer")
    get_node(defines, f"{PREFIX}.outer.inner")

    uses = get_in_dict(v.uses_edges, f"{PREFIX}.outer")
    get_node(uses, f"{PREFIX}.outer.inner")


# --- Context manager ---

def test_context_manager(v):
    """with MyCtx() as ctx: creates uses edges to __enter__, __exit__, and constructor."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_ctx")
    get_node(uses, f"{PREFIX}.MyCtx")
    get_node(uses, f"{PREFIX}.MyCtx.__enter__")
    get_node(uses, f"{PREFIX}.MyCtx.__exit__")


# --- Async ---

def test_async_function_call(v):
    """async process() awaits fetch() -> uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.process")
    get_node(uses, f"{PREFIX}.fetch")


# --- For loop call ---

def test_for_loop_call(v):
    """Function call inside for loop creates uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.process_items")
    get_node(uses, f"{PREFIX}.handle")


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


# --- Async with ---

def test_async_with(v):
    """async with AsyncCM() creates uses edges to __aenter__ and __aexit__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_async_cm")
    get_node(uses, f"{PREFIX}.AsyncCM")
    get_node(uses, f"{PREFIX}.AsyncCM.__aenter__")
    get_node(uses, f"{PREFIX}.AsyncCM.__aexit__")


# --- Match statement ---

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


# --- Type annotations ---

def test_annassign_annotation_uses(v):
    """result: MyType = None creates uses edge to MyType (from annotation)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.MyType")


def test_funcdef_return_annotation_uses(v):
    """def annotated_func(...) -> ReturnType creates uses edge to ReturnType."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.ReturnType")


def test_funcdef_arg_annotation_uses(v):
    """def annotated_func(x: MyType) creates uses edge to MyType (from arg annotation)."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.annotated_func")
    get_node(uses, f"{PREFIX}.MyType")


def test_class_body_annotation_uses(v):
    """Class-level `value: MyType` (no RHS) creates uses edge to MyType."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.Holder")
    get_node(uses, f"{PREFIX}.MyType")


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
    names = [node.get_name() for node in v.uses_edges.keys()]
    assert f"{PREFIX}.unbind_local" not in names


# --- Type aliases (PEP 695, Python 3.12+) ---

PREFIX_312 = "test_code_312.type_aliases"


@pytest.fixture
def v312():
    filenames = [os.path.join(TESTS_DIR, "test_code_312/type_aliases.py")]
    return CallGraphVisitor(filenames, logger=logging.getLogger())


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type statement requires Python 3.12+")
def test_type_alias_defined(v312):
    """type Point = ... creates a defines edge under the module."""
    defines = get_in_dict(v312.defines_edges, PREFIX_312)
    get_node(defines, f"{PREFIX_312}.Point")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type statement requires Python 3.12+")
def test_type_alias_uses_class(v312):
    """type PairAlias = Pair creates uses edge to user-defined Pair."""
    uses = get_in_dict(v312.uses_edges, f"{PREFIX_312}.PairAlias")
    get_node(uses, f"{PREFIX_312}.Pair")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type statement requires Python 3.12+")
def test_parameterized_type_alias_defined(v312):
    """type Matrix[T] = ... creates a defines edge under the module."""
    defines = get_in_dict(v312.defines_edges, PREFIX_312)
    get_node(defines, f"{PREFIX_312}.Matrix")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="type statement requires Python 3.12+")
def test_type_alias_in_function(v312):
    """Type alias inside a function creates a defines edge under the function."""
    defines = get_in_dict(v312.defines_edges, f"{PREFIX_312}.make_alias")
    get_node(defines, f"{PREFIX_312}.make_alias.LocalAlias")
