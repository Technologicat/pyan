# Development Setup with uv

This document walks you through setting up a development environment for Pyan3 using [uv](https://docs.astral.sh/uv/).


## 1. Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

To check that it's installed:

```bash
uv --version
```

The installer places the executable in `~/.local/bin` (Linux/macOS) or `%USERPROFILE%\.local\bin` (Windows). Make sure it's on your `PATH`.

See the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/) for other methods (Homebrew, pipx, etc.) and platform-specific details.


## 2. Project setup

From the repository root:

```bash
# Create a .venv and install pyan3 in editable mode with test dependencies
uv sync --extra test
```

This creates `.venv/` (if it doesn't exist) and installs all dependencies.

Alternatively, to use a specific Python version:

```bash
uv venv --python 3.14 .venv
uv sync --extra test
```

`uv` can use system Pythons or download its own — see `uv python list` to see what's available, and `uv python install 3.14` to download one.


## 3. Everyday tasks

```bash
# Run the CLI
uv run pyan3 --help

# Run tests
uv run pytest tests/ -v

# Lint
uv run ruff check .

# Coverage report
uv run pytest tests/ --cov=pyan --cov-branch --cov-report=term-missing

# Build sdist/wheel
uv build
```


## 4. Testing across Python versions

Pyan3 supports Python 3.10–3.14. If you have multiple interpreters installed (e.g. from [deadsnakes](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) on Ubuntu), you can test against each:

```bash
python3.10 -m pytest tests/ -v -o "addopts="
python3.12 -m pytest tests/ -v -o "addopts="
```

The `-o "addopts="` override is needed to skip the coverage options configured in `pytest.ini` (which require the test extras to be installed in that interpreter's environment).

The `scripts/test-python-versions.sh` helper automates this for all detected interpreters.


## 5. Contributing

1. Fork the repository and create a topic branch.
2. Follow the instructions above to set up and run tests.
3. Keep commits focused; add tests when fixing bugs or adding features.
4. Lint with `uv run ruff check .` before opening a PR.
5. Open a Pull Request describing the change, referencing any related [issue](https://github.com/Technologicat/pyan/issues).
