# Calls myfunc() after importing it. Should create a cross-module edge.
from defines_myfunc import myfunc
myfunc()
