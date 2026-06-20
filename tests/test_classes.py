"""Class-related feature tests: decorators, inheritance, MRO, super(),
class-level constants, enum members, and class-body annotations.

Uses tests/test_code/features.py and tests/test_code/enum_example.py.
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


def test_multiple_inheritance(v):
    """Combined inherits from both MixinA and MixinB."""
    combined_uses = get_in_dict(v.uses_edges, f"{PREFIX}.Combined")
    get_node(combined_uses, f"{PREFIX}.MixinA")
    get_node(combined_uses, f"{PREFIX}.MixinB")


def test_super_call(v):
    """super().greet() in Child should create a uses edge to Parent.greet."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.Child.greet")
    get_node(uses, f"{PREFIX}.Parent.greet")


# --- Class-body annotations ---

def test_class_body_annotation_uses(v):
    """Class-level `value: MyType` (no RHS) creates uses edge to MyType."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.Holder")
    get_node(uses, f"{PREFIX}.MyType")


# --- Class-level constant attributes ---

def test_class_constant_creates_uses_edge_to_class(v):
    """Settings.DEBUG should create a uses edge to the Settings class."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.read_setting")
    get_node(uses, f"{PREFIX}.Settings")


def test_class_constant_with_enum():
    """Enum member access should create a uses edge to the Enum class."""
    filenames = [os.path.join(TESTS_DIR, "test_code/enum_example.py")]
    v = CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())
    uses = get_in_dict(v.uses_edges, "test_code.enum_example.use_color")
    get_node(uses, "test_code.enum_example.Color")
