# Regular module — relative import of sibling.
from . import alpha


def call_greet():
    return alpha.greet()
