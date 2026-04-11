"""Test input for PEP 695 generic syntax (Python 3.12+).

Covers: generic classes, generic functions, generic methods,
nested generics, multiple type parameters, bounded type params,
type param shadowing.
"""


# --- Generic class (the original crash from #123) ---

class Container[T: object]:
    def fetch(self):
        return None

    def store(self, item):
        pass


# --- Generic function ---

def transform[T](x: T) -> T:
    return x


# --- Generic class with multiple type parameters ---

class Mapper[K, V]:
    def get(self, key: K) -> V:
        return None

    def put(self, key: K, value: V):
        pass


# --- Generic method inside a generic class ---

class Box[T]:
    def map[U](self, func) -> U:
        return func(self)


# --- Nested generic classes ---

class Outer[T]:
    class Inner[U]:
        def method(self):
            pass


# --- Generic function calling another function ---

def identity[T](x: T) -> T:
    return x

def apply_identity[T](x: T) -> T:
    return identity(x)


# --- Non-generic class using a generic function ---

class Processor:
    def run(self):
        return transform(42)


# --- Type param shadowed in class body ---
#
# In Python, the type-param scope is a closure between the enclosing
# scope and the class scope.  Methods close over the type-param scope,
# NOT the class scope (class scope is not a closure scope).  So even
# with T = "shadowed" in the class body, method bodies see the
# original type-param T.

class Shadowed[T]:
    T = "not the type param"

    def method(self):
        return T  # sees the type-param T, not the class-body T
