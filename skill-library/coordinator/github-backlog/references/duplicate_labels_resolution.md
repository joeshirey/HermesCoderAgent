# Duplicate Namespaced Labels Bug & Conflict Resolution

## Context

During backlog triage sweeps (`github_backlog.py triage`), some issues accumulated duplicate and conflicting labels from the same namespaced category (e.g., carrying both `effort:L` and `effort:XL` or `risk:medium` and `risk:low` simultaneously). This made the issue cards on the Kanban board and GitHub Issue view confusing and inconsistent.

## Root Cause Analysis

The original implementation of `_conflicting_states` in `github_backlog.py` was overly narrow:

```python
def _conflicting_states(new_labels, current_labels) -> list:
    """State labels currently on the issue that a new label set supersedes."""
    new = set(new_labels)
    return [l for l in current_labels
            if l in BACKLOG_STATE_LABELS and l not in new]
```

It only checked and cleared mutually exclusive labels from the `backlog:*` namespace. It completely ignored all other namespaced categories:

* `type:*`
* `severity:*`
* `effort:*`
* `risk:*`
* `impact:*`
* `confidence:*`

As a result, if an issue was re-classified during a sweep or refined in a subsequent session, the older labels remained on the issue alongside the new ones.

## The Solution

We patched `_conflicting_states` with a **generalized, prefix-aware conflict resolver**:

```python
def _conflicting_states(new_labels, current_labels) -> list:
    """Find namespaced labels currently on the issue that the new label set supersedes."""
    new_prefixes = {}
    for l in new_labels:
        if ":" in l:
            prefix = l.split(":", 1)[0] + ":"
            new_prefixes[prefix] = l

    to_remove = []
    for l in current_labels:
        if ":" in l:
            prefix = l.split(":", 1)[0] + ":"
            if prefix in new_prefixes and l != new_prefixes[prefix]:
                to_remove.append(l)
    return to_remove
```

### How It Works

1. It loops through the `new_labels` to identify all namespaced categories being applied (e.g., `effort:`, `risk:`).
2. It maps each prefix to the specific label being applied (e.g., `effort:` -> `effort:M`).
3. It iterates through the issue's existing labels (`current_labels`) and marks any label for removal if its prefix matches one of the new categories but has a different value (e.g., `effort:S` is marked for removal because the new label is `effort:M`).

This ensures absolute mutual exclusivity within *all* namespaced categories automatically.

## Instant Backlog Cleanup Script

To instantly resolve existing conflicts across all historical issues on GitHub without making expensive and slow LLM calls, use this fast python one-liner inline script:

```bash
python3 -c "
import subprocess

resolutions = {
    21: ['risk:medium'],  # keep risk:low
    19: ['effort:XL'],    # keep effort:L
    16: ['risk:medium'],  # keep risk:high
    15: ['severity:critical', 'risk:medium'], # keep severity:medium, risk:low
    14: ['effort:L'],     # keep effort:XL
    13: ['impact:internal-debt'], # keep impact:user-visible
    10: ['effort:S', 'risk:low', 'confidence:medium'] # keep effort:M, risk:high, confidence:high
}

for num, to_remove in resolutions.items():
    cmd = ['gh', 'issue', 'edit', str(num)]
    for r in to_remove:
        cmd += ['--remove-label', r]
    print(f'Cleaning up Issue #{num}...', flush=True)
    subprocess.run(cmd, check=True)
"
```
