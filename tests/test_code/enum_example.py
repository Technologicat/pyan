"""Test input for Enum member attribute access (#113)."""

from enum import Enum


class Color(Enum):
    RED = 1
    GREEN = 2
    BLUE = 3


def use_color():
    return Color.RED


def use_class():
    return Color
