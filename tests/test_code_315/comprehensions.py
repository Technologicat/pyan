"""Comprehension unpacking (PEP 798), for the Python 3.15+ tests.

Every output expression calls a module-level function, so that there is something
inside the comprehension for the analyzer to resolve. If it fails to traverse the
output expression, the corresponding uses edge simply goes missing — which is what
the tests check for, since a missing edge is the quiet failure mode here.

`ordinary_dict` is the control: it exercises the `value` field that the unpacking
form leaves empty, so a fix that skipped that field entirely would fail here.
"""


def make_mapping(k):
    return {k: k}


def make_items(k):
    return [k, k]


def make_value(k):
    return k * 2


def merged(keys):
    # `DictComp.value` is None here; `key` holds the whole mapping expression.
    return {**make_mapping(k) for k in keys}


def flattened_list(keys):
    return [*make_items(k) for k in keys]


def flattened_set(keys):
    return {*make_items(k) for k in keys}


def flattened_gen(keys):
    return (*make_items(k) for k in keys)


def ordinary_dict(keys):
    return {k: make_value(k) for k in keys}
