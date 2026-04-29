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
    get_node(defines, f"{PREFIX}.make_adder.lambda.0")


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
    names = [node.get_name() for node in v.uses_edges]
    assert f"{PREFIX}.unbind_local" not in names


# --- Iterator protocol ---

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


# --- Lambda as default argument (#61) ---

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


# --- Keyword-only defaults ---

def test_kwonly_defaults_defined(v):
    """Function with keyword-only default args should be defined."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.kwonly_defaults")


# --- Chained assignment ---

def test_chained_assign(v):
    """Chained assignment `a = b = Alpha()` should resolve through."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.chained_assign")
    get_node(uses, f"{PREFIX}.Alpha.alpha_method")


# --- For-else ---

def test_for_else(v):
    """for-else: the else clause should create a uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.for_with_else")
    get_node(uses, "*.len")


# --- Nested attribute access ---

def test_nested_attr(v):
    """o.Inner.method() should create a uses edge to Inner.method."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.access_nested_attr")
    get_node(uses, f"{PREFIX}.Outer.Inner.method")


# --- String literal method ---

def test_string_method(v):
    """'hello'.upper() should create a uses edge to str.upper."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.call_string_method")
    names = [n.get_name() for n in uses]
    assert any("upper" in n for n in names)


# --- super() ---

def test_super_call(v):
    """super().greet() in Child should create a uses edge to Parent.greet."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.Child.greet")
    get_node(uses, f"{PREFIX}.Parent.greet")


# --- Match with guard ---

def test_match_guard(v):
    """Match statement with guard should not crash and should process body."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_with_guard")
    get_node(uses, f"{PREFIX}.handle_point")


def test_match_or_pattern(v):
    """Match with `int() | float() as n` should process the or-pattern."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.match_with_guard")
    get_node(uses, f"{PREFIX}.handle_action")


# --- str()/repr() built-in resolution ---

def test_str_builtin_resolution(v):
    """str(p) should create a uses edge to Printable.__str__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_str_repr")
    get_node(uses, f"{PREFIX}.Printable.__str__")


def test_repr_builtin_resolution(v):
    """repr(p) should create a uses edge to Printable.__repr__."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.use_str_repr")
    get_node(uses, f"{PREFIX}.Printable.__repr__")


# --- Setcomp / dictcomp / genexpr ---

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


# --- Per-anonymous-scope isolation (#110) ---

def test_multi_listcomp_isolated_scopes(v):
    """Two listcomps in the same function should get separate scope nodes."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.multi_listcomp")
    get_node(defines, f"{PREFIX}.multi_listcomp.listcomp.0")
    get_node(defines, f"{PREFIX}.multi_listcomp.listcomp.1")


def test_multi_lambda_isolated_scopes(v):
    """Two lambdas in the same function should get separate scope nodes."""
    defines = get_in_dict(v.defines_edges, f"{PREFIX}.multi_lambda")
    get_node(defines, f"{PREFIX}.multi_lambda.lambda.0")
    get_node(defines, f"{PREFIX}.multi_lambda.lambda.1")


# --- Lambda with defaults ---

def test_lambda_with_defaults(v):
    """Lambda with positional default should be defined."""
    defines = get_in_dict(v.defines_edges, PREFIX)
    get_node(defines, f"{PREFIX}.lambda.0")


# --- Import resolution ---

IMPORTS_DIR = os.path.join(TESTS_DIR, "test_code/imports")
IMPORTS_PREFIX = "test_code.imports"


@pytest.fixture
def v_imports():
    from glob import glob
    filenames = glob(os.path.join(IMPORTS_DIR, "**/*.py"), recursive=True)
    return CallGraphVisitor(filenames, logger=logging.getLogger())


def test_chained_import_resolution(v_imports):
    """consumer imports Widget via reexporter; should resolve to provider.Widget."""
    uses = get_in_dict(v_imports.uses_edges, f"{IMPORTS_PREFIX}.consumer.use_widget")
    names = [n.get_name() for n in uses]
    assert any("Widget" in n for n in names)


def test_attr_of_import(v_imports):
    """prov.helper() via `import ... as prov` should resolve."""
    uses = get_in_dict(v_imports.uses_edges, f"{IMPORTS_PREFIX}.attr_consumer.use_provider_attr")
    names = [n.get_name() for n in uses]
    assert any("helper" in n for n in names)


# --- Local variable noise suppression ---

def test_local_no_unknown_node(v):
    """Unresolved local `x` should not produce a wildcard *.x uses edge."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.local_noise_example")
    # Should have a uses edge to len (the call), but NOT to *.x (the local).
    get_node(uses, "*.len")
    names = [n.get_name() for n in uses]
    assert not any(n.endswith(".x") for n in names)


