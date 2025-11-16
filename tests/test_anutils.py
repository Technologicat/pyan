from glob import glob
import logging
import os

import pytest

from pyan.anutils import get_module_name


def test_get_module_name_filename_not_existing():
    mod_name = get_module_name("just_filename.py")
    assert mod_name == "just_filename"


def test_get_module_name_absolute():
    mod_name = get_module_name(__file__)
    assert mod_name == "test_anutils"


def test_get_module_name_absolute_not_existing():
    with pytest.raises(FileNotFoundError) as e_info:
        get_module_name("/not/existing/abs_path/mod.py")

    mod_name = get_module_name("/not/existing/mod_dir/mod.py", "mod_dir")
    assert mod_name == ".not.existing.mod_dir.mod"

    mod_name = get_module_name("/not/existing/mod_dir/mod.py", "invalid_root")
    assert mod_name == ".not.existing.mod_dir.mod"
