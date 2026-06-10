# Golf League Backlog Research & Domain Knowledge

This reference document contains the detailed codebase context, impacted files, and architectural patterns discovered during the comprehensive backlog triage of the `golfleague` repository. Use this context when planning or implementing the corresponding issue numbers.

---

## 1. Database & Migrations

### A. SQLite WAL Side-Files (`.gitignore` Alignment) — Issue #52 [RESOLVED]

- **Impacted Files:** Root `.gitignore`
- **Context:** At startup, the backend (`backend/app/database.py`) explicitly enables SQLite Write-Ahead Logging (WAL) mode via `PRAGMA journal_mode=WAL` for concurrent read efficiency. This automatically generates transient side-files: `*.db-shm` and `*.db-wal`.
- **Inconsistency:** The root `.gitignore` ignored `*.db` but omitted these side-files, leading to untracked file noise during local runs. Note that `backend/.dockerignore` already correctly ignores them.
- **Resolution (PR #68):** Added `*.db-shm` and `*.db-wal` rules to the root `.gitignore` file, successfully restoring clean status hygiene locally.

### B. Automated Alembic Migration & Model-Drift Test in CI — Issue #26 [RESOLVED]

- **Impacted Files:** `.github/workflows/ci.yml`, `backend/tests/test_migrations.py`
- **Context:** Without automated schema-drift validation, database model changes can diverge from Alembic migrations unnoticed.
- **Resolution (PR #66):**
  - Implemented an automated database migration and schema-drift test inside `test_migrations.py` using Alembic programmatic hooks.
  - Validates a clean, linear upgrade/downgrade/upgrade lifecycle across both SQLite and PostgreSQL dialects in CI.
  - Implemented an explicit index reflection anomaly guard (`ignored_indexes`) to filter out 9 SQLite-specific auto-generated performance indices, preventing false-positive test breaks.

### C. PostgreSQL Migration Constraint Downgrade Bug — Issue #37

- **Impacted Files:** Migration script `ec64c081d2e2` (or corresponding downgrade step).
- **Bug:** The downgrade path of this migration attempts to re-insert a hardcoded `'system'` string into a foreign-key (FK) column. While local SQLite may not aggressively enforce this if constraints are deferred, production PostgreSQL (on Cloud SQL) strictly enforces FK referential integrity and fails immediately, blocking schema rollbacks.

### C. Missing Database Indexes on FKs / Hot Lookups — Issue #36

- **Context:** The current schema defines relations across `picks`, `tournament_results`, `player_scores`, `golfer_values`, and `season_standings`, but defines almost zero standalone database indexes.
- **Pitfall:** Broad unique constraints like `uq_user_tournament_golfer` on `picks` only cover queries starting with the leading column (`user_id`). Individual queries filtering on `tournament_id` or performing `ON DELETE CASCADE` rollups trigger expensive table scans.
- **Action Needed:** Add migrations to introduce explicit indexes on all foreign key and hot lookup columns.

---

## 2. Scoring Logic & Dead Code Elimination

### A. Dead Component & Drifted Scoring Table — Issue #54 [RESOLVED]

- **Dead Component:** `frontend/src/components/admin/ResultsEditor.tsx` (~365 lines of UI). This file was completely unimported in the active React tree.
- **Drifted Scoring Pattern:** `ResultsEditor.tsx` contained its own hardcoded copy of the scoring table and a naive `getPoints(position)` lookup that was completely unaware of tie-scoring.
- **Authoritative Source of Truth:** `backend/app/services/scoring.py` is the official, tie-averaging scoring engine (e.g. four players tied for 3rd average the points of 3rd, 4th, 5th, and 6th positions, applying banker's rounding to 2 decimals).
- **Resolution (PR #71):** Safely pruned the dead component `ResultsEditor.tsx` and updated the active frontend views (`RosterBuilder`, `GolferList`, `ValueBar`) to use precise rounded integer arithmetic helpers to sum salary cap metrics, removing duplicate logic.

### B. Payout Pot Remainder Handling & Hardcoded Fee — Issue #51

- **Context:** Entry fees are currently hardcoded client-side. The payout split calculation drops remainder cents when dividing pots.
- **Remediation:** Centralize the tournament entry fee on the backend and implement an exact remainder allocation/carrying logic for payout divisions.

---

## 3. DevOps & CI/CD Pipelines

### A. Missing Container Smoke Tests — Issue #41 [RESOLVED]

- **Impacted Files:** `infra/cloudbuild.yaml`
- **Current Pattern:** The Cloud Build pipeline builds the frontend/backend Docker images, pushes them to Artifact Registry, and immediately deploys them.
- **Risk:** Build success does not guarantee runtime startup success. Bad dependencies, environment syntax errors, or startup crashes are only caught after the broken image is serving production traffic.
- **Resolution (PR #67, #69):**
  - Integrated full container-startup health pings inside the `infra/cloudbuild.yaml` build process within a shared Docker bridge network (`--network cloudbuild`).
  - To prevent database write permission crashes inside unprivileged container runtime environments (which run under `appuser` and cannot write to `/app/smoke_test.db`), we dynamically mapped the smoke test SQLite database path to the globally writable `/tmp/smoke_test.db` directory. This secures a flawless smoke-test build step without compromising security permissions.

### B. Pinning Docker Base Images — Issue #42

- **Impacted Files:** All `Dockerfile` configurations.
- **Pattern:** Base images are pinned by loose semantic tags rather than secure SHA digests, making builds non-deterministic over time. Update to use explicit SHA-256 digests.

---

## 4. Security, Concurrency & Fair Play (June 2026 Update)

During the June 2026 backlog grooming review, several critical, high-impact issues were identified and grouped into high-leverage implementation bundles:

### A. League Integrity & Fairness Exploits (Bundle 1)

- **Pre-lock Pick Leak — Issue #94:**
  - **Context:** The tournament leaderboard API endpoint is currently vulnerable to a competitive leak where players can view other players' active rosters and pick selections *before* the tournament picks lock. This allows a late-moving player to spy on everyone's strategy right before the deadline.
  - **Remediation:** Modify the API response serialization (likely inside the tournament/leaderboard service) to restrict player roster detail payloads, making them available only *after* the tournament's scheduled lock time.
- **Concurrent Pick Submission Roster Cap Race — Issue #101:**
  - **Context:** Users can potentially double-submit picks concurrently to bypass budget or roster salary limits. If multiple identical API requests hit the backend simultaneously, the validation logic may read stale roster values before both transactions write, allowing an invalid roster to bypass the value cap checks.
  - **Remediation:** Enforce database-level serializability, a check constraint, or use explicit transaction locks (e.g., PostgreSQL row locks or advisory locks) inside the pick submission route.

### B. Poller Concurrency & Database Connection Reliability (Bundle 2)

- **ESPN Poller Concurrency advisory locks — Issue #100:**
  - **Context:** When running in serverless environments like Google Cloud Run, multiple active instances can spin up and execute the background ESPN polling loop concurrently. This results in duplicate API calls to ESPN and race conditions/write conflicts when writing leaderboard scores.
  - **Remediation:** Implement explicit PostgreSQL advisory locks inside the polling cron job wrapper to guarantee that only a single active container instance can hold the poller lease at a time.
- **Database Connection Pool Hardening — Issue #98:**
  - **Context:** Serverless backend instances experience intermittent connection timeouts (500 errors) when connecting to Google Cloud SQL because idle database connections are dropped by GCP's firewall or SQLAlchemy's internal pool becomes stale.
  - **Remediation:** Standardize pool configuration in SQLAlchemy: enable `pool_pre_ping=True`, set `pool_recycle=1800` (to recycle connections before the 15-minute firewall idle timeout), and size pools appropriately for serverless concurrency.
- **ESPN Poller: Decimal vs Float Comparison — Issue #99:**
  - **Context:** The ESPN poller fails to back off scoring checks because numerical comparisons between decimals (from the database) and floats (from the ESPN JSON API) prevent clean equivalence checks, forcing unnecessary poller database updates.
  - **Remediation:** Cast values to a consistent type (such as standardizing on float or parsing API results directly into SQLAlchemy `Numeric(asdecimal=True)`-compatible decimals) during changed-state checks.

### C. Authentication and Session Hardening (Bundle 3)

- **Dev Admin Auth Bypass Vulnerability — Issue #96:**
  - **Context:** The app's developmental admin login bypass mechanism relies on environment configurations. A single misconfigured or leaked environment variable could accidentally expose the bypass backdoor in a production deployment.
  - **Remediation:** Restructure the authentication services so that the bypass path is hard-disabled at compile/runtime if the execution environment is anything other than `local`/`development`.
- **Logout Cache Leak — Issue #97:**
  - **Context:** In shared device setups (e.g. users logging into the golf pool at a clubhouse), logging out of the application fails to invalidate the frontend React Query cache, meaning a subsequent user can view stale cache-leaked rosters or profiles of the prior user.
  - **Remediation:** Explicitly call `queryClient.clear()` on logout within the authentication/session hook layer to purge all user-scoped data.
