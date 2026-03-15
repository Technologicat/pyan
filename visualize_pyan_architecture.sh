#!/bin/bash
# Generate call graph visualizations of pyan's own architecture.
set -e

echo "Generating pyan architecture graphs..."

# Full call graph (uses edges only, colored, grouped)
pyan3 pyan/*.py --uses --no-defines --colored --grouped --nested-groups --dot >architecture.dot 2>architecture.log
dot -Tsvg architecture.dot >architecture.svg
echo "  architecture.{dot,svg} — full call graph"

# Class-level view (depth 2)
pyan3 pyan/*.py --uses --no-defines --colored --grouped --depth 2 --dot >architecture_classes.dot
dot -Tsvg architecture_classes.dot >architecture_classes.svg
echo "  architecture_classes.{dot,svg} — class-level view"

# Module-level view (import dependencies)
pyan3 --module-level pyan/ --dot --colored --grouped --nested-groups >architecture_modules.dot
dot -Tsvg architecture_modules.dot >architecture_modules.svg
echo "  architecture_modules.{dot,svg} — module imports"

echo "Done."
