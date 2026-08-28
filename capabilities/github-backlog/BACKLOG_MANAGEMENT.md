# RFC: GitHub-Integrated Backlog Management Architecture

This document specifies the architecture and workflow for automating backlog management on a repo-by-repo basis using **GitHub Issues** as the canonical backlog store.

---

## 1. Vision & Core Principles

Rather than tracking tasks locally in static text files or separate task databases, the **Coding Coordinator** uses **GitHub Issues** directly as its project backlog. This ensures:

- **Single Source of Truth:** Humans and agents interact with the exact same backlog in real-time.
- **Native Sort & Filter:** Leverage GitHub's built-in issue querying, labeling, and board views (Projects) without inventing custom database engines.
- **Rich AI-Ready Context:** Every backlog item is documented with sufficient background research, architectural context, and testing criteria so that a subsequent agent or human can pick it up and execute with zero extra research.

---

## 2. Metadata Schema (The Labeling System)

To enable robust sorting, filtering, and prioritization in GitHub, we map backlog attributes to standardized, namespaces **GitHub Labels**:

| Category | Label Key | Allowed Values | Description |
|----------|-----------|----------------|-------------|
| **Type** | `type:<val>` | `feature`, `bug`, `refactor`, `chore`, `spike` | Category of work. |
| **Severity** | `severity:<val>` | `critical`, `high`, `medium`, `low`, `nit` | Urgency of resolution. |
| **Effort (LOE)** | `effort:<val>` | `S`, `M`, `L`, `XL` | T-Shirt sizes estimating complexity. |
| **Risk** | `risk:<val>` | `high`, `medium`, `low` | Probability of creating regressions or side effects. |
| **Impact** | `impact:<val>` | `user-visible`, `internal-debt`, `dev-experience` | Who benefits directly from this work. |
| **Confidence** | `confidence:<val>` | `high`, `medium`, `low` | Certainty level of the suggested files & approach. |
| **Status** | `backlog:<val>` | `needs-triage`, `draft-suggestion`, `groomed`, `blocked`, `ready` | Backlog state-machine tracking. |

*Note: The Coordinator will automatically initialize these labels in the repository if they do not exist upon opting in.*

---

## 3. Opt-In Mechanism (Repo-by-Repo Activation)

To ensure this only triggers on desired repositories, we implement an explicit **Opt-In Check**:

1. **Local Activation File:**
   - The coordinator looks for a `.hermes-backlog.yaml` file in the root of the active git repository.
   - If this file does not exist, GitHub backlog automation is entirely bypassed.
2. **Configuration Schema (`.hermes-backlog.yaml`):**

   ```yaml
   enabled: true
   project_name: "Apple Container Integration"
   triage_on_create: true         # Run automatic triage when new issues are added
   require_user_approval: true    # Confirm metadata changes with user via chat
   custom_labels:                 # Optional overrides
     type_prefix: "type:"
     severity_prefix: "severity:"
   ```

---

## 4. Context-Rich Issue Template

To minimize execution-time research, any issue created or groomed by the Coordinator must adhere to the following **Markdown Template**:

```markdown
# [Title]

## 🎯 Objective & Business Value
[Clear, high-level summary of what we are building and WHY it matters. Highlights whether this benefits users directly or is developer-facing technical debt.]

## 📋 Requirements & Acceptance Criteria
- [ ] Requirement 1
- [ ] Requirement 2
- [ ] Requirement 3 (with testing validation instructions)

## ✅ Definition of Done (DoD)
- [ ] Code meets architectural standards (preserves patterns in `<file>`).
- [ ] Unit tests written and passing (targeting >80% coverage on new lines).
- [ ] No new compiler or linter warnings introduced.
- [ ] Verification steps executed successfully (see rollback/verification commands below).

## 🛡️ Security & Safety Impact
- **Touches Authentication/Authorization?** [Yes/No]
- **Reads/Writes Sensitive User Data?** [Yes/No]
- **Opens Network/External Sockets?** [Yes/No]
- *Note for Auditor: If any are Yes, requires mandatory Tier 3 execution sandboxing.*

## 🔬 Technical Context & Research
- **Impacted Files:** `src/foo/bar.py`, `tests/test_foo.py`
- **Existing Patterns:** Refer to the implementation in `src/utils/pattern.py` for standard error handling.
- **APIs/Libraries Needed:** Uses the `shutil` package for file copying.

## ⚠️ Implementation Guidelines & Pitfalls
- **Suggested Approach:** Deconstruct into 3 steps...
- **Risks & Regressions:** Modifying `bar.py` could affect upstream login validation. Keep changes isolated.
- **Known Gotchas:** Do not import `X` inside `Y` to avoid circular import errors.

---
### 📊 Metadata Details
* **Type:** `type:feature`
* **Severity:** `severity:high`
* **Effort:** `effort:M`
* **Risk:** `risk:low`
* **Impact:** `impact:user-visible`
* **Confidence:** `confidence:high`

<!-- relations-metadata
{
  "depends_on": [102],
  "blocks": [104],
  "related": [105]
}
-->
```

