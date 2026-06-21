import othermod  # imported, but NOT part of the analyzed source set

def func_a():
    othermod.cache()  # call on the imported module; must NOT bind to local cache()

def cache():
    pass

def caller():
    helper()  # genuine intra-module call (positive control)

def helper():
    pass
