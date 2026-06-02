# Case Study: Comprehensive Monorepo Review using Antigravity (agy)

This reference documents the pattern used to conduct an end-to-end architectural and code-level review of a multi-language multi-agent monorepo (**Race Condition**) using the Antigravity (`agy`) harness, incorporating user preferences for technical evaluations.

## Coordinator Dispatch Pattern

When tasked with a high-level review of a complex, multi-language monorepo, the coordinator should dispatch a comprehensive, read-only analysis task to the `agy` coding engine with clear scoping across all sub-components.

### Dispatch Prompt

```bash
agy -p "Conduct a comprehensive review of the <project-name> monorepo.
Focus on:
1. Go Gateway (cmd/gateway/, internal/) - concurrency, Redis/PubSub handling, WebSockets, error handling, performance.
2. Python ADK Agents (agents/) - Google ADK API usage, prompting, concurrency, state management, test coverage.
3. TypeScript Frontend (web/) - Angular, Three.js rendering, NDJSON replay, state management, WebSockets.
4. Infrastructure & DevOps (Dockerfile, docker-compose.yml, cloudbuild-bootstrap.yaml, infra/) - reliability, scaling, local DX.

List specific issues, technical debt, security gaps, and architectural improvements. Evaluate findings by Impact, Effort, and Risk." --dangerously-skip-permissions --print-timeout 5m0s --add-dir <project-dir>
```

---

## Technical Recommendations Evaluation Framework

When synthesizing findings from `agy`, the coordinator must structure all recommended improvements using the user's preferred evaluation framework, grading each item across three axes:

1. **Impact** (High/Medium/Low) — The magnitude of the positive outcome (e.g., performance gain, reliability fix, security mitigation).
2. **Level of Effort (LOE)** (High/Medium/Low) — The complexity and engineering time required to implement.
3. **Risk to Implementation** (High/Medium/Low) — The likelihood of introducing regressions, breaking public APIs, or causing deployment failures.

### Consolidation Rule

Consolidate all finalized recommendations into a single-source-of-truth **`BACKLOG.md`** file located in the root of the repository. If a backlog or roadmap file already exists, append the findings directly to it to avoid cluttering the repository with duplicate tracking files.

---

## Example Backlog Entry Format

```markdown
## N. [Descriptive Name]

* **Target Area**: [e.g., Go Session Registry (`internal/session/redis_registry.go`)]
* **Technical Context**: Detailed explanation of the current bottleneck, code patterns, or bug.
* **Impact**: High / Medium / Low
* **Level of Effort**: High / Medium / Low
* **Risk to Implementation**: High / Medium / Low
* **Actionable Remediation**: Specific step-by-step instructions or diff patterns showing how to resolve.
```