*Why the comment blocks exist:* The trailing `<!-- relations-metadata ... -->` is an invisible JSON block in the markdown. It allows the Coordinator to programmatically parse and update issue relationships without cluttering the human-readable description!

---

## 5. Relational Tracking & Closed-Loop Cascades

To manage issue dependencies natively, we track relationship links through the invisible JSON block in the description and standard GitHub comment linkages.

When an issue is **Closed** (either via PR merger or manual closing):

```
                       ┌─────────────────────────┐
                       │     Issue #102 Closed   │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │ Read Relations Metadata │
                       │    (Blocks: [#104])     │
                       └────────────┬────────────┘
                                    │
                                    ▼
                       ┌─────────────────────────┐
                       │  Inspect Issue #104     │
                       │ (Check other deps)      │
                       └────────────┬────────────┘
                                    │
               Has other open deps  ├───────────────────────────────┐
                                    │ All dependencies closed       │
                                    ▼                               ▼
                       ┌─────────────────────────┐     ┌─────────────────────────┐
                       │   Keep Blocked Label    │     │ 1. Remove 'blocked'     │
                       │   (Log remaining deps)  │     │ 2. Add 'ready' label    │
                       └─────────────────────────┘     │ 3. Comment auto-unlock  │
                                                       └─────────────────────────┘
```

1. **Trigger:** A background cron check (or webhook integration) is fired whenever an issue transitions to `closed`.
2. **Dependency Check:** It looks up all issues where the closed issue was listed under `depends_on` (e.g., `#104`).
3. **Evaluation:** It checks if `#104` has any *other* open dependencies remaining.
4. **Action (Auto-Unlock):**
   - If **all** dependencies are resolved, the Coordinator automatically:
     1. Removes the `status:blocked` label.
     2. Applies the `status:ready` label.
     3. Posts an automated comment:
        > 🔓 **Dependency Resolved:** Dependency `#102` is now closed. `#104` is now unblocked and fully ready for implementation!

---

## 6. Agent-Initiated Backlog Suggestions & Bloat Control

During coding, refactoring, or review sessions, the active AI coding engine often uncovers edge cases, technical debt, deprecations, or follow-up ideas. Allowing the agent to automatically file these items maximizes project quality, but presents a massive risk of **issue bloat** that can quickly make the backlog unmanageable.

To capture this hidden intelligence without polluting the active backlog, we implement the following **Auto-Suggestion & Bloat Control Protocol**:

### A. The "Session Harvesting" Pass

At the end of every task execution or PR review, the Coordinator's `Reviewer` and `Quality` role skills trigger a background sweep over:

- **Code Comments:** Extracting any `TODO:`, `FIXME:`, or non-blocking reviewer suggestions that were out-of-scope for the active branch.
- **Terminal Logs:** Capturing unresolved warnings, deprecated function calls, or unoptimized SQL queries thrown during tests.
- **The Active Session History:** Identifying logic gaps or future-work recommendations noted during the conversation.

### B. The "Suggestion Inbox" Buffer (Preventing Noise)

Instead of auto-creating full backlog issues immediately on GitHub, the harvested suggestions pass through a **Triage Buffer**:

1. **Interactive Session Checkout (Human-in-the-Loop):**
   - When the session concludes, the Coordinator presents a structured "Harvest Summary" directly in chat:

     ```text
     💡 Uncovered Enhancements & Tech Debt:
     I found 2 items during this session that we should track. Would you like to file them?
     
     [ ] 1. Optimize DB query index in 'user_model.py' (Effort: S, Severity: Low, Risk: Low)
     [ ] 2. Expand E2E test coverage for concurrent socket sessions (Effort: L, Severity: Medium, Risk: Medium)
     
     [File Selected as Issues]   [Dismiss All]
     ```

   - *Action:* The user selects only the items they genuinely want to track. The rest are discarded, keeping the backlog clean.

2. **Asynchronous Draft Creation (Optional):**
   - If running in fully autonomous cron mode (where no human is present to approve), the Coordinator creates the issue on GitHub but labels it strictly with **`backlog:draft-suggestion`**.
   - Draft suggestions are excluded from default backlog views/Projects and are hidden from active "to-do" lists.

3. **The "Auto-Decay" Expiration Gate (Pruning):**
   - To prevent `backlog:draft-suggestion` issues from piling up indefinitely, a "Cold Storage" rule is enforced.
   - If a draft suggestion remains unreviewed or ungroomed by a human for **30 days**, the Curator cron job automatically:
     1. Posts a polite closing note: *"Closing this automated suggestion as it has been unreviewed for 30 days. Re-open if this becomes active."*
     2. Closes the issue as "not planned" and removes it from backlog counters.
     *Result:* The backlog is self-cleaning, preventing long-term clutter.

---

---

## 7. Automated Nightly Triage Engine

To manage human-entered backlog items—which are often created quickly and lack labels, file pointers, or precise scope—we implement a **Scheduled Nightly Triage Job**.

Every night (e.g., at 2:00 AM), the Coordinator executes an automated sweep to transform raw, basic human inputs into highly structured, execution-ready backlog assets.

```
                         ┌────────────────────────┐
                         │   Nightly Triage Job   │
                         │      (2:00 AM Cron)    │
                         └───────────┬────────────┘
                                     │
                                     ▼
                         ┌────────────────────────┐
                         │ Fetch Untriaged Issues │
                         │ (No labels or status)  │
                         └───────────┬────────────┘
                                     │
                                     ▼
                         ┌────────────────────────┐
                         │ Codebase Deep Research │
                         │ (Locate files/patterns)│
                         └───────────┬────────────┘
                                     │
                                     ▼
                         ┌────────────────────────┐
                         │ Compile Suggested Tags │
                         │  (Severity, LOE, etc)  │
                         └───────────┬────────────┘
                                     │
                   Approval Mode     ├──────────────────────────────┐
                   is Enabled        │                              │ Direct Commit
                                     ▼                              ▼
                         ┌────────────────────────┐     ┌────────────────────────┐
                         │ Send Telegram Digest   │     │  Commit Tags & Body    │
                         │   (Interactive Review) │     │    Directly to GitHub  │
                         └────────────────────────┘     └────────────────────────┘
```

### A. The Triage Processing Steps

For each newly discovered, untriaged issue, the Coordinator runs the following loop:

1. **Codebase Discovery Pass:**
   - Evaluates keywords in the raw title and body.
   - Searches the active codebase to identify candidate files, matching code structures, or relevant dependency schemas.
2. **Metadata Classification:**
   - Derives appropriate values for Type, Severity, Effort (T-shirt size), Risk, Impact, and Confidence using a lightweight reasoning model.
3. **Template Enrichment:**
   - Re-writes the issue description, formatting it perfectly according to our **Context-Rich Issue Template**.
   - Auto-populates the *Definition of Done (DoD)* and the *Security & Safety Impact* checkboxes.
4. **Dependency Linkage Analysis:**
   - Analyzes whether the issue references or blocks any other open issues, and compiles the invisible JSON `<!-- relations-metadata -->` block.

---

### B. Approval Modes: Staged vs. Direct

To accommodate different developer workflows, the Nightly Triage Engine supports two distinct routing pathways:

#### 1. Interactive Staged Mode (High Control - Recommended)

When `require_user_approval: true` is set in `.hermes-backlog.yaml`:

- **Staging Comment:** The Coordinator posts a hidden or clearly marked "Triage Suggestion Comment" on the GitHub issue containing the proposed tags and formatted body.
- **Telegram Digest:** It sends a clean, interactive digest directly to your Telegram Home channel:

  ```text
  📋 Nightly Backlog Triage Digest (2 Open Items):
  
  * Issue #132: "Add validation to container start"
    - Suggested: type:bug | severity:high | effort:S | risk:low
    - Enrichment: Identified 'src/containers.py'. Added Security checklist.
    [Approve Triage]  [Edit Triage]
    
  * Issue #133: "Upgrade virtualization dependencies"
    - Suggested: type:chore | severity:medium | effort:M | risk:high
    - Enrichment: Identified 'pyproject.toml'. Linked related Issue #98.
    [Approve Triage]  [Edit Triage]
  ```

- **Atomicity:** Once you click **Approve Triage**, the Coordinator instantly applies the labels, replaces the issue body on GitHub, deletes the staging comment, and transitions the status to `backlog:groomed`.

#### 2. Direct Commit Mode (Autonomous - Low Friction)

When `require_user_approval: false` is set in `.hermes-backlog.yaml`:

- The Coordinator directly applies the labels and updates the issue body on GitHub.
- It posts an explanatory comment: *"This issue has been automatically groomed and research-enriched by the Backlog Triage Engine. Status set to `backlog:groomed`."*

---

## 8. Backlog Grooming & Management Engine

While triage deals with newly added items, **Backlog Grooming** focuses on maintaining the long-term health, organization, and feasibility of the backlog as the codebase and project goals evolve.

The Coordinator executes a **Weekly Backlog Grooming Sweep** (e.g., every Monday at 9:00 AM) to perform advanced maintenance tasks across four key vectors:

```
                         ┌────────────────────────┐
                         │ Weekly Grooming Sweep  │
                         │      (Monday 9:00 AM)  │
                         └───────────┬────────────┘
                                     │
                                     ▼
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│ 1. Dependency   │         │ 2. Semantic     │         │ 3. Automated    │
│  Bottlenecks    │         │  Deduplication  │         │  Decomposition  │
└─────────────────┘         └─────────────────┘         └─────────────────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │ 4. Stale/Decay Audit   │
                        │    (Warm-Stale Warn)   │
                        └────────────┬───────────┘
                                     │
                                     ▼
                        ┌────────────────────────┐
                        │ Send Grooming Digest   │
                        │   (Telegram Checkout)  │
                        └────────────────────────┘
```

### A. Core Grooming Vectors

#### 1. Dependency Bottleneck Detection

- **Mechanism:** The Coordinator parses the invisible `<!-- relations-metadata -->` block of all open issues to reconstruct the project's **Dependency Directed Acyclic Graph (DAG)**.
- **Action:**
  - Identifies "critical-path bottlenecks" (e.g., a single issue like `#12` that is blocking 5 other issues).
  - Automatically elevates the bottleneck's priority (e.g., adding `severity:critical` or `severity:high`) and flags it as a priority recommendation.
  - Detects and flags any circular dependencies (e.g., `#10` depends on `#11`, which depends on `#10`) so they can be manually untangled.

#### 2. Semantic Deduplication (Duplicate Detection)

- **Mechanism:** The Coordinator executes a semantic similarity pass over the titles and objectives of all open issues.
- **Action:**
  - If any two issues match with >85% semantic similarity, the Coordinator flags them as duplicates.
  - Suggests **merging** them: it drafts a combined issue body consolidating research from both, and proposes closing the newer issue as a duplicate of the older one.

#### 3. Automated Decomposition of High-Effort Tasks

- **Mechanism:** Evaluates any issue labeled `effort:XL` or `effort:L` to determine if it is too massive for a single implementation run.
- **Action:**
  - Runs a decomposition algorithm to break the `XL` task down into 2 to 4 independent, bite-sized `S` or `M` sub-issues.
  - Drafts the new sub-issues, wires their dependency linkages so they block/depend on each other correctly, and suggests closing or converting the parent `XL` issue into an epic/milestone tracker.

