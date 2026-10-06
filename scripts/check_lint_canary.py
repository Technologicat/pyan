#!/usr/bin/env python3
"""Whether the linters CI runs still report the violations we rely on them to catch.

A lint configuration can be narrower than it looks, and nothing says so: the run passes, and the checks were
not running. That happened once already — `select = ["E", ...]` reads as covering pycodestyle's error rules,
and enables none of the indentation family — and it is invisible by construction, since a clean result looks
the same whether the tree is clean or the rule is off.

So this lints `lint_canary_fixture.py`, which carries one deliberate violation per rule family, and fails
unless every one is reported. The commands are read out of the CI workflow rather than written here a second
time, so the canary cannot drift from what CI actually runs; only the target changes, to the fixture, and
pycodestyle's `--exclude`, which in CI lists the fixture. A code the house deliberately allows (E127) is in
the fixture too, and must stay unreported.

Exits 1 if a code is missing or an allowed one appears, and 2 if the workflow no longer has a command to read.
"""

import pathlib
import re
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
FIXTURE = pathlib.Path("scripts") / "lint_canary_fixture.py"

# What each linter must report on the fixture, and what it must not.
EXPECTED = {"ruff": {"F841", "E711", "SIM201"},
            "pycodestyle": {"E128", "E129"}}
ALLOWED_BY_THE_HOUSE = {"E126", "E127"}

# The blocking ruff run, and the pycodestyle run. CI runs both under `pdm run`, and so does this script, so the
# prefix is dropped: `ruff` and `python` then resolve to the same environment's.
_COMMANDS = {"ruff": re.compile(r"^\s*run:\s*(?:pdm run )?(ruff check \.(?:(?!\|\|).)*?)\s*$", re.MULTILINE),
             "pycodestyle": re.compile(r"^\s*run:\s*(?:pdm run )?(python -m pycodestyle .*?)\s*$", re.MULTILINE)}

_CODE = re.compile(r":\d+:\d+: ([A-Z]+\d+)\b")


def command_for(linter: str, workflow: str) -> list[str] | None:
    """Return CI's command for `linter`, retargeted at the fixture, or `None` if the workflow has none."""
    match = _COMMANDS[linter].search(workflow)
    if match is None:
        return None
    arguments = [argument for argument in shlex.split(match.group(1))
                 if not argument.startswith("--exclude")]
    arguments = [str(FIXTURE) if argument == "." else argument for argument in arguments]
    if arguments[0] == "python":
        # This interpreter, rather than whichever `python` the OS finds first: on Windows that search begins in
        # the running interpreter's own directory, which for a venv's launcher is the base installation's.
        arguments[0] = sys.executable
    if linter == "ruff":
        arguments += ["--no-cache", "--output-format", "concise"]  # where the output goes, not which rules
    return arguments


def main() -> int:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    problems = 0
    for linter, expected in EXPECTED.items():
        command = command_for(linter, workflow)
        if command is None:
            print(f"{WORKFLOW.relative_to(ROOT)}: no {linter} command found, so there is nothing to check; "
                  f"if the step was renamed or rewritten, update `_COMMANDS` here")
            return 2
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        reported = set(_CODE.findall(result.stdout))
        print(f"{linter}: {' '.join(command)}")
        print(f"    reported: {' '.join(sorted(reported)) or '(nothing)'}")
        if missing := expected - reported:
            print(f"    MISSING: {' '.join(sorted(missing))} — the rule is no longer running as CI runs it")
            if result.stderr.strip():
                print(f"    stderr: {result.stderr.strip()}")
            problems += 1
        if allowed := reported & ALLOWED_BY_THE_HOUSE:
            print(f"    UNEXPECTED: {' '.join(sorted(allowed))} — the house allows these, and CI now rejects them")
            problems += 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
