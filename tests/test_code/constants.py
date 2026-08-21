"""Names bound to literals, and what reading them resolves to."""

import enum


LIMIT = 42
GREETING = "hello"
TABLE = {"a": 1}
UNUSED = 7


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


def read_number():
    return LIMIT


def read_mapping():
    return TABLE["a"]


def read_enum_member():
    return Color.RED


def method_on_a_literal():
    return "hello".upper()


class Holder:
    size = LIMIT
