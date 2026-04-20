from common.file1 import fn1
from common import fn2
from common import *  # noqa: F401, F403


def fn_parent():
    fn1()
    fn2()
    fn3()  # noqa: F405  — bound by the wildcard import above
