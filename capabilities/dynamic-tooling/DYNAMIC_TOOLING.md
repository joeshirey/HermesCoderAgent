# RFC: Dynamic Skill & Tool Injection Architecture (Hermes Coder)

This document outlines the architectural plan for dynamically injecting specialized skills, reference documentation, and MCP (Model Context Protocol) servers into coding engines (like `claude-code`, `antigravity`, or `opencode`) at dispatch time.

---

## 1. Core Vision

By dynamic injection, the **Coding Coordinator** transitions from a passive dispatcher to a **Context & Capability Curator**.

Instead of overwhelming the coding engine with every available tool and skill in the system (which causes token bloat, reasoning confusion, and over-engineering), the Coordinator dynamically analyzes the target task and **packages a custom, minimal toolbelt/context bundle** tailored strictly to that specific execution.

```
                    ┌────────────────────────┐
                    │  Implementation Task   │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   Complexity Triage    │
                    │   (T-Shirt Sizing)     │
                    └───────────┬────────────┘
                                │
                    ┌───────────┴───────────┐
         Simple (S) │                       │ Medium/Large (M/L)
                    ▼                       ▼
           ┌─────────────────┐    ┌──────────────────┐
           │ Raw Dispatch    │    │ Dynamic Curator  │
           │ (No extensions) │    │  (Select Tools)  │
           └─────────────────┘    └─────────┬────────┘
                                            │
                                            ▼
                                  ┌──────────────────┐
                                  │ Security/Trust   │
                                  │   Verification   │
                                  └─────────┬────────┘
                                            │
                                            ▼
                                  ┌──────────────────┐
                                  │ Dynamic Harness  │
                                  │    Injection     │
                                  └──────────────────┘
```

---

## 2. Architectural Pillars

### A. Discovery & Determination (Codebase-Aware Retrieval)

To discover which skills or MCP servers are relevant, we employ a two-layer strategy:

1. **Semantic Search over Metadata:**
   - Every skill (`SKILL.md`) and MCP definition contains YAML frontmatter with `tags`, `frameworks`, and `compatibility`.
   - The Coordinator queries the local skills database using semantic matching between the task description and skill metadata.
2. **Codebase-Aware Static Analysis:**
   - Before dispatching, the Coordinator parses the imports of the target files (e.g., checking `package.json` or reading file headers).
   - If `react-router-dom` is imported, the Router skill is prioritized. If `@tanstack/react-query` is found, the React Query skill is activated. This ensures we don't guess—we match the code.

### B. Tool Budgets (Preventing Context & Tool Bloat)

Giving an LLM 50 tools makes it stupid. Giving it the exact 3 tools it needs makes it incredibly sharp.

- **The Concept of a "Tool Budget":**
  - Limit the coding engine to a maximum of **1 custom skill** and **3 custom MCP tools** per dispatch.
  - For skills, instead of injecting the entire markdown document, we extract only the **Reference Implementation** and **Common Pitfalls** sections.
  - We configure the engine's `--allowedTools` flag (or equivalent) dynamically to disable native tools that are unnecessary for the task.

### C. Complexity Matching (T-Shirt Sizing)

We must avoid giving "skills" to simple tasks. For example, if we are changing an inline Tailwind class, a React architectural skill will only distract the model and lead to over-engineering.

- **T-Shirt Sizing Protocol:**
  - **S (Small):** Single-file modifications, CSS tweaks, straightforward bug fixes, regex updates.
    - *Action:* Zero dynamic injection. Raw engine dispatch.
  - **M (Medium):** Adding component logic, creating helper utilities, implementing simple endpoints.
    - *Action:* Selective reference injection (skills metadata only), no custom MCP servers.
  - **L (Large):** Creating brand new features, major refactors, multi-file integrations.
    - *Action:* Full Dynamic Curator pass (Skills + custom MCP servers).

### D. Best-Match Selection & De-duplication

If there are multiple matching skills (e.g., three different React state-management skills), the Coordinator applies a **De-duplication Matrix**:

- **Explicit Preference Rules:** Define priority lists in `config.yaml` (e.g., "If React state is needed, prefer `zustand` over `redux` unless `redux` is explicitly found in imports").
- **Cohesion Score:** Calculate the overlap between the task's technical requirements and the skill's capabilities. The highest cohesion score wins.

