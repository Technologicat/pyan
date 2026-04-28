"""Calls a statically-resolvable function via attribute access on its module.

For #127's regression: ``defines_func.myfunc()`` should produce exactly one
``calls_func.caller -> defines_func.myfunc`` edge — never a duplicate, and
no fallback edge to the module (since the attr resolves to a defined Node).
"""

import defines_func


def caller():
    return defines_func.myfunc()