#### 4. Stale/Decay Audit (The Self-Cleaning Sweep)

- **Mechanism:** Scans open issues with no user-activity, commits, or comments for over **60 days**.
- **Action:**
  - Applies a `backlog:stale` label.
  - Posts a "Warm-Stale Warning" comment on the issue: *"This issue has seen no activity for 60 days. It will be automatically closed in 14 days if no comments are made."*
  - If no activity occurs after 14 more days, the issue is closed as "not planned," keeping the backlog fresh and active.

---

### B. Interactive Grooming Digest (scrum master mode)

Rather than making sweeping changes on its own, the Coordinator presents a structured **Backlog Health & Grooming Digest** to you on Telegram:

```text
📋 Weekly Backlog Grooming Report (Apple Container Integration):

⚠️ Bottleneck Detected:
- Issue #12: "Fix container memory limit flags" blocks 4 other issues.
  [Elevate to severity:high & move to top]

👥 Possible Duplicates:
- Issue #145 ("Add login validations") is 92% similar to Issue #102 ("Verify credentials on login").
  [Merge #145 into #102 and close #145]

🪵 Large Task Decomposition:
- Issue #42 ("Implement complete macOS networking bridge") is effort:XL.
  - Proposal: Decompose into 3 independent sub-issues (Effort S/M).
  [Decompose Issue #42]

🍂 Stale Items:
- Issue #88 ("Investigate legacy plist parser") has been idle for 60 days.
  [Mark Stale & Warn]  [Close Issue]
```

Each recommendation contains a single-click interactive checkout button, giving you complete **Scrum Master authority** over your backlog in seconds!

---

## 9. Backlog Lifecycle Stages (The Build Phases)

When we implement this, we will structure it into three progressive phases:

### Phase 1: Automated Creation & Rich Documentation (Built — `github_backlog.py create`/`enrich`)

- Read a raw, basic issue idea or user request.
- Run a deep research pass (reading codebase files and existing APIs).
- Draft and create the fully documented, context-rich issue in GitHub with correct metadata labels.

### Phase 2: Active Issue Triage (Built — `github_backlog.py triage`)

- Monitor the repo for issues added by humans or external sources that lack label metadata or rich context (candidate = no `type:*` label OR `backlog:needs-triage`).
- Analyze the issue, perform codebase research, suggest correct classifications, and update the descriptions to match our standard template (executes the Scheduled Nightly Triage Job). Applies via the autonomy ladder (gated→digest, `--confirm`/push-draft/full→edit + `backlog:groomed` comment), bounded by `--limit`; cron documented, not auto-registered.

### Phase 3: Backlog Grooming & Management (Built — `github_backlog.py groom`)

- Weekly grooming sweep (`groom`): four analysis vectors over open issues → one digest → gated apply.
- DAG-based dependency tracking: rebuilds the dependency graph from the invisible `relations-metadata` blocks, flags bottlenecks (issues blocking ≥ `--bottleneck-min`, default 3 → `severity:high` elevation) and circular dependencies (flag-only).
- Semantic deduplication: `difflib` lexical similarity over title+objective ≥ `--dup-threshold` (0.85), with an optional local-gemma4 confirm pass (`--no-llm-dup` / Ollama-down → lexical-only, degraded exit 3).
- Automated task decomposition: drafts 2–4 sub-issues for `effort:L`/`effort:XL` issues **into the digest only** — propose-only, never auto-created.
- Stale pruning: `backlog:stale` + warm-stale warning at `--stale-days` (60) idle; close-eligible `--grace-days` (14) after.
- Applies via the autonomy ladder. **Close carve-out:** `groom` may close stale-past-grace and confirmed-duplicate issues — only behind the gate (`--confirm`/push-draft/full), never in default `gated`, suppressible via `--no-close`; closes use `gh issue close --reason "not planned"`, never delete/merge.
- Cron documented, not auto-registered (`approvals.cron_mode: deny`; user wires the weekly job).