### E. Security & Trust Gateways (Zero-Risk Execution)

Loading random third-party skills or community MCP servers introduces massive security vulnerabilities (e.g., shell injection, remote code execution, token stealing). To guarantee absolute safety, the Coordinator implements a multi-layered security gateway:

```
                      ┌─────────────────────────┐
                      │    Discovered Tool/MCP  │
                      └────────────┬────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │ 1. Reputation Check     │
                      └────────────┬────────────┘
                                   │
               Tier 1 (Official)   ├───────────────────────────────┐
                                   │ Tier 2/3 (Low Rep/Unknown)    │
                                   ▼                               ▼
                      ┌─────────────────────────┐     ┌─────────────────────────┐
                      │ 3. Check Local Cache    │     │ 2. Automated Code Audit │
                      │      (SHA-256)          │     │    (Static + LLM Pass)  │
                      └────────────┬────────────┘     └────────────┬────────────┘
                                   │                               │
                      Match Found  │                               │ PASS
                      (Bypass)     ├───────────────────────────────┘
                                   ▼
                      ┌─────────────────────────┐
                      │ Copy to Vetted Vault    │
                      │   (Immutable Local)     │
                      └────────────┬────────────┘
                                   │
                                   ▼
                      ┌─────────────────────────┐
                      │ Execute from Local Vault│
                      └─────────────────────────┘
```

#### 1. Source Reputation Framework (Source Trust Tiers)

Every tool or MCP server is classified into a strict reputation tier based on its author, cryptographic signature, and origin:

- **Tier 1 (Official / Cryptographically Signed):**
  - *Origin:* Authored by verified vendors (Google, Anthropic, AWS, Microsoft) or explicitly local, user-authored scripts.
  - *Action:* Automatically approved. Bypasses deep code auditing, proceeds directly to execution.
- **Tier 2 (Verified Community):**
  - *Origin:* Popular, open-source packages (e.g., highly-starred GitHub repos) from reputable organizations.
  - *Action:* Fast-tracked if it matches a known-safe registry checksum; otherwise, undergoes automated static audit.
- **Tier 3 (Third-Party / Unknown / Ad-Hoc):**
  - *Origin:* Custom user links, newly uploaded hub skills, or community-shared MCP repositories.
  - *Action:* Hard security gate. Mandates complete automated code review and explicit user confirmation before any integration.

#### 2. Automated Sandbox & Code Auditor Agent

For Tier 2 (first-time) and Tier 3 tools, a specialized "Security Auditor" subagent is spawned to review the tool’s codebase:

- **Phase A: Static Analysis & Regex Linting:**
  - Looks for high-risk system commands (e.g., raw subprocess calls, `eval`, base64/obfuscated strings).
  - Flags suspicious file operations (accessing sensitive paths like `~/.aws/credentials`, `~/.ssh/`, or browser cookies).
  - Scans for unexpected network egress sockets (e.g., a simple formatting tool attempting to send POST requests).
- **Phase B: LLM-Based Security Audit Pass:**
  - Evaluates the tool’s source code against a strict security rubric.
  - Detects logical vulnerabilities like shell injection vector vulnerabilities, path traversal risks, and credential leakage.
  - **Result Generation:** Outputs a structured JSON report (`FAIL`, `WARN`, `PASS`) outlining findings. Any `FAIL` immediately blocks the tool.

#### 3. Immutable Vetted Local Vault, Checksum Cache & Lifecycle Updater

