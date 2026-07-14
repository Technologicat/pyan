# A leaf module: no imports at all.
#
# Regression fixture for the bug where modvis only registered modules that
# imported something, so an import-less module got no node and every edge
# into it was silently dropped.

DELTA_CONST = 23
