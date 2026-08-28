# Resolving Pytest-Asyncio Non-Async Test Marker Warnings

## Problem Description

When running test suites with `pytest-asyncio`, you may encounter warnings like:

```text
PytestWarning: The test <Function test_some_sync_logic> is marked with '@pytest.mark.asyncio' but it is not an async function. Please remove the asyncio mark. If the test is not marked explicitly, check for global marks applied via 'pytestmark'.
```

This warning occurs when a test case is marked as an asynchronous test (`@pytest.mark.asyncio`) but is declared using a standard synchronous Python function (`def` instead of `async def`).

---

## Why It Happens

This most frequently happens in two scenarios:

1. **Global Module-Level Marks:** The test file defines a global module-level mark at the top:
    ```python
    pytestmark = pytest.mark.asyncio
    ```
    This instructs pytest to automatically apply the `@pytest.mark.asyncio` decorator to **every single test case** in the file, regardless of whether it is asynchronous or synchronous.
2. **Class-Level Marks:** A test class applies the mark to all its members:
    ```python
    @pytest.mark.asyncio
    class TestMathAndDBLogic:
        # Async tests are fine:
        async def test_db_insert(self): ...
        
        # Sync tests will raise the warning:
        def test_pure_formula(self): ...
    ```

Mixing pure-synchronous computational logic unit tests (e.g., parsing formulas, math matrices, config overrides) with database/network async tests in the same globally marked class/file triggers these noisy warnings.

---

## Symmetrical Correctness Strategies

To maintain a clean, warning-free test output:

### Strategy A: Segregate Sync and Async Tests (Recommended)
Isolate purely synchronous, computational unit tests into their own distinct test classes or files that **do not** carry the class-level or module-level `pytest.mark.asyncio` decorator:

```python
# Segment 1: Pure Sync Unit Tests (No async mark)
class TestPureCalculations:
    def test_pure_sync_logic(self):
        result = compute_points(10)
        assert result == 5

# Segment 2: Async DB/Integration Tests (Explicitly marked)
@pytest.mark.asyncio
class TestDatabaseIntegration:
    async def test_async_database_insert(self, db_session):
        await save_record(db_session)
        assert True
```

### Strategy B: Use Explicit Per-Method Marks (No Module-Level `pytestmark`)
Instead of applying `pytestmark = pytest.mark.asyncio` at the top of the file, remove the module-wide mark and explicitly decorate **only** the specific asynchronous tests:

```python
# Remove: pytestmark = pytest.mark.asyncio

def test_sync_pure_math():
    assert 1 + 1 == 2

@pytest.mark.asyncio
async def test_async_fetch():
    data = await fetch_api()
    assert data is not None
```

By keeping pure unit tests and integration tests cleanly separated, you prevent test-runner warnings and speed up your local execution suites!
