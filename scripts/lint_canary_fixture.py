"""Deliberate lint violations, one per rule family pyan's CI relies on. Never imported, never run.

`check_lint_canary.py` lints this file the way CI lints the tree, and fails unless every violation below is
reported. The ordinary lint run excludes it, or CI would fail on it permanently.
"""


def helper(a, b):
    return a + b


def canary(value):
    unused = 1  # F841: assigned but never used
    if value == None:  # E711: comparison to None
        pass
    if not value == 2:  # SIM201: `not ==`, where `!=` is meant
        pass
    under = helper(1,
        2)  # E128: continuation line under-indented for visual indent
    if (value and
        under):  # E129: visually indented line with same indent as next logical line
        pass
    over = helper(1,
                    2)  # E127: over-indented, which the house allows; must NOT be reported
    return under, over
