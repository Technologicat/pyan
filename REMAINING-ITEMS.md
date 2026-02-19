# Remaining Work Items

## N-items (from recon)

| Item | Description | Size |
|------|-------------|------|
| N8 | Comprehensive test suite expansion | Large |
| N9/N10 | Type annotations | Large |

## D-items (deferred)

### Small — ✓ all done

| Item | Description | Status |
|------|-------------|--------|
| D1 | Rename `sanitize_exprs` → `canonize_exprs` | ✓ `38fffd0` |
| D2 | `resolve()` keyword-only params | ✓ `a402739` |
| D3 | Unify output formats (tgf/yed in `create_callgraph()`) | ✓ `600f724` |
| D4 | README badges | ✓ `6f48a78` |
| D5 | Sphinx extension verification | ✓ `4d1e196` |
| D16 | Review flake8 warnings (W503, E203, E741) | ✓ `1af4e31`..`9c9c45c` |

### Medium

| Item | Description | Status |
|------|-------------|--------|
| D6 | README: document `--module-level` + svg/html in modvis CLI | ✓ `831f31c` |
| D7 | `Del` context tracking | deferred |
| D8 | Iterator protocol tracking + `is_async` | deferred |
| D9 | modvis `filename_to_module_name` cwd fragility | ✓ `c9cc075`+`a310477` |
| D10 | `visit_Name` local variable noise | deferred |
| D11 | modvis plain-text output | deferred |

### Large (significant effort)

| Item | Description |
|------|-------------|
| D12 | Tuple unpacking with `Starred` |
| D13 | Per-comprehension scope isolation |
| D14 | "Node" terminology overload |
| D15 | modvis multi-project coloring |

## Also done this session

- CI: GitHub Actions test matrix (3.10–3.14) + flake8 lint
- CI: Coverage workflow with Codecov integration (73%)
- CI: Dependabot for GitHub Actions version updates
- README: CI status + codecov badges
- Flake8: zero warnings across codebase

## Canonical detail

See `TODO_DEFERRED.md` for full descriptions of each D-item.
