# Contributing

Welcome to the pyan3 contributor guide! This document assumes you are new to
[uv](https://astral.sh/uv) and walks you through the entire workflow: installing
uv, provisioning Python interpreters, creating environments, and running the
project.

## 1. Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex
```

The installer places the executable in `~/.cargo/bin`. If that directory is not
on your `PATH`, add it:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

Verify the installation:

```bash
uv --version
```

## 2. Manage Python versions with uv

uv can download and manage multiple Python installs side-by-side (stored under
`~/.cache/uv/python`). Examples:

```bash
# Install interpreters you want available
uv python install 3.9 3.10 3.11 3.12

# List everything uv knows about
uv python list --all
uv python list --installed

# Run a command with a specific interpreter
uv python 3.11 -- python -V
uv python 3.10 -- pip list
```

You can also create virtual environments explicitly:

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

## 3. Project setup (editable install)

From the repository root:

```bash
# Install the package in editable mode with dev + test extras
uv sync --extra dev --extra test
```

`uv sync` creates or updates the local project environment (default: `.venv/`)
and installs dependencies pinned in `uv.lock`.

### Quick wrapper CLI

For convenience, the repository ships with `scripts/uv-dev.sh`:

```bash
scripts/uv-dev                 # Interactive mode
scripts/uv-dev.sh setup        # Equivalent to uv sync --extra dev --extra test
scripts/uv-dev.sh test         # Run pytest
scripts/uv-dev.sh lint         # Ruff lint
scripts/uv-dev.sh build        # uv build
scripts/uv-dev.sh shell        # Python REPL inside the project env
scripts/uv-dev.sh test-matrix  # Multi-version test sweep via uv-managed venvs
```

Run `scripts/uv-dev.sh --help` for the full list of commands.

## 4. Everyday tasks

```bash
# Run CLI locally (uses project environment)
uv run pyan3 --help

# Execute the test suite
uv run pytest tests -q

# Lint / format
uv run ruff check
uv run ruff format

# Build sdist/wheel
uv build

# Run coverage-enabled tests
uv run pytest tests -q --cov=pyan

# Launch a Python shell with project dependencies available
uv run python
```

To exercise the test matrix across multiple interpreters, use
`scripts/test-python-versions.sh`. The script will:

1. Ensure the requested Python versions are installed via `uv python install`.
2. Create dedicated environments under `.uv-venvs/`.
3. Install the project with test extras.
4. Run `pytest` in each environment.

## 5. Answers to common onboarding questions

**Does uv create a virtual environment for the project automatically?**

- Yes. `uv sync` creates/updates a project environment (default `.venv/`).
- You can override the target directory with `uv sync --venv-path <path>` or by
  creating explicit envs with `uv venv`.

**How do I install an editable copy of the package?**

- `uv sync --extra dev --extra test` installs the project in editable mode.
- Alternatively use `uv pip install -e '.[dev,test]'` if you prefer pip syntax.

**How do I run tests?**

- `uv run pytest tests -q` executes the standard suite.
- Use `scripts/uv-dev.sh test` for a shorthand.
- Run `scripts/test-python-versions.sh` to sweep the matrix (Python 3.9–3.12).

**How do I build the package?**

- `uv build` produces both the wheel and sdist under `dist/`.
- `scripts/uv-dev.sh build` is a wrapper.

**How do I manage multiple Python versions?**

- `uv python install <version>` downloads an interpreter.
- `uv python list --installed` shows available versions.
- `uv python 3.11 -- <command>` runs a command using that interpreter.

**Can I use uv with an existing venv or conda environment?**

- Yes. Activate your environment first, then run `uv sync`. uv will install into
  the active interpreter instead of creating `.venv`.

## 6. Coding guidelines

* Python 3.9+ typing standards (use built-in collection types).
* Ruff enforces lint + formatting; run `scripts/uv-dev.sh lint` before opening a PR.
* Please add or update tests when fixing bugs or implementing new features.

## 7. Submitting changes

1. Fork the repository and create a topic branch.
2. Follow the instructions above to install dependencies and run tests.
3. Keep commits focused; add tests and documentation when relevant.
4. Open a Pull Request describing the change, referencing any related issue
   (e.g., #105 for analyzer tests).
5. Be prepared to iterate based on review feedback.

