"""Module that imports via the re-exporter (chained import resolution)."""

from test_code.imports.reexporter import Widget

def use_widget():
    w = Widget()
    w.activate()