To eliminate high-latency auditing on every run and protect against "dependency poisoning" (where a package update introduces malicious code after it's been reviewed), we implement an **Immutable Local Cache with a Managed Lifecycle**:

- **SHA-256 Content Hashing:**
  - The coordinator calculates the SHA-256 hash of the tool's source code files.
  - It references a local database: `~/.hermes-coder/vetted_tools.db`.
- **Vault Operations:**
  - **Registry Match (Approved):** If the checksum is found and marked `APPROVED`, the coordinator skips the audit completely.
  - **Audit Pass:** If a tool passes the security review and is approved by the user, the coordinator copies the file(s) into an isolated local directory: `~/.hermes-coder/vetted_vault/`.
  - **Lock-In Execution (Immutability):** The coordinator **only executes the tool from the `vetted_vault/` local path**—never the remote or downloaded path. This ensures that even if the remote source is updated or compromised, your local execution remains perfectly safe, pinned, and untouched.

- **Upstream Update & Diff-Audit Lifecycle:**
  To ensure you don't miss out on valuable enhancements or bug fixes from upstream updates, we establish an **Asynchronous Upgrade & Diff-Audit Protocol**:
  1. **Background Version Monitoring:**
     - Asynchronously (or periodically via a background curator cron job), the Coordinator fetches the remote repository state and computes the latest upstream SHA-256 hash.
     - If the upstream hash differs from your local vault's hash, the tool is flagged as **`OUTDATED` (Update Available)**.
  2. **Quarantine & Diff-Auditing (Surgical Reviews):**
     - Rather than overwriting your active local vault copy, the Coordinator downloads the new upstream code into a temporary **Quarantine Directory**.
     - Instead of re-auditing the entire codebase (which is slow and expensive), the Security Auditor runs a **Surgical Diff Audit** focusing strictly on the changes (`git diff` or file comparison between the vault and quarantine versions).
  3. **User-Approved Atomicity:**
     - The Coordinator presents a clean, visual update card to you:

       ```text
       🔄 Upstream Tool Update Detected: 'tool-react-rendering'
       - Local Version Checksum:  [a1b2c3...] (APPROVED)
       - Upstream Version Checksum: [x9y8z7...] (PENDING)

       Security Audit Report on Diff:
       ✔ PASS (0 issues found in changed lines)
       ✔ Changes evaluated: Updated JSX runtime parsing for React 19.

       [Approve Update & Vault]    [Ignore & Keep Local Copy]
       ```

     - If you select **Approve**, the Coordinator atomically replaces the vault files with the quarantined code, registers the new SHA-256 checksum as the active approved hash, and archives the previous version for rollback safety. This guarantees you get the latest features with zero manual effort and absolute safety!

---

## 3. Implementation Mechanism & Multi-Engine Compatibility

The dynamic injection architecture adapts beautifully across all three supported coding engines, leveraging their individual strengths and bypassing their limitations.

### A. Summary of Engine Capabilities

| Capability / Feature | Claude Code (`claude`) | Antigravity (`agy`) | OpenCode (`opencode`) |
|----------------------|-------------------------|---------------------|-----------------------|
| **System Prompt Inj.** | Yes (`--append-system-prompt`) | No                  | No                    |
| **Tool Restriction**  | Yes (`--allowedTools`)  | Partial (`--sandbox`) | No                  |
| **File Attachment**  | Indirect (via prompt)   | Indirect (via prompt) | Yes (`-f` / `--file`) |
| **MCP Configuration**| `~/.claude/settings.json` | `~/.antigravitycli/config.yaml` | `~/.opencode/config.yaml` |

---

### B. Engine-Specific Integration Blueprints

#### 1. Claude Code Integration (Native / Surgical)

- **Skill Injection:** Injected surgically into the background system prompt using `--append-system-prompt '<curated pitfalls & specifications>'`.
- **Tool Restriction:** Enforced via `--allowedTools 'Read,Edit,Bash'` or restricted on-demand.
- **MCP Injection:** Accomplished by backing up and on-the-fly patching `~/.claude/settings.json` before running the `claude -p` command, then restoring it instantly upon process exit.

#### 2. Antigravity Integration (Prompt-Wrapped & Config-Patched)

- **Skill Injection (Prompt Wrapping):** Since `agy` lacks a system-prompt injection flag, the Coordinator **appends/wraps** the curated skill pitfalls and standards directly to the end of the user's task prompt inside a distinct fenced block:

  ```text
  <original task prompt>

  ══════════════════════════════════════════════════════════════
  CRITICAL REFERENCE STANDARDS (DO NOT DEVIATE)
  - Pitfalls to Avoid: [curated pitfalls from skill]
  - Architecture Rules: [curated guidelines from skill]
  ══════════════════════════════════════════════════════════════
  ```

  *This prompt-wrapping strategy is universally effective and preserves model instruction-following across all engines.*
- **MCP Injection:** Accomplished by patching the active workspace config file (`~/.antigravitycli/config.yaml`) during dispatch.

#### 3. OpenCode Integration (File-Attached & Model-Optimized)

- **Skill Injection (Dynamic File Attaching):** In addition to the Prompt-Wrapping strategy used for `agy`, OpenCode natively supports attaching file references via the `-f` / `--file` flags.
  - The Coordinator can dynamically attach the *exact reference template or schema* (e.g., a `.yaml` API schema or `.ts` mock file linked to the skill) directly using:
    `opencode run '<prompt>' --dir <workdir> -f <path-to-skill-template> -m <model>`
- **MCP Injection:** Accomplished by dynamically patching the local `~/.opencode/config.yaml` configuration during the dispatch execution block.
- **Model Optimization:** Leveraging OpenCode's `-m` flag, the Coordinator can automatically upgrade the engine model to `claude-opus-4-7` or a high-reasoning variant (`--variant high`) when launching an **L-sized** task, and drop to a fast `gemini-3.5-flash` for **S/M-sized** tasks.

---

### C. Container Runner Abstraction (Docker vs. Apple Containers)

To prevent hard-coding a dependency on Docker (which is slow on macOS due to Linux VM translation layers), the Security Gateway abstracts all untrusted MCP server and sandbox execution through a pluggable **Container Runner Interface**.

This interface dynamically routes executions depending on the host hardware architecture and installed packages:

#### 1. M-Series (Apple Silicon) Macs → Apple Containers (Default)

- **Why it's faster:** Apple Containers (leveraging macOS's native `Virtualization.framework` and the open-source `container` CLI) are **massively faster and more memory-efficient** than Docker Desktop.
  - *No Linux VM Boot Overhead:* Instead of spinning up a full Linux guest OS, Apple Containers boot lightweight macOS-native container tasks directly.
  - *Native Thread Scheduling:* Process threads are scheduled directly by macOS's kernel, taking full advantage of Apple Silicon's Performance (P) and Efficiency (E) core architecture.
  - *Zero-Overhead File Mounts:* File sharing occurs natively without the slow virtualized file-system translation layers (like gRPC FUSE or VirtioFS) that plague Docker on macOS.
