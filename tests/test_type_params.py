"""PEP 695 type-parameter feature tests (Python 3.12+):
``type`` aliases (parameterized and not) and generic classes/functions.

Uses tests/test_code_312/type_aliases.py and tests/test_code_312/generics.py.
"""

import logging
import os
import sys

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict, get_node

TESTS_DIR = os.path.dirname(__file__)


# --- Type aliases (PEP 695) ---

PREFIX_312 = "test_code_312.type_aliases"


@pytest.fixture
def v312():
    filenames = [os.path.join(TESTS_DIR, "test_code_312/type_aliases.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


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


# --- Generics (PEP 695, #123) ---

PREFIX_GEN = "test_code_312.generics"


@pytest.fixture
def v_generics():
    filenames = [os.path.join(TESTS_DIR, "test_code_312/generics.py")]
    return CallGraphVisitor(filenames, root=TESTS_DIR, logger=logging.getLogger())


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_class_defines_methods(v_generics):
    """Generic class Container[T] should define its methods normally (#123)."""
    defines = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Container")
    get_node(defines, f"{PREFIX_GEN}.Container.fetch")
    get_node(defines, f"{PREFIX_GEN}.Container.store")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_class_defined_in_module(v_generics):
    """Generic class should appear as a defines edge of the module."""
    defines = get_in_dict(v_generics.defines_edges, PREFIX_GEN)
    get_node(defines, f"{PREFIX_GEN}.Container")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_function_defined(v_generics):
    """Generic function transform[T] should be defined in the module."""
    defines = get_in_dict(v_generics.defines_edges, PREFIX_GEN)
    get_node(defines, f"{PREFIX_GEN}.transform")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_class_multiple_params(v_generics):
    """Generic class Mapper[K, V] should define its methods."""
    defines = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Mapper")
    get_node(defines, f"{PREFIX_GEN}.Mapper.get")
    get_node(defines, f"{PREFIX_GEN}.Mapper.put")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_method_in_generic_class(v_generics):
    """Generic method Box[T].map[U] should be defined under Box."""
    defines = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Box")
    get_node(defines, f"{PREFIX_GEN}.Box.map")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_nested_generic_classes(v_generics):
    """Nested generic classes: Outer[T].Inner[U] with method."""
    defines_outer = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Outer")
    get_node(defines_outer, f"{PREFIX_GEN}.Outer.Inner")
    defines_inner = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Outer.Inner")
    get_node(defines_inner, f"{PREFIX_GEN}.Outer.Inner.method")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_function_calls_another(v_generics):
    """Generic function apply_identity[T] calls identity."""
    uses = get_in_dict(v_generics.uses_edges, f"{PREFIX_GEN}.apply_identity")
    get_node(uses, f"{PREFIX_GEN}.identity")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_nongeneric_class_uses_generic_function(v_generics):
    """Non-generic Processor.run calls generic transform[T]."""
    uses = get_in_dict(v_generics.uses_edges, f"{PREFIX_GEN}.Processor.run")
    get_node(uses, f"{PREFIX_GEN}.transform")


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 requires Python 3.12+")
def test_generic_class_shadowed_type_param(v_generics):
    """Shadowed[T] with T = ... in body should still define its method."""
    defines = get_in_dict(v_generics.defines_edges, f"{PREFIX_GEN}.Shadowed")
    get_node(defines, f"{PREFIX_GEN}.Shadowed.method")
