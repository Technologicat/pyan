"""Anonymous scopes nested inside anonymous scopes.

The monkeypatch-stub shape at the bottom is what turned this up in the wild: a
lambda whose body constructs something from another lambda.
"""


def target(value):
    return value


def lambda_in_lambda():
    return lambda x: (lambda y: target(x + y))


def comprehension_in_lambda():
    return lambda xs: [target(x) for x in xs]


def lambda_in_comprehension(xs):
    return [(lambda y: target(y)) for _ in xs]


def two_nested_lambdas():
    first = lambda a: (lambda b: target(a))
    second = lambda c: (lambda d: target(c))
    return first, second


def two_inner_lambdas():
    return lambda x: (lambda a: target(a), lambda b: target(b + x))


def stub_factory(data):
    return lambda: dict(fetch=lambda *a, **kw: target(data))
