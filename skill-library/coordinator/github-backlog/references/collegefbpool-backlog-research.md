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
* **Commissioner Roles:** Automatically assigned **the repository owner** (and `Joseph Shirey`) and **Eric Huggins** as `commissioner` users.
* **Local Bypass:** Since setting up Google OAuth credentials locally is tedious, use the local `/mock-login` endpoint. To test, navigate to `http://localhost:3000`, click **Mock Login**, and type `joe.shirey@example.com` to bypass Google authentication and sign in as commissioner immediately!
