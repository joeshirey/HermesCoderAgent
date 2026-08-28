# Time-Sensitive & Business Constraint Testing Pitfalls

Guidelines for writing robust backend integration tests that involve time-dependent database states, dynamic mock calendars, and downstream constraint validations.

---

## 1. Time-Sensitive / Date-Dependent Gated State Pitfall

### The Symptom
An integration test or admin route assertion (like setting manual overrides or modifying rosters pre-lock) fails with:
```
assert res_val.status_code == 200 (where status_code is 400 Bad Request)
```
with details indicating that the tournament or session is locked and cannot be modified.

### The Cause
The model or service contains dynamic properties (like `is_locked` or `is_active`) determined by comparing `datetime.now(UTC)` against stored date/time values (like `picks_lock_at` or `start_date`). If your mock test data seeds hardcoded past dates (e.g. `2026-04-10` during a test execution in June 2026), the database entity is automatically considered locked or finished from the very first line of the test.

### The Solution
For test cases that assert pre-lock or active-play states, always use dynamic offsets or a safe future year (such as `2029` or `2030`) so that the test data remains unlocked under temporal checks:

```python
# Avoid hardcoding past years (e.g., 2026-04-10) for pre-lock test datasets
res = await admin_client.post(
    "/api/admin/tournaments",
    json={
        "season_id": test_season.id,
        "name": "Active Skins Game",
        "start_date": "2029-04-10",
        "end_date": "2029-04-13",
        "picks_lock_at": "2029-04-10T08:00:00Z", # Safely in the future
        "entry_fee": 25,
    },
)
```

---

## 2. Business Constraint Under-Seeding Trap (e.g., `/publish-values`)

### The Symptom
An endpoint transition test (like `/publish-values` or `/finalize`) returns a `400 Bad Request` with errors like:
```
Need at least 5 golfers in the field to publish; only 1 present.
```
or:
```
No valid roster is possible: the cheapest golfers sum to 50, above the value cap of 15.
```

### The Cause
FastAPI routes and business-logic controllers enforce strict constraint validations before completing major state transitions (e.g. checking that the field is actually playable, checking salary caps, or verifying rosters). A naive integration test that only seeds a single dummy entity (like 1 golfer) to quickly test the route will violate these hidden constraints, returning a `400`.

### The Solution
Always identify and satisfy the business-level default constraints inside your test setup blocks:
1. **Seed the minimum playable count:** If the controller requires `max_picks` (e.g. 5) entities to proceed, seed exactly that number.
2. **Respect the mathematical boundary limits:** Set values such that the total sum of the cheapest entities satisfies the `value_cap` (e.g. setting golfer values to `2` each to sum to `10`, which safely clears a default value cap of `15`).

```python
# 1. Seed 5 golfers to meet the minimum max_picks field requirement
golfers = []
for i in range(5):
    g = Golfer(external_id=f"888{i}", first_name=f"Player{i}", last_name=f"Test{i}")
    db_session.add(g)
    golfers.append(g)
await db_session.commit()

# 2. Set golfer values to 2 (total 10) to stay within the default value_cap (15)
for g in golfers:
    await admin_client.put(
        f"/api/admin/tournaments/{bet_id}/golfer-values/{g.id}",
        json={"value": 2},
    )
```

---

## 3. Frontend Component Clock Mocking (Vitest / Jest)

### The Symptom
Frontend test suites that render date-sensitive elements (such as a lock deadline widget, side-bets action button, or signup countdown) pass when written, but suddenly fail weeks or months later once the real-world calendar moves past the hardcoded test deadlines (known as a "test time-bomb").

```
AssertionError: expected "Picks open soon" but got "Picks locked"
```

### The Cause
The component uses dynamic client-side dates (e.g. `new Date()`) to determine whether actions are active, comparing the *actual real execution time* of the test runner against the mock tournament schedule. If the tournament's lock date is hardcoded to `2026-06-29` and the test runs in July 2026, the real-world clock has passed the deadline, causing different UI branches to execute.

### The Solution
Use Vitest or Jest system clock mock utilities to pin the runner's execution date to a safe, deterministic point *before* your mock data's locking threshold. Always clean up the mocked clock in `afterEach` to avoid drifting subsequent test blocks.

#### Vitest Implementation
```typescript
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SideBetsWidget } from './SideBetsWidget';

describe('SideBetsWidget Time-Sensitive Rendering', () => {
  beforeEach(() => {
    // 1. Enable fake timers
    vi.useFakeTimers();
    // 2. Set the system clock to a deterministic date/time
    vi.setSystemTime(new Date('2026-06-28T12:00:00Z'));
  });

  afterEach(() => {
    // 3. Restore the real-world clock
    vi.useRealTimers();
  });

  it('renders "Picks open soon" before the lock deadline has passed', () => {
    const mockTournament = {
      picksLockAt: '2026-06-29T18:00:00Z', // 1 day in the mocked future
      status: 'pending',
    };
    render(<SideBetsWidget tournament={mockTournament} />);
    expect(screen.getByText(/Picks open soon/i)).toBeInTheDocument();
  });
});

---

## 4. Negative Assertion Guard Validation Pitfall

### The Symptom
A test that asserts that a negative guard is functional (e.g., verifying that clicking a disabled or locked row *does not* expand its details, or a guest user *does not* see admin components) passes successfully, but a future refactor breaks the guard in production and the test *still* passes.

### The Cause
The negative assertion is too generic and is satisfied by the default absence of the queried element, even if the element was never rendered under any circumstances. For example, asserting that clicking a disabled row does not show "Golfer Breakdown" by calling:
```typescript
expect(screen.queryByText(/Golfer Breakdown/i)).not.toBeInTheDocument();
```
will pass even if the row expansion was successful, if the expanded content did not contain the text "Golfer Breakdown" or if "Golfer Breakdown" is absent on the page entirely.

### The Solution
Always assert the absence of content that is **uniquely specific** to that interactive target, and where possible, perform a control assertion that verifies the content *does* appear when the action is valid.
1. **Control Assert (Positive check):** Verify that clicking an *enabled* row successfully renders the specific detail content. This proves the querying mechanism and content exist in the DOM.
2. **Target Assert (Negative check):** Verify the absence of the specific row-level details (e.g. searching for the specific golfer's name seeded *only* in that row) rather than a global page text label.

```typescript
// Avoid asserting on a generic label that might be absent anyway
// queryByText(/Golfer Breakdown/) could be absent due to a rendering bug elsewhere

// 1. Positive Control Check
render(<LeaderboardRow golfer="Tiger Woods" disabled={false} />);
await userEvent.click(screen.getByRole('button'));
expect(screen.getByText(/Tiger Woods/i)).toBeInTheDocument();

// 2. Precise Negative Check
cleanup();
render(<LeaderboardRow golfer="Tiger Woods" disabled={true} />);
await userEvent.click(screen.getByRole('button'));
expect(screen.queryByText(/Tiger Woods/i)).not.toBeInTheDocument(); // Tiger Woods is specific to this row's details
```

```

```
