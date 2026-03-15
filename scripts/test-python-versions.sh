#!/bin/bash
# Multi-version test runner.
# Usage: scripts/test-python-versions.sh
#
# Runs the test suite against each Python version in the matrix.
# Uses uv to provision interpreters if needed.

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_VERSIONS=("3.10" "3.11" "3.12" "3.13" "3.14")

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. See https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

run_for_version() {
    local version="$1"
    echo "--- Python ${version} ---"

    if ! uv python install "${version}" >/dev/null 2>&1; then
        echo "SKIP: could not provision Python ${version}"
        return 1
    fi

    if uv run --project "${PROJECT_ROOT}" \
        --python "${version}" \
        --isolated \
        --extra test \
        pytest tests -q; then
        echo "PASS: Python ${version}"
    else
        echo "FAIL: Python ${version}"
        return 1
    fi
    echo
}

echo "Testing pyan3 against Python ${PYTHON_VERSIONS[*]}"
echo

failed=()
for version in "${PYTHON_VERSIONS[@]}"; do
    if ! run_for_version "${version}"; then
        failed+=("${version}")
    fi
done

echo "=== Summary ==="
if [ ${#failed[@]} -eq 0 ]; then
    echo "All versions passed."
else
    echo "Failures: ${failed[*]}"
    exit 1
fi
