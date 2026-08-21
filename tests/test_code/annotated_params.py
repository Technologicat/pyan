"""Attribute access on a parameter whose type the signature states."""


class Thing:
    def method(self):
        pass


def annotated(obj: Thing):
    obj.method()


def unannotated(obj):
    obj.method()


def via_local():
    thing = Thing()
    thing.method()


def varargs(*items: Thing):
    # The annotation describes the element type; `items` is a tuple.
    items.method()


def kwargs_only(**opts: Thing):
    # Likewise: `opts` is a dict.
    opts.method()
