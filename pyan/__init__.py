#!/usr/bin/env python3

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("pyan3")
except PackageNotFoundError:
    __version__ = "unknown"

from .main import create_callgraph, main  # noqa: F401
