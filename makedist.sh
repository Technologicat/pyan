#!/bin/bash
# Build distribution using UV
# Usage: ./makedist.sh

set -e

echo "Building distribution with UV..."
uv build

echo "Distribution built successfully!"
ls -lh dist/
