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
