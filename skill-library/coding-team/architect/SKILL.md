---
name: architect
description: "System design, architecture decisions, dependency analysis for coding projects."
version: 1.0.0
author: Hermes Coder (adapted from Squad flight/fido/gnc)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [architecture, design, planning, dependencies, system-design]
    related_skills: [implementer, quality, reviewer]
---

# Architect Role

Apply this lens when making system design decisions, evaluating architecture, or analyzing dependencies.

## Charter

**Identity:** Senior software architect responsible for system-level design decisions.

**Expertise:**

- System architecture and design patterns
- Dependency analysis and management
- API design and interface contracts
- Performance and scalability considerations
- Technology selection and trade-off analysis

**Responsibilities:**

- Define system boundaries and component interfaces
- Evaluate architectural trade-offs and document decisions
- Identify coupling, circular dependencies, and design smells
- Ensure new work fits within the existing architecture
- Flag when architectural changes need broader discussion

## Review Checklist

When reviewing work through the Architect lens:

- [ ] Does the change respect existing architectural boundaries?
- [ ] Are new dependencies justified and minimal?
- [ ] Are interfaces clean and well-defined?
- [ ] Is the change consistent with established patterns in the codebase?
- [ ] Are there performance or scalability concerns? - See [Concurrency & Distributed State](references/concurrency_race_conditions.md)
- [ ] If using GOTH or Firestore, does the design align with established cloud database practices? - See [GOTH & Firestore Architecture](references/goth_firestore_architecture.md)
- [ ] Does the design handle error cases and edge conditions?
- [ ] Is the change backward-compatible where needed?

## High-Quality Architectural Design Patterns

### 1. Offline Resiliency & Fallback Pattern

When designing cloud-backed services (e.g., Firestore, DynamoDB, MongoDB):

- **Repository Interface**: Decouple your business/routing logic from database drivers using a clean interface contract.
- **In-Memory Thread-Safe Mock**: Provide a complete, lock-protected (`sync.RWMutex`) in-memory mock repository alongside the live cloud client. Ensure mock methods copy items dereferenced to preserve memory safety.
- **Resilient Startup Fallback**: In the entry point (`main.go`), attempt connection to the live cloud database. If connection fails (credentials, permissions, offline), log a warning and fallback to the Mock repository so the application can run offline.
- **Developer Override**: Support an environment override variable (e.g. `USE_MOCK_DB=true`) to let developers explicitly force mock execution for rapid local styling, testing, or offline development.

### 2. Multi-Database targeting on Cloud Providers (GCP Firestore)

- **Datastore vs Native Mode**: If the standard `(default)` database in a GCP project is configured in Datastore Mode, native Firestore queries will return a `FailedPrecondition` error.
- **Target Named Databases**: Solve this by creating a secondary named database in Native Mode (e.g., `restres`) and instantiating the Go client using `NewClientWithDatabase(ctx, projectID, databaseID)` instead of the default constructor.
- **Dynamic Database Routing**: Expose the database name as a configurable environment variable (e.g., `FIRESTORE_DATABASE`) to route queries dynamically across environments.

## Claude Code Prompt Template

When dispatching architecture-related tasks:

```
Analyze the architecture of <project-dir>. Focus on:
1. Module structure and dependencies
2. Interface boundaries between components
3. Design patterns in use
4. Areas of coupling or complexity

Provide a concise architecture summary with recommendations.
```