# --- Class-level constant attributes ---

def test_class_constant_creates_uses_edge_to_class(v):
    """Settings.DEBUG should create a uses edge to the Settings class."""
    uses = get_in_dict(v.uses_edges, f"{PREFIX}.read_setting")
    get_node(uses, f"{PREFIX}.Settings")


def test_class_constant_with_enum():
    """Enum member access should create a uses edge to the Enum class."""
    filenames = [os.path.join(TESTS_DIR, "test_code/enum_example.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    uses = get_in_dict(v.uses_edges, "test_code.enum_example.use_color")
    get_node(uses, "test_code.enum_example.Color")


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


# --- PEP 695 generics (Python 3.12+, #123) ---

PREFIX_GEN = "test_code_312.generics"


@pytest.fixture
def v_generics():
    filenames = [os.path.join(TESTS_DIR, "test_code_312/generics.py")]
    return CallGraphVisitor(filenames, logger=logging.getLogger())


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


# --- Directional filtering (#95) ---

@pytest.fixture
def v_multi():
    """Analyzer over the full test_code package (cross-module calls)."""
    from glob import glob
    filenames = glob(os.path.join(TESTS_DIR, "test_code/**/*.py"), recursive=True)
    return CallGraphVisitor(filenames, logger=logging.getLogger())


CALLER = "test_code.submodule2.test_2"        # calls test_func1
CALLEE = "test_code.submodule1.test_func1"     # called by test_2


def test_direction_down_finds_callees(v_multi):
    """direction='down' from test_2 should include test_func1 (a callee)."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="down")
    names = {n.get_name() for n in related}
    assert CALLEE in names


def test_direction_down_excludes_callers(v_multi):
    """direction='down' from test_func1 should NOT include test_2 (a caller)."""
    node = v_multi.get_node("test_code.submodule1", "test_func1")
    related = v_multi.get_related_nodes(node, direction="down")
    names = {n.get_name() for n in related}
    assert CALLER not in names


def test_direction_up_finds_callers(v_multi):
    """direction='up' from test_func1 should include test_2 (a caller)."""
    node = v_multi.get_node("test_code.submodule1", "test_func1")
    related = v_multi.get_related_nodes(node, direction="up")
    names = {n.get_name() for n in related}
    assert CALLER in names


def test_direction_up_excludes_callees(v_multi):
    """direction='up' from test_2 should NOT include test_func1 (a callee)."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="up")
    names = {n.get_name() for n in related}
    assert CALLEE not in names


def test_direction_both_finds_both(v_multi):
    """direction='both' from test_2 should include both callers and callees."""
    node = v_multi.get_node("test_code.submodule2", "test_2")
    related = v_multi.get_related_nodes(node, direction="both")
    names = {n.get_name() for n in related}
    assert CALLEE in names


# --- Call path listing (#12) ---

def test_find_paths_direct(v_multi):
    """find_paths should find a direct edge as a single-hop path."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node)
    path_strs = [" -> ".join(n.get_name() for n in p) for p in paths]
    assert any("test_2" in s and "test_func1" in s for s in path_strs)


def test_find_paths_multi_hop():
    """find_paths should find a two-hop path: Derived.baz -> Base.bar -> Base.foo."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    from_node = v.get_node("test_code.features.Derived", "baz")
    to_node = v.get_node("test_code.features.Base", "foo")
    paths = v.find_paths(from_node, to_node)
    assert len(paths) >= 1
    # The two-hop path should go through bar
    path_names = [[n.get_name() for n in p] for p in paths]
    assert any("test_code.features.Base.bar" in p for p in path_names)


def test_find_paths_no_path(v_multi):
    """find_paths should return empty list when no path exists."""
    # test_func1 does not call test_2
    from_node = v_multi.get_node("test_code.submodule1", "test_func1")
    to_node = v_multi.get_node("test_code.submodule2", "test_2")
    paths = v_multi.find_paths(from_node, to_node)
    assert paths == []


def test_find_paths_max_paths(v_multi):
    """find_paths respects max_paths limit."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node, max_paths=1)
    assert len(paths) <= 1


def test_format_paths(v_multi):
    """format_paths produces the expected text format."""
    from_node = v_multi.get_node("test_code.submodule2", "test_2")
    to_node = v_multi.get_node("test_code.submodule1", "test_func1")
    paths = v_multi.find_paths(from_node, to_node)
    text = v_multi.format_paths(paths)
    assert " -> " in text
    assert "test_2" in text
    assert "test_func1" in text


# --- Depth filtering (#80) ---

def test_depth_class_level_collapses_methods():
    """depth=1 should collapse methods into their class."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    v.filter_by_depth(1)

    # Methods should be gone
    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.features.Base.foo" not in names
    assert "test_code.features.Base.bar" not in names
    # Classes should remain
    assert "test_code.features.Base" in names
    assert "test_code.features.Derived" in names


def test_depth_class_level_collapses_edges():
    """depth=1 should collapse method→method edges to class→class edges."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    v.filter_by_depth(1)

    # Derived.baz → Base.bar should become Derived → Base
    derived_node = None
    base_node = None
    for nodes in v.nodes.values():
        for n in nodes:
            if n.get_name() == "test_code.features.Derived":
                derived_node = n
            if n.get_name() == "test_code.features.Base":
                base_node = n
    assert derived_node is not None
    assert base_node is not None
    assert derived_node in v.uses_edges
    target_names = {n.get_name() for n in v.uses_edges[derived_node]}
    assert "test_code.features.Base" in target_names


def test_depth_module_level():
    """depth=0 should show only modules, collapsing everything deeper."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    v.filter_by_depth(0)

    # Only the module itself should remain as a defined node
    defined_names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.features" in defined_names
    for name in defined_names:
        assert name in v.module_to_filename, f"Node {name} should be a module at depth 0"


def test_depth_module_level_cross_module(v_multi):
    """depth=0 with multi-module input should collapse function edges to module edges."""
    v_multi.filter_by_depth(0)

    # Functions should be gone, modules should remain
    names = {n.get_name() for nodes in v_multi.nodes.values() for n in nodes if n.defined}
    assert "test_code.submodule2" in names
    assert "test_code.submodule1" in names
    assert "test_code.submodule2.test_2" not in names

    # Uses edges should be remapped: test_2 → test_func1 becomes submodule2 → submodule1
    all_uses_targets = {}
    for src, tgts in v_multi.uses_edges.items():
        all_uses_targets[src.get_name()] = {t.get_name() for t in tgts}
    assert "test_code.submodule1" in all_uses_targets.get("test_code.submodule2", set()), \
        "Cross-module uses edge should survive depth collapsing"


def test_depth_dotted_module_uses_edges():
    """Uses edges must survive depth collapsing even when module names contain dots.

    The old implementation counted raw dots in the fully qualified name, so a
    class in ``pkg.mod`` was treated as depth 2 instead of depth 1. This caused
    the ancestor lookup to create phantom nodes (wrong namespace/name split),
    which had ``defined=False`` and were silently dropped by ``remap_edges``.
    """
    filenames = [
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_a.py"),
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_b.py"),
    ]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())

    # Depth 1: methods collapse into classes; classes and modules remain
    v.filter_by_depth(1)

    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.depth_pkg.mod_a.ClassA" in names
    assert "test_code.depth_pkg.mod_b.ClassB" in names
    assert "test_code.depth_pkg.mod_a.ClassA.method_a" not in names  # collapsed

    # The critical check: ClassA.method_a → ClassB should become ClassA → ClassB
    uses_map = {src.get_name(): {t.get_name() for t in tgts}
                for src, tgts in v.uses_edges.items()}
    assert "test_code.depth_pkg.mod_b.ClassB" in uses_map.get("test_code.depth_pkg.mod_a.ClassA", set()), \
        "Cross-module uses edge must survive depth collapsing with dotted module names"


def test_depth_dotted_module_depth_zero():
    """Depth 0 with dotted module names should collapse everything to modules."""
    filenames = [
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_a.py"),
        os.path.join(TESTS_DIR, "test_code/depth_pkg/mod_b.py"),
    ]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    v.filter_by_depth(0)

    names = {n.get_name() for nodes in v.nodes.values() for n in nodes if n.defined}
    assert "test_code.depth_pkg.mod_a" in names
    assert "test_code.depth_pkg.mod_b" in names
    assert "test_code.depth_pkg.mod_a.ClassA" not in names  # collapsed

    uses_map = {src.get_name(): {t.get_name() for t in tgts}
                for src, tgts in v.uses_edges.items()}
    assert "test_code.depth_pkg.mod_b" in uses_map.get("test_code.depth_pkg.mod_a", set()), \
        "Cross-module uses edge must survive depth-0 collapsing with dotted module names"


def test_depth_no_self_edges():
    """Collapsing should not create self-edges (e.g. Base.bar → Base.foo → Base)."""
    filenames = [os.path.join(TESTS_DIR, "test_code/features.py")]
    v = CallGraphVisitor(filenames, logger=logging.getLogger())
    v.filter_by_depth(1)

    for n, edges in v.uses_edges.items():
        assert n not in edges, f"Self-edge on {n.get_name()}"


# --- Module-level NAME Node-ification ---
#
# Every named entity reachable from outside its definition site is a Node.
# Module-level and class-level bindings are reachable; function-locals are not.

def _name_nodes_at(visitor, namespace):
    """Return defined NAME-flavored Nodes at *namespace*."""
    from pyan.node import Flavor
    return [
        n for ns in visitor.nodes.values() for n in ns
        if n.defined and n.flavor == Flavor.NAME and n.namespace == namespace
    ]


def test_module_level_assignment_creates_defined_name_node():
    """``mymod.x = ...`` at module level produces a defined ``Flavor.NAME``
    Node at ``mymod.x``, with a defines edge from the module Node."""
    v = CallGraphVisitor.from_sources([
        ("CONSTANT = 42\nLOGGER = object()\n", "mymod"),
    ])
    name_nodes = {n.name for n in _name_nodes_at(v, "mymod")}
    assert "CONSTANT" in name_nodes
    assert "LOGGER" in name_nodes


def test_function_local_does_not_create_name_node():
    """Function-local bindings stay as scope-only ``set_value`` and do not
    produce graph Nodes — they aren't externally addressable and would
    only clutter the graph."""
    v = CallGraphVisitor.from_sources([
        ("def f():\n    local = 1\n    return local\n", "mymod"),
    ])
    name_nodes = {n.name for n in _name_nodes_at(v, "mymod.f")}
    assert "local" not in name_nodes


def test_cross_module_constant_import_resolves_to_name_node():
    """``from mymod import CONSTANT`` should bind to the actual NAME Node
    at ``mymod.CONSTANT``, not contract to a wildcard. This is the
    precision win from making module-level bindings addressable Nodes."""
    v = CallGraphVisitor.from_sources([
        ("CONSTANT = 42\n", "constants"),
        ("from constants import CONSTANT\n\ndef use():\n    return CONSTANT\n", "consumer"),
    ])
    use_uses = {n.get_name() for n in v.uses_edges.get(
        v.get_node("consumer", "use"), set()
    )}
    assert "constants.CONSTANT" in use_uses


def test_visgraph_suppresses_edgeless_name_nodes():
    """NAME Nodes with no incoming or outgoing uses edges should not appear
    in the visgraph output (visual-density default). The Node still exists
    in the analyzer's graph for cross-module resolution; only the rendered
    output filters it."""
    from pyan.visgraph import VisualGraph
    v = CallGraphVisitor.from_sources([
        # UNUSED has no uses edges anywhere; USED is imported by consumer.
        ("UNUSED = 1\nUSED = 2\n", "constants"),
        ("from constants import USED\n\ndef f():\n    return USED\n", "consumer"),
    ])
    vg = VisualGraph.from_visitor(v, options={"draw_defines": True, "draw_uses": True})

    def collect(graph, out):
        for n in graph.nodes:
            out.add(n.label)
        for sg in graph.subgraphs:
            collect(sg, out)
    labels = set()
    collect(vg, labels)
    assert any("USED" in lab for lab in labels), f"USED should appear; saw {labels}"
    assert not any("UNUSED" in lab for lab in labels), (
        f"UNUSED has no uses edges and should be suppressed; saw {labels}"
    )


# --- NAMESPACE_OBJECT (constructor-based namespace recognition, #129) ---

def _namespace_object_node(visitor, fqn):
    """Locate the NAMESPACE_OBJECT-flavored Node at *fqn*, or None."""
    from pyan.node import Flavor
    namespace, _, name = fqn.rpartition(".")
    for n in visitor.nodes.get(name, []):
        if n.namespace == namespace and n.flavor == Flavor.NAMESPACE_OBJECT:
            return n
    return None


def _scope_defs(visitor, fqn):
    """Return defs dict of the scope at *fqn*, or empty dict if absent."""
    sc = visitor.scopes.get(fqn)
    return sc.defs if sc else {}


# Each of the four built-in constructors gets at least one fixture.

def test_namespace_object_unpythonic_env_canonical_form():
    """``from unpythonic.env import env; config = env(thingy=baa)`` —
    canonical FQN ``"unpythonic.env.env"``."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None, "config should be a NAMESPACE_OBJECT Node"
    assert "thingy" in _scope_defs(v, "mymod.config"), "kwarg 'thingy' should register in config's scope"


def test_namespace_object_unpythonic_env_top_level_reexport():
    """``from unpythonic import env; config = env(thingy=baa)`` —
    top-level re-export FQN ``"unpythonic.env"`` (the module shadows
    the class — historical naming)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic import env\n\nconfig = env(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.config")


def test_namespace_object_simplenamespace():
    """``import types; ns = types.SimpleNamespace(thingy=baa)`` — Attribute
    func, FQN reconstructed from the dotted AST path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nimport types\n\nns = types.SimpleNamespace(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.ns")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.ns")


def test_namespace_object_argparse_namespace():
    """``import argparse; cfg = argparse.Namespace(thingy=baa)``."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nimport argparse\n\ncfg = argparse.Namespace(thingy=baa)\n", "mymod"),
    ])
    obj = _namespace_object_node(v, "mymod.cfg")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.cfg")


