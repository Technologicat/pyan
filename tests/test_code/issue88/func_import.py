# Function-level import: only caller() should get the edge, not non_caller().
def caller():
    from defines_myfunc import myfunc
    myfunc()

def non_caller():
    myfunc()
