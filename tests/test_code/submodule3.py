import test_code.subpackage2.submodule_hidden1

from test_code.subpackage1 import A2
from test_code.subpackage1 import EnumType


def test_3():
    print(A2.STATIC_VAL)
    print(EnumType.ENUM_1)
    return test_code.subpackage2.submodule_hidden1.test_func1()
