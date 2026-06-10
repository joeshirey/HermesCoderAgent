# College Football Pool (CollegeFBPool) Research & Backlog Context

This reference card details the repository structure, database configurations, and specific architectural workarounds engineered for the **CollegeFBPool** application. Use this context during future sessions to accelerate onboarding, prevent regression, and coordinate scoring/auth additions.

---

## 🐘 1. Database Schema & Alembic Revisions

* **Target Database:** PostgreSQL 16 running natively in Docker (mapped to local port `5432` with database `cfb_pool` and user `postgres`).
* **Column Mismatch (`teams.is_fcs`):**
  * *Bug:* The SQLAlchemy model `backend/app/models/team.py` declared an `is_fcs` boolean column, but it was missing from all Alembic migrations (revisions `001` through `005`), causing runtime desyncs when reading/writing teams.
  * *Resolution:* Generated a new migration `backend/alembic/versions/139bc7b26979_add_is_fcs_to_teams.py` (revises `005` to `head`). It implements a clean backfill strategy: adds `sa.Column('is_fcs', sa.Boolean(), server_default=sa.false(), nullable=False)` to backfill existing records, then strips the server default (`alter_column`) to match the Python-side model default perfectly.

---

## 🧠 2. LLM Client & Native Gemini SDK Integration

* **Package Dependencies:** Upgraded backend dependencies in `backend/pyproject.toml` to declare and install **`google-genai`** and **`anthropic`** natively via `uv`.
* **The SDK Shift:** Swapped out the old OpenAI-compatible redirection client for Google's native, high-performance **`google-genai` SDK**:

    ```python
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=self.api_key)
    response = await client.aio.models.generate_content(
        model=self.model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        ),
    )
    content = response.text or ""
    ```

* **Model Default:** Default configurations in `backend/app/config.py` and `backend/.env.sample` are standardized to `LLM_PROVIDER=gemini` and `LLM_MODEL=gemini-3.5-flash`.

---

## 📊 3. Unified Bonus Outcome Builder (The Scorers Fix)

* **Bug #12 Resolved:** The outcomes dictionary (`game_outcomes`) was built generically in `scoring.py` / `api/bonus.py`, failing to provide the specific keys required by 5 of your registered field scorers:
  * `yes_no` reads `outcome["answer"]` (bool).
  * `multi_select` reads `outcome["winners"]` (plural list).
  * `percentage_assign` reads `outcome["base_points"]` + `outcome["correct"]` (user-specific list).
  * `point_allocation` reads nested `outcome["games"][game_id]["winner"/"points"]`.
  * `home_away` reads `outcome[game_id]` (H/V selections).
* **Resolution:** Extracted all outcome generation into a unified, extremely robust helper: **`backend/app/services/bonus_outcome_builder.py::build_bonus_game_outcomes`**.
  * *Features:* Uses regex to parse spreads from yes_no labels, distinguishes between Straight-Up and Against-The-Spread (ATS) multi-select selections, and maps variables by UUID and matchup strings dynamically.
  * *User-Specific Mapping:* To handle the user-specific `percentage_assign` fields, `build_bonus_game_outcomes` accepts an optional `user_pick` argument. At scoring runtime (`scoring.py`), the scorer builds user-specific outcomes dynamically by mapping the user's specific regular loser picks (`loser_1`, `loser_2`, `loser_3`) to their calculated point values and statuses.

---

## 👥 4. User Directory & Mock Login Bypass

* **Player Seeding:** Populated the `users` database table from the `CFB 2025.xlsx` spreadsheet (`Standings` sheet) using a clean parsing script (`backend/scripts/seed_users.py`). Loaded all **20 players** as active users with mock emails and Google IDs.
* **Commissioner Roles:** Automatically assigned **the repository owner** and **Eric Huggins** as `commissioner` users.
* **Local Bypass:** Since setting up Google OAuth credentials locally is tedious, use the local `/mock-login` endpoint. To test, navigate to `http://localhost:3000`, click **Mock Login**, and type `commissioner@example.com` to bypass Google authentication and sign in as commissioner immediately!

---

## 🔒 5. Database, Query, & Form Validation Hardening (Option 1 Passes)

