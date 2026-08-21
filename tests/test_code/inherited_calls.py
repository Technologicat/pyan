"""One function calling both a base method and the override that shadows it."""


class Base:
    def hello(self):
        pass


class Derived(Base):
    def hello(self):
        pass


def call_both():
    Base.hello(None)
    Derived.hello(None)
