"""Tests for the --exclude / -x option."""

import os

from pyan.anutils import _matches_exclude, expand_sources

TESTS_DIR = os.path.dirname(__file__)
TEST_CODE_DIR = os.path.join(TESTS_DIR, "test_code")


# --- Low-level: _matches_exclude ---

class TestMatchesExclude:
    def test_basename_pattern(self):
        assert _matches_exclude("/some/path/test_foo.py", ["test_*.py"])

    def test_basename_no_match(self):
        assert not _matches_exclude("/some/path/foo.py", ["test_*.py"])

    def test_path_pattern(self):
        assert _matches_exclude("/project/tests/foo.py", ["*/tests/*"])

    def test_path_pattern_no_match(self):
        assert not _matches_exclude("/project/src/foo.py", ["*/tests/*"])

    def test_multiple_patterns_any_match(self):
        assert _matches_exclude("/a/test_bar.py", ["conftest.py", "test_*.py"])

    def test_multiple_patterns_none_match(self):
        assert not _matches_exclude("/a/foo.py", ["conftest.py", "test_*.py"])


# --- expand_sources with exclude ---

class TestExpandSourcesExclude:
    def test_exclude_by_basename(self):
        all_files = expand_sources([TEST_CODE_DIR])
        excluded = expand_sources([TEST_CODE_DIR], exclude=["__init__.py"])
        assert len(excluded) < len(all_files)
        assert all("__init__.py" not in f for f in excluded)

    def test_exclude_no_patterns(self):
        """No exclusion when exclude is None or empty."""
        a = expand_sources([TEST_CODE_DIR])
        b = expand_sources([TEST_CODE_DIR], exclude=None)
        c = expand_sources([TEST_CODE_DIR], exclude=[])
        assert a == b == c

    def test_exclude_everything(self):
        """Excluding *.py removes all results."""
        result = expand_sources([TEST_CODE_DIR], exclude=["*.py"])
        assert result == []


# --- CLI integration ---

from pyan.main import main as callgraph_main
from pyan.modvis import main as modvis_main


class TestCLIExclude:
    def test_callgraph_exclude(self, capsys):
        """--exclude filters files before analysis."""
        # Analyze test_code/ but exclude features.py — should still work
        # (submodule1.py and submodule2.py remain).
        callgraph_main([
            os.path.join(TEST_CODE_DIR, "*.py"),
            "--exclude", "features.py",
            "--exclude", "__init__.py",
            "--text",
        ])
        output = capsys.readouterr().out
        # features.py defines things in "test_code.features" namespace
        assert "features" not in output

    def test_modvis_exclude(self, capsys):
        """--module-level --exclude filters files before analysis."""
        modvis_main([
            os.path.join(TEST_CODE_DIR, "*.py"),
            "--exclude", "features.py",
            "--text",
        ])
        output = capsys.readouterr().out
        assert "features" not in output


# --- API integration ---

from pyan import create_callgraph, create_modulegraph


class TestAPIExclude:
    def test_create_callgraph_exclude(self):
        result = create_callgraph(
            filenames=os.path.join(TEST_CODE_DIR, "*.py"),
            exclude=["features.py", "__init__.py"],
            format="text",
        )
        assert "features" not in result

    def test_create_modulegraph_exclude(self):
        result = create_modulegraph(
            filenames=os.path.join(TEST_CODE_DIR, "*.py"),
            exclude=["features.py"],
            format="text",
        )
        assert "features" not in result
