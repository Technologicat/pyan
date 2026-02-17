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
    with MyCtx() as ctx:
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
