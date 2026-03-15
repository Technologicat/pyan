#!/bin/bash
# Build sdist and wheel.
set -e
uv build
ls -lh dist/
