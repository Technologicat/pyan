"""Each lambda and comprehension must be named for, and get, its own scope (#142).

Scopes come from `symtable`, and the visitor looks each one up by name, so the name has to say which
table belongs to which AST node. When it does not, sibling lambdas trade scopes. That goes unnoticed until
one of them holds a scope of its own: then the lookup of `lambda.0.lambda.0` finds nothing and the whole
analysis aborts with ``ValueError: Unknown scope``.

Each template below has two slots, `{a}` before `{b}` in the source. One slot gets a plain lambda
and the other a lambda containing a lambda, both ways round — the reported shape only failed with
the nested lambda in one particular slot.
"""

import logging
import re

import pytest

from pyan.analyzer import CallGraphVisitor

PLAIN = "(lambda: 0)"
NESTED = "(lambda q: q(lambda: 0))"

TEMPLATES = {
    # Calls: the callee is evaluated, and numbered, before the arguments.
    "method chain": "x.do({a}).do({b})",
    "lambda as callee": "{a}({b})",
    "positional and keyword": "g({a}, k={b})",
    "two positionals": "g({a}, {b})",
    "two keywords": "g(j={a}, k={b})",
    "star and double star": "g(*{a}, **{b})",
    # Expressions.
    "subscript": "{a}[{b}]",
    "binop": "{a} + {b}",
    "boolop": "{a} or {b}",
    "compare": "{a} < {b} < 1",
    "ifexp body and test": "{a} if {b} else 0",
    "ifexp test and orelse": "0 if {a} else {b}",
    "tuple": "({a}, {b})",
    "dict key and value": "{{{a}: {b}}}",
    "dict two values": "{{1: {a}, 2: {b}}}",
    "set": "{{{a}, {b}}}",
    "f-string": "f'{{{a}}}{{{b}}}'",
    "slice": "x[{a}:{b}]",
    "starred": "[*{a}, *{b}]",
    "walrus": "(y := {a}) and {b}",
    # Comprehensions: the outermost iterable belongs to the enclosing scope.
    "listcomp iter and elt": "[{b} for _ in {a}]",
    "listcomp iter and if": "[0 for _ in {a} if {b}]",
    # Statements.
    "return tuple": "return {a}, {b}",
    "with": "with {a}() as y, {b}(): pass",
    "for iter and body": "for y in {a}: {b}",
    "assert": "assert {a}, {b}",
    "raise": "raise {a} from {b}",
    "yield": "yield ({a}, {b})",
    "def two defaults": "def h(z={a}, w={b}): pass",
    "def two kwonly defaults": "def h(*, z={a}, w={b}): pass",
    "match subject and guard": "match {a}:\n        case 1 if {b}: pass",
    "delete": "del x[{a}], x[{b}]",
    # Assignments: `symtable` numbers the targets before the value.
    "subscript target and value": "x[{a}] = {b}",
    "chained assignment": "x[{a}] = y[0] = {b}",
    "augmented assignment": "x[{a}] += {b}",
    "attribute target": "{a}().z = {b}",
    "annotated assignment": "y: {a} = {b}",
    # Definitions: `symtable` numbers a function's defaults before its decorators.
    "decorator and default": "@{a}\n    def h(z={b}): pass",
    "default and annotation": "def h(z: {b} = {a}): pass",
    "lambda default and body": "lambda z={a}: {b}",
    "class base and body": "class C({a}):\n        z = {b}",
    # Scopes inside comprehensions, which Python 3.12+ inlines.
    "genexpr": "list({b} for _ in {a})",
    "inlined comprehension": "[x.do({a}).do({b}) for x in g]",
}

ORDERS = {"nested second": (PLAIN, NESTED), "nested first": (NESTED, PLAIN)}


def _analyze(tmp_path, body):
    source = f"def f(x, g):\n    {body}\n"
    compile(source, "m.py", "exec")  # a template that is not valid Python would test nothing
    (tmp_path / "m.py").write_text(source)
    return CallGraphVisitor([str(tmp_path / "m.py")], root=str(tmp_path), logger=logging.getLogger())


