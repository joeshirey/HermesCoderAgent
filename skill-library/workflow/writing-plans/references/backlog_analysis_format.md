# Backlog & Codebase Analysis Format

When performing an exhaustive review of a codebase to generate recommendations or update a backlog:

1. **Independent Analysis First**: Ignore existing backlog files during the initial analysis phase. Compare findings to the existing backlog only after the analysis is complete.
2. **Evaluation Criteria**: For each discovered item, provide an opinion on:
   - **Impact**: How much it matters for correctness, security, or user/admin experience.
   - **Level of Effort**: Rough size of the change (e.g., Small/Hours, Medium/Days, Large/Multi-day).
   - **Risk**: The chance the change breaks something or needs a careful rollout.
3. **Single Source of Truth**: Consolidate findings into the existing backlog file (e.g., in `.local/`) rather than creating scattered new files. Update statuses of completed items and integrate new discoveries into coherent execution groups.
