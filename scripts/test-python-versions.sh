#!/bin/bash
# UV-powered multi-version test runner
# Usage: scripts/test-python-versions.sh

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_VERSIONS=("3.9" "3.10" "3.11" "3.12")

if ! command -v uv >/dev/null 2>&1; then
    echo "❌ uv is required to run this script. Install it from https://astral.sh/uv/"
    exit 1
fi

run_for_version() {
    local version="$1"
    echo "----------------------------------------"
    echo "Testing with Python ${version}"
    echo "----------------------------------------"

    if ! uv python install "${version}" >/dev/null 2>&1; then
        echo "❌ Failed to provision Python ${version} via uv"
        return 1
    fi

    if uv run --project "${PROJECT_ROOT}" \
        --python "${version}" \
        --isolated \
        --locked \
        --extra test \
        pytest tests -q; then
        echo "✅ Tests passed for Python ${version}"
    else
        echo "❌ Tests failed for Python ${version}"
        return 1
    fi

    echo "✅ Completed Python ${version}"
    echo ""
}

echo "Running pyan3 test suite across Python ${PYTHON_VERSIONS[*]}"

failed_versions=()
for version in "${PYTHON_VERSIONS[@]}"; do
    if ! run_for_version "${version}"; then
        failed_versions+=("${version}")
    fi
done

echo "========================================="
echo "SUMMARY"
echo "========================================="
if [ ${#failed_versions[@]} -eq 0 ]; then
    echo "✅ All configured Python versions passed!"
else
    echo "❌ Failures encountered for: ${failed_versions[*]}"
    exit 1
fi