@pytest.mark.filterwarnings("ignore::SyntaxWarning")  # `(lambda: 0)[...]` is valid, and the compiler says so
@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("template", TEMPLATES)
def test_nested_lambda_is_found_in_either_slot(tmp_path, template, order):
    a, b = ORDERS[order]
    v = _analyze(tmp_path, TEMPLATES[template].format(a=a, b=b))
    # Negative control: without a scope inside one of the lambdas, misnumbered siblings pass silently.
    defined = sorted(n.get_name() for targets in v.defines_edges.values() for n in targets)
    assert any(re.search(r"\.lambda\.\d+\.lambda\.0$", name) for name in defined), (
        f"no lambda inside a lambda was analyzed, so this fixture cannot detect misnumbering: {defined}")


# Which scope gets which name. Each lambda's parameter names it the way it should be named, and its body
# refers to nothing else, so its scope must hold exactly that one name: a scope traded with a sibling, or
# merged with one, holds the wrong name or two of them.
ORDER_SOURCE = """\
def chain(x):
    x.do(lambda first: 0).do(lambda second: 0)

def decorated():
    @(lambda second: second)
    def h(z=lambda first: 0):
        pass

def inlined(xs):
    [x.do(lambda first: 0).do(lambda second: 0) for x in xs]

def after_comprehension(x, xs):
    [lambda inner: 0 for _ in xs]
    x.do(lambda first: 0)

def lambda_default():
    lambda second=(lambda first: 0): 0

def annotated():
    def h(z: (lambda first: 0)):
        pass
"""

EXPECTED_SCOPES = {
    # A call's callee is evaluated, and numbered, before its arguments.
    "chain.lambda.0": "first",
    "chain.lambda.1": "second",
    # The compiler meets a function's defaults before its decorators, against the reading order. The order
    # `symtable` reports is the one that holds wherever there is one.
    "decorated.lambda.0": "first",
    "decorated.lambda.1": "second",
    # Python 3.12+ reports no table for the comprehension, and the lambdas in it as children of the
    # function; numbered in reading order within the comprehension, they come out as on 3.11.
    "inlined.listcomp.0.lambda.0": "first",
    "inlined.listcomp.0.lambda.1": "second",
    # So, likewise, a lambda after a comprehension holding one is still the function's first lambda.
    "after_comprehension.listcomp.0.lambda.0": "inner",
    "after_comprehension.lambda.0": "first",
    # A lambda's defaults are evaluated where the lambda is, so a lambda among them belongs to the
    # function, and the compiler meets it before the lambda it is a default of.
    "lambda_default.lambda.0": "first",
    "lambda_default.lambda.1": "second",
    # Annotations are analyzed as part of the function they annotate, though Python evaluates them outside
    # it, so that what they use is attributed to the function.
    "annotated.h.lambda.0": "first",
}


def test_each_scope_is_named_for_its_own_lambda(tmp_path):
    (tmp_path / "m.py").write_text(ORDER_SOURCE)
    v = CallGraphVisitor([str(tmp_path / "m.py")], root=str(tmp_path), logger=logging.getLogger())
    found = {ns.removeprefix("m."): sorted(scope.defs) for ns, scope in v.scopes.items() if ".lambda." in ns}
    assert found == {ns: [param] for ns, param in EXPECTED_SCOPES.items()}


def test_a_file_edited_between_passes_is_planned_again(tmp_path, monkeypatch):
    """A file can change on disk while pyan runs, say under an editor's save, and each pass reads it afresh.

    A plan made from the old text then names spans the new text no longer has.
    """
    path = tmp_path / "m.py"
    path.write_text("def f(x):\n    x.do(lambda first: 0)\n")
    prescan = CallGraphVisitor._prescan_one

    def prescan_then_edit(self, filename):
        prescan(self, filename)
        path.write_text("\n\n" + path.read_text())  # every span moves down two lines

    monkeypatch.setattr(CallGraphVisitor, "_prescan_one", prescan_then_edit)
    v = CallGraphVisitor([str(path)], root=str(tmp_path), logger=logging.getLogger())
    assert path.read_text().startswith("\n\n"), "the file was not edited, so this fixture tests nothing"
    assert sorted(v.scopes["m.f.lambda.0"].defs) == ["first"]