* **Scoring Bonus Chronological Ordering:**
  * *Bug:* Selecting the latest bonus definition ordered by random UUIDs (`BonusDefinition.id.desc()`), randomly serving or scoring players against outdated/wrong definitions.
  * *Fix:* Standardized all active queries to order chronologically using `BonusDefinition.created_at.desc()`.

* **Current-Week Active Season Filtering:**
  * *Bug:* Open/locked week checks ignored active seasons, causing old-season locked weeks to shadow and block new seasons.
  * *Fix:* Centralized `get_active_season` inside current-week fetches (`picks.py`, `bonus.py`), appending `Week.season_id == active_season.id` to ensure correct week queries.

* **Database-Level Pick Validation:**
  * *Bug:* Duplicate loser submissions (double-dipping point values) triggered unhandled DB CheckConstraint `500` crashes instead of clear validation responses.
  * *Fix:* Added `validate_distinct_losers` checking duplicate team IDs inside `PickValidator` and raised `400 Bad Request` validation errors.

* **Frontend Submission & Form State Safety:**
  * *Bug:* If a player's base picks succeeded but their bonus picks failed, the frontend clobbered their unsaved bonus answers by flipping `hasEdited = false` and fetching old db data.
  * *Fix:* Removed `setHasEdited(false)` from individual success mutations. Refactored `handleSubmit` to check `bonusIsValid`, execute both base and bonus mutations sequentially, and reset edit state strictly at the end of successful multi-step completion.

* **Substring Shadowing Resilience Heuristics:**
  * *Bug:* Suffix-based team matching (e.g. matching "Iowa" vs "Iowa State" inside matchup strings) erroneously mapped games based on substring overlaps.
  * *Fix:* Replaced fragile substring matching in `_resolve_game_for_option` with regex word boundaries combined with character-length scoring prioritization:
    ```python
    pattern = rf"\b{re.escape(name.lower())}\b"
    if re.search(pattern, label_l):
        score += len(name)
    ```
    This guarantees that longer, more specific team names ("Iowa State") are chosen over overlapping sub-names ("Iowa"), resolving all shadowing desyncs.

---

## 📈 6. Large Backlog Incremental Triage Loops

* **Sequential Triage Timeout:**
  * *Bug:* Triaging large backlogs (20+ issues) inside a single terminal run easily timed out due to sequential LLM-research latency (~120s per issue).
  * *Fix:* Created a unbuffered sequential support loop `triage_loop.py` running `triage --limit 1 --confirm --json` inside independent python steps, saving triage state incrementally with zero transaction loss. Run in the background (`background=True`) and leverage automated Hermes completeness notifications.

---

## 📡 7. Live Operations, SMS Idempotency, and ESPN Sync Resilience (Option 2 Passes)

* **Missing-Picks SMS Idempotency Gate:**
  * *Bug:* Missing-picks reminders lacked an idempotency gate, causing users to get duplicate SMS alerts (~96 texts within the 24h window) on repeated cron Scheduler runs.
  * *Fix:* Wrapped the missing-picks sender inside an `_already_sent(db, "missing_picks", week.id)` database check inside `trigger_deadline` (`notifications.py`), securely writing a `skipped` record when disabled in preferences to prevent redundant checks.

* **ESPN Postponed & Cancelled Game Scoring:**
  * *Bug:* Postponed or cancelled games mapped back to `"scheduled"` during ESPN scoreboard status syncs, triggering 400 Bad Request finality blockages that permanently locked week scoring.
  * *Fix:* Expanded status mapping in `scoring.py` to map `"STATUS_POSTPONED"` $\rightarrow$ `"postponed"` and `"STATUS_CANCELED"` $\rightarrow$ `"cancelled"`, and excluded both from the `non_final` finality checks so scoring can proceed.

* **Notification Service N+1 and Falsy-Zero Bugs:**
  * *Bug:* `notify_scores_posted` ran N+1 database fetches inside a user loop and was susceptible to falsy-zero bugs (score of `0` reported as `"N/A"` instead of `"0.0"`).
  * *Fix:*
    * Optimized `notify_scores_posted` to query all WeeklyPicks for the week in a single query outside the user loop, turning $O(N)$ DB queries into a fast $O(1)$ dictionary lookup.
    * Modified formatting check to use `pick.base_score is not None` (fixing falsy-zero reporting).
    * Wired week-open notifications directly to the transition to `"open"` in `weeks.py`.
    * Wired scores-posted notifications directly to the transition to `"scored"` in `scoring.py`.

