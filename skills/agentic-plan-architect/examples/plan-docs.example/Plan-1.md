# Plan 1: Add the Behavior

**Goal:** Deliver the new behavior with regression coverage.

## Batch 1: Implementation

**Goal:** Implement and verify the behavior.

### Task T1: Add the behavior

**Files:**
- Modify: `src/module.py`
- Test: `tests/test_module.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `normalize(value: str) -> str` in `src/module.py`.

**Acceptance:** A1: `normalize` passes the regression test; A2: existing behavior unchanged.

- [ ] **Step 1: Write the failing regression test**

```python
from src.module import normalize

def test_normalize_strips_and_lowercases():
    assert normalize("  Hello World  ") == "hello world"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_module -v`
Expected: FAIL with `ImportError: cannot import name 'normalize'`

- [ ] **Step 3: Implement the minimal change**

```python
def normalize(value: str) -> str:
    return value.strip().lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_module -v`
Expected: PASS

- [ ] **Step 5: Run the focused verification**

Run: `python -m unittest tests -v`
Expected: all tests pass, no public interface change.
