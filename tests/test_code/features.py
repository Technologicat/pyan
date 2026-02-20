"""Test input for baseline feature coverage.

Self-contained — no external imports. Each section exercises
a different analyzer feature.
"""


# --- Decorators ---

class Decorated:
    @staticmethod
    def static_method():
        pass

    @classmethod
    def class_method(cls):
        pass

    @property
    def my_prop(self):
        return self._x

    def regular(self):
        pass


# --- Inheritance ---

class Base:
    def foo(self):
        return 1

    def bar(self):
        return self.foo()


class Derived(Base):
    def baz(self):
        return self.foo() + self.bar()


# --- Multiple inheritance ---

class MixinA:
    def shared(self):
        pass


class MixinB:
    def shared(self):
        pass


class Combined(MixinA, MixinB):
    pass


# --- Lambda ---

def make_adder(n):
    return lambda x: x + n


# --- Closures ---

def outer():
    def inner():
        return 1
    return inner()


# --- Context manager ---

class MyCtx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def use_ctx():
    with MyCtx() as ctx:  # noqa: F841  # test fixture
        pass


# --- Async ---

async def fetch(url):
    pass


async def process():
    await fetch("x")


# --- For loop call ---

def process_items(items):
    for item in items:
        handle(item)


def handle(x):
    return x


# --- Walrus operator (NamedExpr, PEP 572) ---

def walrus_caller(data):
    if (n := len(data)) > 10:
        walrus_target(n)


def walrus_target(x):
    pass


class Result:
    def process(self):
        pass


def walrus_method():
    if (r := Result()):
        r.process()


# --- Async with ---

class AsyncCM:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def use_async_cm():
    async with AsyncCM() as cm:  # noqa: F841  # test fixture
        pass


# --- Match statement (PEP 634) ---

class Point:
    def __init__(self, x, y):
        pass


class Circle:
    def __init__(self, r):
        pass


def handle_point(px, py):
    pass


def handle_circle(r):
    pass


def handle_str(s):
    pass


def handle_list(first):
    pass


def handle_action(action):
    pass


def handle_default():
    pass


def match_example(cmd):
    match cmd:
        case Point(x=px, y=py):
            handle_point(px, py)
        case Circle(r=cr):
            handle_circle(cr)
        case str() as s:
            handle_str(s)
        case [first, *others]:  # noqa: F841  # test fixture
            handle_list(first)
        case {"action": action, **rest}:  # noqa: F841  # test fixture
            handle_action(action)
        case _:
            handle_default()


# --- Type annotations ---

class MyType:
    pass


class ReturnType:
    pass


def annotated_func(x: MyType) -> ReturnType:
    result: MyType = None
    return result


class Holder:
    value: MyType


# --- Del statement ---

class Registry:
    def __delattr__(self, name):
        pass

    def __delitem__(self, key):
        pass


def clear_entry(registry):
    registry = Registry()
    del registry.entry

def remove_item(registry):
    registry = Registry()
    del registry["key"]

def unbind_local():
    tmp = 1
    del tmp


# --- Iterator protocol ---

class Sequence:
    def __iter__(self):
        return self

    def __next__(self):
        raise StopIteration


def iterate_sequence():
    seq = Sequence()
    for item in seq:  # noqa: F841  # test fixture
        pass


class AsyncStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


async def iterate_async_stream():
    stream = AsyncStream()
    async for chunk in stream:  # noqa: F841  # test fixture
        pass


def comprehend_sequence():
    seq = Sequence()
    return [x for x in seq]


# --- Starred unpacking (positional matching) ---

class Alpha:
    def alpha_method(self):
        pass


class Beta:
    def beta_method(self):
        pass


class Gamma:
    def gamma_method(self):
        pass


class Delta:
    def delta_method(self):
        pass


def star_at_end():
    a, b, *c = Alpha(), Beta(), Gamma(), Delta()  # noqa: F841  # test fixture
    a.alpha_method()
    b.beta_method()


def star_in_middle():
    a, *b, c = Alpha(), Beta(), Gamma(), Delta()  # noqa: F841  # test fixture
    a.alpha_method()
    c.delta_method()


def star_at_start():
    *a, b = Alpha(), Beta(), Gamma()  # noqa: F841  # test fixture
    b.gamma_method()


# --- Local variable noise suppression ---

def local_noise_example(items):
    """Unresolved local `x` should not produce a wildcard UNKNOWN node."""
    x = len(items)  # noqa: F841  # test fixture
    return items
