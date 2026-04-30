"""Import-resolution feature tests: chained re-export and aliased
attribute access.

Uses tests/test_code/imports/.
"""

from glob import glob
import logging
import os

import pytest

from pyan.analyzer import CallGraphVisitor
from tests.test_analyzer import get_in_dict

TESTS_DIR = os.path.dirname(__file__)
IMPORTS_DIR = os.path.join(TESTS_DIR, "test_code/imports")
IMPORTS_PREFIX = "test_code.imports"


@pytest.fixture
def v_imports():
    filenames = glob(os.path.join(IMPORTS_DIR, "**/*.py"), recursive=True)
    return CallGraphVisitor(filenames, logger=logging.getLogger())


def test_chained_import_resolution(v_imports):
    """consumer imports Widget via reexporter; should resolve to provider.Widget."""
    uses = get_in_dict(v_imports.uses_edges, f"{IMPORTS_PREFIX}.consumer.use_widget")
    names = [n.get_name() for n in uses]
    assert any("Widget" in n for n in names)


def test_attr_of_import(v_imports):
    """prov.helper() via `import ... as prov` should resolve."""
    uses = get_in_dict(v_imports.uses_edges, f"{IMPORTS_PREFIX}.attr_consumer.use_provider_attr")
    names = [n.get_name() for n in uses]
    assert any("helper" in n for n in names)
