from pkg_with_all import *  # noqa: F401, F403
from pkg_private import *  # noqa: F401, F403


def use_with_all():
    alpha()  # noqa: F405 — from pkg_with_all's __all__
    _helper()  # noqa: F405 — leading underscore, but listed in __all__


def use_private():
    pub()  # noqa: F405 — non-underscore, brought in by public-names rule