# Each of the four binding sites.

def test_namespace_object_recognized_in_annotated_assign():
    """``config: Env = env(...)`` — AnnAssign path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig: env = env(thingy=baa)\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None


def test_namespace_object_recognized_in_walrus():
    """``(config := env(...))`` — NamedExpr path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\n_ = (config := env(thingy=baa))\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None


def test_namespace_object_recognized_in_with_statement():
    """``with env(...) as config:`` — `_visit_with` routes through
    `analyze_binding`, same recognition path."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nwith env(thingy=baa) as config:\n    pass\n", "mymod"),
    ])
    # In a with-statement at module scope, the binding still creates a
    # module-level NAME Node that gets upgraded to NAMESPACE_OBJECT.
    assert _namespace_object_node(v, "mymod.config") is not None


# Cross-module attribute resolution — the headline use case.

def test_namespace_object_cross_module_attr_resolves():
    """External ``config.thingy`` resolves to the kwarg's target Node,
    bypassing #127's module-level fallback entirely."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env(thingy=baa)\n", "lib"),
        ("from lib import config\n\ndef use():\n    return config.thingy\n", "consumer"),
    ])
    use_uses = {n.get_name() for n in v.uses_edges.get(v.get_node("consumer", "use"), set())}
    assert "lib.baa" in use_uses, f"config.thingy should resolve to lib.baa; saw {use_uses}"


