# modvis test fixtures

Two small packages (`pkg_a`, `pkg_b`) with cross-package imports and a deliberate import cycle (`alpha` ↔ `gamma`).

## Example commands

```bash
# Module dependency graph (default: omit __init__)
pyan3 --module-level tests/test_code_modvis/ --dot --root tests/test_code_modvis

# With __init__ modules and bidirectional edge merging
pyan3 --module-level tests/test_code_modvis/ --dot --concentrate --init --root tests/test_code_modvis

# Import cycle detection
pyan3 --module-level tests/test_code_modvis/ --cycles --root tests/test_code_modvis
```
