# CC Brief: Python 3.15 support (pyan)

Third of three, alongside `mcpyrate/briefs/python-3.15-support.md` (which carries the full AST survey) and `unpythonic/briefs/python-3.15-support.md`. Those two are the macro layer; this one is the static analyzer, and it was the easy one to overlook — pyan has no macro layer, so it does not *look* like a project a Python version bump breaks. It reads the AST just as directly as the other two.

## Context

CPython 3.15 reached rc1 in August 2026. Three field changes across two PEPs, verified by diffing `Parser/Python.asdl` between the 3.14 and 3.15 tags:

```
-          | Import(alias* names)
-          | ImportFrom(identifier? module, alias* names, int? level)
+          | Import(alias* names, int? is_lazy)
+          | ImportFrom(identifier? module, alias* names, int? level, int? is_lazy)
-         | DictComp(expr key, expr value, comprehension* generators)
+         | DictComp(expr key, expr? value, comprehension* generators)
```

- **PEP 810** adds `lazy import x` / `lazy from x import y`, recorded as `is_lazy`.
- **PEP 798** allows unpacking in comprehensions. `{**d for d in dicts}` becomes `DictComp(key=d, value=None)` — the mapping goes in `key`, and `value` being `None` *is* the marker. `[*L for L in lists]` and its set and generator siblings put a `Starred` in `elt`, needing no grammar change.

## State of things, verified on 3.15.0rc1

### pyan crashes on a dict-unpacking comprehension

Not a silent wrong answer — a hard `AttributeError`, on any codebase containing `{**d for ...}`:

```
File "pyan/analyzer.py", line 1304, in analyze_comprehension
    self.visit(getattr(node, field2))
File "/usr/lib/python3.15/ast.py", line 309, in iter_fields
    for field in node._fields:
AttributeError: 'NoneType' object has no attribute '_fields'
```

Reproduced by running `CallGraphVisitor` over a two-line file containing `merged = {**d for d in dicts}`.

The mechanism: `visit_DictComp` (`analyzer.py:1205`) calls `analyze_comprehension(node, "dictcomp", field1="key", field2="value")`, and `analyze_comprehension` ends with `self.visit(getattr(node, field2))` (`:1304`). With `value` now `None` for the unpacking form, that visits `None`, and `ast.NodeVisitor.generic_visit` immediately asks it for `_fields`.

**The fix is to skip a field whose value is `None`**, which is also what CPython's own `generic_visit` does. Visiting `key` remains correct and sufficient: in the unpacking form `key` holds the whole mapping expression, so the names actually used are all reachable through it.

The docstring at `analyzer.py:1238–1239` needs correcting in the same edit — it currently states flatly that "DictComp uses `key` and `value`", which is now true only of the `k: v` form and is precisely the belief that produced the crash.

### What already works

Both verified by running the analyzer over probe files on 3.15, not by reading:

- **Lazy imports.** `lazy import json` and `lazy from pathlib import Path` analyze cleanly and bind their names as usual, because `visit_Import` / `visit_ImportFrom` (`analyzer.py:781,791`) read `names` and never touch the new field. Correct as-is: a lazy import creates the same name binding and the same dependency, so the call graph is unchanged.
- **Starred comprehension elements.** `[*L for L in lists]`, `{*L for L in lists}` and `(*L for L in lists)` all analyze without error — `elt` holds a `Starred`, and the generic path recurses into its `value`.

### The version cap is missing, and pyan is the project that actually breaks

`pyproject.toml` declares `requires-python = ">=3.10"` with **no upper bound**. So pip will install pyan on 3.15, where it crashes on input it is specifically built to read.

`unpythonic` caps at `<3.15` deliberately, for exactly this reason: an AST consumer should not run against a grammar it has not been taught. That cap is right, and pyan needs the same one.

In fact `unpythonic` is the *only* one of the three AST users that has it — `mcpyrate` also declares a bare `>=3.10`, and on 3.15 mcpyrate does not even import (its `source_to_code` override has the wrong signature for the new importlib protocol). So two of the three advertise support for the version that breaks them, and pyan is one of them.

**On timing.** A cap in the repo only reaches users through a release, so adding `<3.15` today protects nobody who has already installed pyan; meanwhile it would obstruct our own work, since `pdm venv create 3.15` followed by `pdm install` refuses a version the project excludes. So the sensible order is to land the fix first and then set the bound to `<3.16` with a 3.15 classifier, arriving at a cap that is *correct* rather than one that is temporarily defensive. If the fix slips far enough that a release goes out before it, cap at `<3.15` in that release instead.

## Work items

1. **Fix `analyze_comprehension` to skip a `None` field** (`analyzer.py:1304`), and correct the docstring at `:1238`.
2. **Regression test**, following the pattern already established for 3.12 syntax: a fixture module under `tests/test_code_315/` plus `@pytest.mark.skipif(sys.version_info < (3, 15), reason="...")`, as `tests/test_type_params.py` does for the `type` statement. Note pyan uses ordinary pytest — it has no macro layer, so none of the `unpythonic.test` machinery applies here.
   - Cover the crash case (`{**d for ...}`) and, since they are free once the fixture exists, the starred comprehension forms and a lazy import, so the passing cases stay passing.
3. **Add the missing `requires-python` upper bound**, which pyan should have had all along as the third AST user. Once 1 and 2 are green that bound is `<3.16`, landing together with the 3.15 classifier and the CI matrix entry — see "On timing" above for why it is not added ahead of the fix.

## Possible enhancement, not a defect

pyan currently renders a lazy import identically to an eager one. For a *call* graph that is right — the dependency exists either way. For the *module* dependency graph (`modvis.py`) there is an argument for distinguishing them, since a lazy edge does not contribute to import-time cost, and telling the two apart is most of the reason PEP 810 exists. Worth considering only if someone wants it; it is a feature, and nothing is wrong without it.