# Staged form: point 4 in the design brief.

def test_namespace_object_attribute_write_after_construction():
    """``config = env(); config.a = baa`` — the attribute write goes
    through ``_bind_target``'s Attribute branch and ``set_attribute``,
    which writes into the NAMESPACE_OBJECT's scope (created at
    construction time, even when no kwargs were passed)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nconfig.a = baa\n", "mymod"),
    ])
    assert _namespace_object_node(v, "mymod.config") is not None
    assert "a" in _scope_defs(v, "mymod.config"), "later attribute write should populate the scope"


# setattr — three levels.

def test_namespace_object_setattr_level1_literal_string():
    """``setattr(config, "a", baa)`` — literal-string name."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nsetattr(config, 'a', baa)\n", "mymod"),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_level2_scope_local_literal():
    """``k = "a"; setattr(config, k, baa)`` — name-bound literal in same
    scope. Module-level binding chain only (function-local literals not
    tracked, by design — see ``_maybe_register_name_literal``)."""
    v = CallGraphVisitor.from_sources([
        ("def baa():\n    pass\n\nfrom unpythonic.env import env\n\nconfig = env()\nKEY = 'a'\nsetattr(config, KEY, baa)\n", "mymod"),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_level3_cross_module_imported_literal():
    """``from constants import KEY; setattr(config, KEY, baa)`` — KEY
    traces back through an import to a string literal in another module."""
    v = CallGraphVisitor.from_sources([
        ("KEY = 'a'\n", "constants"),
        (
            "def baa():\n    pass\n\n"
            "from unpythonic.env import env\n"
            "from constants import KEY\n\n"
            "config = env()\n"
            "setattr(config, KEY, baa)\n",
            "mymod",
        ),
    ])
    assert "a" in _scope_defs(v, "mymod.config")


def test_namespace_object_setattr_dynamic_key_is_no_op():
    """``for k in keys: setattr(config, k, baa)`` — k is loop-bound and
    not statically a string literal. Recognition gracefully no-ops; no
    spurious bindings are registered."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "from unpythonic.env import env\n\n"
            "config = env()\n"
            "for k in ('a', 'b'):\n"
            "    setattr(config, k, baa)\n",
            "mymod",
        ),
    ])
    # The constructor recognition still creates the NAMESPACE_OBJECT,
    # but no individual kwarg names get registered from the loop.
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    defs = _scope_defs(v, "mymod.config")
    assert "a" not in defs and "b" not in defs


# User-extensible registry.

def test_user_extensible_namespace_constructor():
    """``namespace_constructors=["mylib.MyNS"]`` extends the registry."""
    v = CallGraphVisitor.from_sources(
        [(
            "def baa():\n    pass\n\n"
            "from mylib import MyNS\n\n"
            "config = MyNS(thingy=baa)\n",
            "mymod",
        )],
        namespace_constructors=["mylib.MyNS"],
    )
    obj = _namespace_object_node(v, "mymod.config")
    assert obj is not None
    assert "thingy" in _scope_defs(v, "mymod.config")


# Negative: don't over-fire.

def test_factory_returned_namespace_not_recognized():
    """``config = make_config()`` where ``make_config`` is a regular
    function — not in the registry, so no upgrade. Falls through to
    #127's module-level fallback as the right floor."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "def make_config():\n    return None\n\n"
            "config = make_config()\n",
            "mymod",
        ),
    ])
    assert _namespace_object_node(v, "mymod.config") is None


def test_unrecognized_constructor_no_op():
    """Calling a non-registered constructor doesn't accidentally upgrade."""
    v = CallGraphVisitor.from_sources([
        (
            "def baa():\n    pass\n\n"
            "class MyClass:\n    pass\n\n"
            "config = MyClass()\n",
            "mymod",
        ),
    ])
    assert _namespace_object_node(v, "mymod.config") is None
