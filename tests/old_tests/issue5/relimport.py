# -*- coding: utf-8; -*-
# See issue #5

from . import mod1  # noqa
from . import mod1 as moo  # noqa
from ..mod3 import bar  # noqa: F401  # test fixture
from .mod2 import foo  # noqa: F401  # test fixture
