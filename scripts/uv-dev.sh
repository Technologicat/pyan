#!/bin/bash
# Helper CLI for common UV workflows in the pyan3 repository.

set -euo pipefail

PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

usage() {
    cat <<'EOF'
Usage: scripts/uv-dev.sh [command]

Commands:
  setup           Install editable package plus dev & test extras (uv sync)
  test            Run the project test suite (pytest)
  lint            Run ruff lint checks
  format          Run ruff formatter
  build           Build sdist and wheel via uv build
  shell           Launch a Python REPL inside the UV project environment
  test-matrix     Run multi-version test matrix (scripts/test-python-versions.sh)
  menu            Launch interactive selector (default when no args)

Examples:
  scripts/uv-dev.sh            # interactive menu
  scripts/uv-dev.sh setup
  scripts/uv-dev.sh test-matrix

EOF
}

require_uv() {
    if ! command -v uv >/dev/null 2>&1; then
        echo "❌ uv is required but not installed. See https://astral.sh/uv/ for instructions." >&2
        exit 1
    fi
}

run_in_project() {
    (cd "${PROJECT_ROOT}" && "$@")
}

menu() {
    require_uv
    while true; do
        cat <<'EOF'

Select an action:
  1) setup        - Install editable project with dev+test extras
  2) test         - Run pytest
  3) lint         - Run ruff check
  4) format       - Run ruff format
  5) build        - Build distributions
  6) shell        - Launch Python REPL (uv run python)
  7) test-matrix  - Run multi-version test sweep
  q) quit

EOF
        read -rp "Enter choice: " choice
        case "${choice}" in
            1) run_in_project uv sync --locked --extra dev --extra test ;;
            2) run_in_project uv run --locked pytest tests -q ;;
            3) run_in_project uv run --locked ruff check ;;
            4) run_in_project uv run --locked ruff format ;;
            5) run_in_project uv build ;;
            6) run_in_project uv run --locked python ;;
            7) run_in_project scripts/test-python-versions.sh ;;
            q|Q) echo "Goodbye!"; break ;;
            *) echo "Unknown selection." ;;
        esac
    done
}

if [ $# -lt 1 ]; then
    menu
    exit 0
fi

COMMAND=$1
shift || true

require_uv

case "${COMMAND}" in
    setup)
        run_in_project uv sync --locked --extra dev --extra test
        ;;
    test)
        run_in_project uv run --locked pytest tests -q "$@"
        ;;
    lint)
        run_in_project uv run --locked ruff check "$@"
        ;;
    format)
        run_in_project uv run --locked ruff format "$@"
        ;;
    build)
        run_in_project uv build "$@"
        ;;
    shell)
        run_in_project uv run --locked python "$@"
        ;;
    test-matrix)
        run_in_project scripts/test-python-versions.sh "$@"
        ;;
    menu)
        menu
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "Unknown command: ${COMMAND}" >&2
        usage
        exit 1
        ;;
esac