- **Implementation:** The Coordinator invokes commands directly via the native open-source **`container run`** CLI. This keeps the core implementation lightweight and free of external MCP dependencies, with any integration of custom MCP servers (like `AppleContainerMCP`) treated strictly as an optional, opt-in layer.

#### 2. Intel Macs & Linux Hosts → Docker (Fallback)

- **The Intel Mac Reality:** Since Intel Macs do not support the Apple Silicon-specific virtualization features of `container`, the interface automatically falls back to **Docker**.
- **Implementation:** Leverages standard, localized Docker configurations (`docker run --rm -d --network none ...`) to ensure the design is fully backward-compatible and portable, allowing development to proceed flawlessly on your current Intel Mac while instantly scaling up to native speeds if you migrate to an M-series machine.

#### 3. Automatic Runner Probe & Selection

At Coordinator initialization, a fast, lightweight probe runs:

```python
import shutil, platform

def resolve_container_runner() -> str:
    # 1. Check if 'container' command is available (Apple Containers)
    if shutil.which("container") and platform.machine() == "arm64":
        return "apple-container"
    # 2. Check if docker is available
    elif shutil.which("docker"):
        return "docker"
    # 3. Fallback to native local execution (Strict Sandbox Mode)
    return "local-restricted"
```

The selected runner is stored in the session state and used to wrap all subsequent Tier 3 MCP executions.

---

## 4. Next Steps & Phase 1 Plan

To prove this concept, we should build a minimal, high-leverage prototype:

1. **Define the Metadata Schema:** Add a small structured header to our skills outlining `frameworks`, `file_patterns`, and `complexity_threshold`.
2. **Build the Triage Script:** Create a simple Python script under `scripts/dynamic_curator.py` that parses a prompt and a file, and outputs the top matching local skill.
3. **Integrate with Claude-Code Harness:** Patch our `claude-code` skill to execute `dynamic_curator.py` and inject its output via `--append-system-prompt` for Medium/Large tasks.
