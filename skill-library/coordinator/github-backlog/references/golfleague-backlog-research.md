# Golf League Backlog Research & Domain Knowledge

This reference document contains the detailed codebase context, impacted files, and architectural patterns discovered during the comprehensive backlog triage of the `golfleague` repository. Use this context when planning or implementing the corresponding issue numbers.

---

## 1. Database & Migrations

### A. SQLite WAL Side-Files (`.gitignore` Alignment) — Issue #52

- **Impacted Files:** Root `.gitignore`
- **Context:** At startup, the backend (`backend/app/database.py`) explicitly enables SQLite Write-Ahead Logging (WAL) mode via `PRAGMA journal_mode=WAL` for concurrent read efficiency. This automatically generates transient side-files: `*.db-shm` and `*.db-wal`.
- **Inconsistency:** The root `.gitignore` ignored `*.db` but omitted these side-files, leading to untracked file noise during local runs. Note that `backend/.dockerignore` already correctly ignores them.
- **Fix:** Update root `.gitignore` to match the Docker exclusions.

### B. PostgreSQL Migration Constraint Downgrade Bug — Issue #37

- **Impacted Files:** Migration script `ec64c081d2e2` (or corresponding downgrade step).
- **Bug:** The downgrade path of this migration attempts to re-insert a hardcoded `'system'` string into a foreign-key (FK) column. While local SQLite may not aggressively enforce this if constraints are deferred, production PostgreSQL (on Cloud SQL) strictly enforces FK referential integrity and fails immediately, blocking schema rollbacks.

### C. Missing Database Indexes on FKs / Hot Lookups — Issue #36

- **Context:** The current schema defines relations across `picks`, `tournament_results`, `player_scores`, `golfer_values`, and `season_standings`, but defines almost zero standalone database indexes.
- **Pitfall:** Broad unique constraints like `uq_user_tournament_golfer` on `picks` only cover queries starting with the leading column (`user_id`). Individual queries filtering on `tournament_id` or performing `ON DELETE CASCADE` rollups trigger expensive table scans.
- **Action Needed:** Add migrations to introduce explicit indexes on all foreign key and hot lookup columns.

---

## 2. Scoring Logic & Dead Code Elimination

### A. Dead Component & Drifted Scoring Table — Issue #54

- **Dead Component:** `frontend/src/components/admin/ResultsEditor.tsx` (~365 lines of UI). This file is completely unimported in the active React tree.
- **Drifted Scoring Pattern:** `ResultsEditor.tsx` contains its own hardcoded copy of the scoring table and a naive `getPoints(position)` lookup that is completely unaware of tie-scoring.
- **Authoritative Source of Truth:** `backend/app/services/scoring.py` is the official, tie-averaging scoring engine (e.g. four players tied for 3rd average the points of 3rd, 4th, 5th, and 6th positions, applying banker's rounding to 2 decimals).
- **Remediation:** Safely prune `ResultsEditor.tsx` and ensure any administrative workflows rely entirely on the backend-computed scoring engine.

### B. Payout Pot Remainder Handling & Hardcoded Fee — Issue #51

- **Context:** Entry fees are currently hardcoded client-side. The payout split calculation drops remainder cents when dividing pots.
- **Remediation:** Centralize the tournament entry fee on the backend and implement an exact remainder allocation/carrying logic for payout divisions.

---

## 3. DevOps & CI/CD Pipelines

### A. Missing Container Smoke Tests — Issue #41

- **Impacted Files:** `infra/cloudbuild.yaml`
- **Current Pattern:** The Cloud Build pipeline builds the frontend/backend Docker images, pushes them to Artifact Registry, and immediately runs `gcloud run services replace` to deploy them to production.
- **Risk:** Build success does not guarantee runtime startup success. Bad dependencies, environment syntax errors, or startup crashes are only caught *after* the broken image is serving production traffic.
- **Fix:** Insert a lightweight container startup smoke test check (e.g., verifying a health/readiness HTTP endpoint) between the push and deploy stages.

### B. Pinning Docker Base Images — Issue #42

- **Impacted Files:** All `Dockerfile` configurations.
- **Pattern:** Base images are pinned by loose semantic tags rather than secure SHA digests, making builds non-deterministic over time. Update to use explicit SHA-256 digests.
