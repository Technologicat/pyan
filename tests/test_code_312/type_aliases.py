"""Test input for PEP 695 type alias features (Python 3.12+)."""


class Pair:
    pass


# Simple type alias — no type parameters
type Point = tuple[float, float]

# Type alias referencing a user-defined class
type PairAlias = Pair

# Parameterized type alias
type Matrix[T] = list[list[T]]


# Type alias inside a function scope
def make_alias():
    type LocalAlias = int
