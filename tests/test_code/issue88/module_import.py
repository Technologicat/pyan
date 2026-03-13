# Module-level import: both functions should see myfunc.
from defines_myfunc import myfunc

def caller_a():
    myfunc()

def caller_b():
    myfunc()
