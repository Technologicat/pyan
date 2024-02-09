from ..submodule2 import test_2


class A:

    def __init__(self, b):
        self.a = None
        self.b = test_2(b)

    @staticmethod
    def test_static():
        pass


class A2:
    STATIC_VAL = 123
