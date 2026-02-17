"""Baseline feature coverage tests for the analyzer.

Exercises: decorators, inheritance, MRO, lambdas, closures,
context managers, async functions, for-loop calls.

Uses tests/test_code/features.py as input.
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
