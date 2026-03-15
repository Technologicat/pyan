"""Module that accesses attributes of an imported module."""

import test_code.imports.provider as prov

def use_provider_attr():
    prov.helper()
    w = prov.Widget()
    w.activate()
