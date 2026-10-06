"""Anonymous scopes must be named in the order `symtable` numbers them (#142).

`symtable` numbers the lambdas and comprehensions of a scope in its own traversal order, and the
visitor looks each one up by the name it generates. When the two orders disagree, sibling lambdas
swap names, which goes unnoticed until one of them holds a scope of its own: then the lookup of
`lambda.0.lambda.0` finds nothing and the whole analysis aborts with ``ValueError: Unknown scope``.

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
