# modvis test fixtures

Two small packages (`pkg_a`, `pkg_b`) with cross-package imports and a deliberate import cycle (`alpha` ↔ `gamma`).

`pkg_b/delta.py` imports nothing, and `pkg_a/epsilon.py` imports only a name defined in `pkg_b/__init__.py`. Both are shapes whose edges used to vanish, so leave them as they are.

## Example commands

```bash
# Module dependency graph (default: omit __init__)
pyan3 --module-level tests/test_code_modvis/ --dot --root tests/test_code_modvis

# With __init__ modules and bidirectional edge merging
pyan3 --module-level tests/test_code_modvis/ --dot --concentrate --init --root tests/test_code_modvis

# Import cycle detection
pyan3 --module-level tests/test_code_modvis/ --cycles --root tests/test_code_modvis
```
