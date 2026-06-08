# CI Code Coverage Gates & Scheduler Integration Testing

## Overview

Automated quality assurance relies on objective metric gating (code coverage) and comprehensive integration tests that mimic complex, cron-like loop lifecycles. This guide defines standard configuration recipes and mocking patterns for both Python (backend) and TypeScript (frontend).

---

## 1. Automated Code Coverage Gating (fail-under)

Enforcing a minimum coverage bar prevents test quality from eroding as new features are added.

### 🐍 Python Backend (coverage.py + pytest)

To measure actual application code (avoiding bloating figures with test files or generated migrations), configure `pyproject.toml` to target strictly your source directory (`app`) and omit testing/migrations artifacts:

```toml
[tool.coverage.run]
source = ["app"]
omit = [
    "tests/*",
    "alembic/*",
    "scripts/*",
    "app/seed/*"
]

[tool.coverage.report]
fail_under = 70
show_missing = true
```

#### 🚀 Running Backend Coverage

To collect coverage and fail the execution if it falls under your `fail_under` threshold, execute:

```bash
# Run tests under coverage measurement
PYTHONPATH=. uv run coverage run -m pytest

# Output report and check threshold
PYTHONPATH=. uv run coverage report
```

---

### ⚛️ React Frontend (Vitest + @vitest/coverage-v8)

Configure a lines-of-code coverage gate directly inside the `test` block of your `vitest.config.ts` using the V8 provider:

```typescript
import { defineConfig } from 'vitest/config';
react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      thresholds: {
        lines: 55, // Strict fail-under line-coverage percentage
      },
    },
  },
});
```

#### 🚀 Running Frontend Coverage

Execute coverage checks in CI/CD by running:

```bash
npm test -- --coverage
```

*Note: Ensure `coverage/` is added to your frontend `.gitignore` so local HTML/JSON coverage reports are never committed into git history.*

---

## 2. Mock-Driven Poller & Scheduler Integration Testing

Testing deep asynchronous polling loops (`run_poll_cycle()`) that execute transactions independent of the standard HTTP request lifecycle requires binding the background session maker to the test database engine, mocking out hours gates, and simulating consecutive external API events.

### 🧪 Integration Testing Recipe

When testing a polling cycle that triggers external network fetches (such as ESPN API calls) and acts on completion to auto-finalize standings:

1. **Bind Session Factories:** If the poller opens independent database sessions via a global `async_session_factory()`, override or rebind that session maker to the test `db_engine` in your test fixture. When testing on an in-memory SQLite `StaticPool`, binding both the poller session maker and the test thread's `db_session` to the same engine guarantees they see the same data in real-time.
2. **Mock Clock & Hour Gates:** Mock timezone-dependent play hours filters (`is_during_tournament_hours`) to return `True` to allow execution under the test clock.
3. **Simulate Sequence of API Responses:** Mock external network clients (`espn_client`) to simulate:
   - *Active Round State:* Returns an in-progress round status (`status_completed = False`) to verify that the poller upserts results but does not touch scoring finalizations.
   - *Final Completed State:* Returns a completed round status (`STATUS_FINAL`, `status_completed = True`) to verify that completion is detected, scoring engines auto-finalize player rosters, and overall season standings are updated with the correct aggregate results.

#### 📝 Reference Python Test Pattern

```python
@pytest.fixture
async def _bind_poller_session_factory(db_engine, monkeypatch):
    """Binds background session factory to test engine so poller sees test data."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    import app.services.espn_poller as poller_module

    test_factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(poller_module, "async_session_factory", test_factory)


async def test_run_poll_cycle_polls_and_auto_finalizes(
    _bind_poller_session_factory, db_session, test_season, monkeypatch
):
    # 1. Seed complete season and active tournament
    today = date.today()
    tournament = Tournament(
        season_id=test_season.id,
        name="Mock Major",
        start_date=today - timedelta(days=1),
        end_date=today + timedelta(days=1),
        picks_lock_at=datetime(2099, 1, 1),
        espn_event_id="evt-completed",
        is_complete=False,
        sequence=1,
    )
    db_session.add(tournament)
    await db_session.commit()

    # 2. Mock play hours and ESPN API client responses
    import app.services.espn_poller as poller_module
    monkeypatch.setattr(poller_module, "is_during_tournament_hours", lambda **kw: True)

    async def mock_fetch_leaderboard(event_id):
        return [ESPNGolferResult(golfer_id=1, total_score="E", position=1)]

    async def mock_fetch_event_status(event_id):
        return {
            "status_name": "STATUS_FINAL",
            "status_completed": True,
            "status_detail": "Final",
        }

    monkeypatch.setattr(poller_module.espn_client, "fetch_leaderboard", mock_fetch_leaderboard)
    monkeypatch.setattr(poller_module.espn_client, "fetch_event_status", mock_fetch_event_status)

    # 3. Execute poller cycle
    summary = await poller_module.run_poll_cycle(force=True)

    # 4. Assertions: Polling upserted results & auto-finalized scores
    assert len(summary["tournaments"]) == 1
    
    # Reload from DB and verify completion
    await db_session.refresh(tournament)
    assert tournament.is_complete is True
    
    # Verify player scores are generated and standings are updated
    scores = (await db_session.execute(select(PlayerScore))).scalars().all()
    assert len(scores) > 0
```
