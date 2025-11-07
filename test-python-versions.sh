#!/bin/bash
# Test pyan3 across different Python versions
# Usage: ./test-python-versions.sh

set -e

echo "Running pyan3 test suite across available Python versions..."

PYTHON_VERSIONS=("python3.9" "python3.10" "python3.11" "python3.12")

test_python_version() {
    local python_cmd=$1
    echo "----------------------------------------"
    echo "Testing with $python_cmd"
    echo "----------------------------------------"
    
    # Check if Python version is available
    if ! command -v "$python_cmd" &> /dev/null; then
        echo "❌ $python_cmd not found, skipping..."
        return 0
    fi

    # Get Python version
    local version=$($python_cmd --version 2>&1)
    echo "✅ Found: $version"
    
    # Ensure basic import still works before installing
    echo "Testing import..."
    if $python_cmd -c "import pyan; print(f'✅ Import successful for {pyan.__version__}')"; then
        echo "✅ Module imports successfully"
    else
        echo "❌ Import failed"
        return 1
    fi

    echo "Checking test dependencies..."
    if $python_cmd -c "import pytest, coverage" >/dev/null 2>&1; then
        echo "✅ Test dependencies already present"
    else
        echo "Testing dependencies not present. Install them by running 'uv sync --extra test'."
        return 1
    fi

    echo "Running pytest..."
    if $python_cmd -m pytest tests -q; then
        echo "✅ Tests passed"
    else
        echo "❌ Tests failed"
        return 1
    fi

    echo "✅ $python_cmd verification completed"
    echo ""
}

# Test each Python version
failed_versions=()
for python_version in "${PYTHON_VERSIONS[@]}"; do
    if ! test_python_version "$python_version"; then
        failed_versions+=("$python_version")
    fi
done

# Summary
echo "========================================="
echo "SUMMARY"
echo "========================================="
if [ ${#failed_versions[@]} -eq 0 ]; then
    echo "✅ All available Python versions passed!"
else
    echo "❌ Failed versions: ${failed_versions[*]}"
    exit 1
fi