---

## 🚀 8. Production Readiness & Database Resilience (Option 3 Passes)

* **SQLAlchemy Async Connection Pooling:**
  * *Issue:* SQLAlchemy engines are susceptible to idle timeouts and connection dropouts, causing 500 error crashes on the next request.
  * *Fix:* Added `pool_pre_ping=True` and `pool_recycle=1800` inside `backend/app/db.py` to force engine keepalives and automatic reconnection on fallout.

* **LLM Client JSON Decode Retry Resilience:**
  * *Issue:* The LLM client raised exceptions immediately on transient malformed JSON generations, as `ValueError` subclasses (like `JSONDecodeError`) bypassed the backoff retry loops.
  * *Fix:* Refactored `_gemini_native_generate` and `_anthropic_generate` to raise standard `json.JSONDecodeError` on malformed output, and patched `_retry_with_backoff` in `llm_client.py` to allow retry execution on `JSONDecodeError` while keeping other strict prompt validation exceptions gated solely by exception type:
    ```python
    if isinstance(e, ValueError) and not isinstance(e, json.JSONDecodeError):
        raise
    ```
  * *Outage Gating:* Refactored `generate_bonus` inside `bonus.py` to explicitly catch `json.JSONDecodeError` first, and raise a `502 Bad Gateway` (with B904-compliant `from e` formatting), ensuring malformed LLM outputs never leak as client-side errors.

* **Genuine Postgres-Backed CI Job & Dual-Mode Test Isolation:**
  * *Issue:* CI pytest suite ran on in-memory SQLite and never tested migrations, while running `create_all`/`drop_all` on every test run on Postgres was too slow.
  * *Fix:*
    * Configured a live Postgres 15 service container inside GHA (`.github/workflows/ci.yml`) and ran `uv run alembic upgrade head` against it on the remote runner before test executions.
    * Refactored `conftest.py` to dynamically honor `TEST_DATABASE_URL`.
    * Designed a dual-mode `setup_db` fixture: if running on Postgres, it performs a **lightning-fast `TRUNCATE CASCADE`** over all 12 schema tables between test runs (`RESTART IDENTITY CASCADE`), maintaining SQLite-level test speed (~28s) with real Postgres isolation!

* **Database-Safe Idempotency Index (Issue #76):**
  * *Issue:* Two concurrent trigger requests could bypass the in-memory/in-API `_already_sent` check and double-send SMS notifications.
  * *Fix:* Created a partial unique index `uq_notifications_sent_type_week` on `(notification_type, week_id)` on `NotificationSent` when `week_id` is not null:
    ```python
    __table_args__ = (
        sa.Index(
            "uq_notifications_sent_type_week",
            "notification_type",
            "week_id",
            unique=True,
            postgresql_where=sa.text("week_id IS NOT NULL"),
            sqlite_where=sa.text("week_id IS NOT NULL"),
        ),
    )
    ```
    Generated and executed Alembic migration `fd89aee2b77e` to apply the backstop.

* **Commit Before Raise Validation (Issue #78):**
  * *Issue:* Syncing ESPN scoreboard results was discarded if a game status check triggered the 400 Bad Request finality block, rolling back all successfully synced outcomes.
  * *Fix:* Executed `await db.commit()` inside `scoring.py` immediately after the sync loop, securing the results before evaluating the finality validation exceptions.

* **Automated Startup Shell Scripts:**
  * *Issue:* Starting the application container without database migration synchronization caused desync crashes on deploy.
  * *Fix:* Authored a startup script `start.sh` executing `python3 -m alembic upgrade head` before booting `uvicorn` inside Docker, copy-granting execute permissions in `Dockerfile` to guarantee automated migration alignment on deploy.

* **Production Backup & Recovery Shell Scripts (Issue #84):**
  * *Issue:* Private repositories require database maintenance structures.
  * *Fix:* Authored `backup.sh` and `restore.sh` utilizing `pg_dump`/`pg_restore` for database SQL maintenance inside `backend/scripts/`.
