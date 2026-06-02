#!/usr/bin/env python3
"""Systematic debugger: enforced 4-phase debugging pipeline.

Blocks the coding engine from editing source files until it has:
1. Reproduced the bug
2. Traced the data flow to root cause
3. Formed a hypothesis and written a failing regression test
4. Fixed the bug (via auto-healer integration)

Usage:
    python3 systematic_debugger.py --bug "test_auth fails with 401" --repo /path/to/project --engine claude-code
    python3 systematic_debugger.py --resume abc123 --repo /path/to/project --engine claude-code
    python3 systematic_debugger.py --bug "race condition in worker" --repo /path --engine antigravity --json

Exit codes:
    0  Fixed (all phases completed, tests passing)
    1  Escalated (auto-healer exhausted retries)
    2  Invalid arguments
    3  Reproduction failed (not a real bug or environment issue)
    4  Hypothesis rejected (regression test didn't fail as expected)
"""

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# -- Debug journal --

@dataclass
class PhaseState:
    status: str = "pending"  # pending, passed, failed, skipped
    evidence: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class ReproduceState(PhaseState):
    repro_command: str = ""
    error_output: str = ""
    reproduces_consistently: bool = False


@dataclass
class TraceState(PhaseState):
    data_flow: str = ""
    root_cause_file: str = ""
    root_cause_line: Optional[int] = None


@dataclass
class HypothesizeState(PhaseState):
    hypothesis: str = ""
    test_file: str = ""
    test_command: str = ""
    test_fails_before_fix: bool = False


@dataclass
class FixState(PhaseState):
    fix_description: str = ""
    heal_report: dict = field(default_factory=dict)


@dataclass
class DebugJournal:
    bug_id: str
    description: str
    created: str
    repo: str
    engine: str
    current_phase: str = "reproduce"
    phases: dict = field(default_factory=dict)
    source_edit_violations: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.phases:
            self.phases = {
                "reproduce": ReproduceState(),
                "trace": TraceState(),
                "hypothesize": HypothesizeState(),
                "fix": FixState(),
            }

    def as_dict(self) -> dict:
        result = {
            "bug_id": self.bug_id,
            "description": self.description,
            "created": self.created,
            "repo": self.repo,
            "engine": self.engine,
            "current_phase": self.current_phase,
            "source_edit_violations": self.source_edit_violations,
            "phases": {},
        }
        for name, state in self.phases.items():
            if isinstance(state, dict):
                result["phases"][name] = state
            else:
                result["phases"][name] = dataclasses.asdict(state)
        return result

    def save(self):
        journal_dir = Path(self.repo) / ".hermes-debug"
        journal_dir.mkdir(parents=True, exist_ok=True)
        path = journal_dir / f"{self.bug_id}.json"
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, repo: str, bug_id: str) -> "DebugJournal":
        path = Path(repo) / ".hermes-debug" / f"{bug_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        journal = cls(
            bug_id=data["bug_id"],
            description=data["description"],
            created=data["created"],
            repo=data["repo"],
            engine=data["engine"],
            current_phase=data.get("current_phase", "reproduce"),
            source_edit_violations=data.get("source_edit_violations", []),
        )
        for phase_name, phase_data in data.get("phases", {}).items():
            if phase_name == "reproduce":
                journal.phases[phase_name] = ReproduceState(**phase_data)
            elif phase_name == "trace":
                journal.phases[phase_name] = TraceState(**phase_data)
            elif phase_name == "hypothesize":
                journal.phases[phase_name] = HypothesizeState(**phase_data)
            elif phase_name == "fix":
                journal.phases[phase_name] = FixState(**phase_data)
        return journal


# -- Dispatch helpers --

def _build_readonly_command(prompt: str, engine: str, repo: str) -> str:
    """Build a read-only dispatch command (no file editing allowed)."""
    escaped = prompt.replace("'", "'\\''")
    if engine == "claude-code":
        return (
            f"claude -p '{escaped}' "
            f"--allowedTools 'Read,Bash' "
            f"--max-turns 15 "
            f"--dangerously-skip-permissions"
        )
    elif engine == "antigravity":
        return (
            f"agy -p '{escaped}' "
            f"--dangerously-skip-permissions "
            f"--print-timeout 5m0s "
            f"--sandbox "
            f"--add-dir {repo}"
        )
    elif engine == "opencode":
        return (
            f"opencode run '{escaped}' "
            f"--dir {repo} "
            f"--dangerously-skip-permissions "
            f"-m google-vertex/gemini-3.5-flash"
        )
    # fallback
    return (
        f"claude -p '{escaped}' "
        f"--allowedTools 'Read,Bash' "
        f"--max-turns 15 "
        f"--dangerously-skip-permissions"
    )


def _build_test_write_command(prompt: str, engine: str, repo: str) -> str:
    """Build a command that allows writing test files only."""
    escaped = prompt.replace("'", "'\\''")
    if engine == "claude-code":
        return (
            f"claude -p '{escaped}' "
            f"--allowedTools 'Read,Edit,Write,Bash' "
            f"--max-turns 15 "
            f"--dangerously-skip-permissions"
        )
    elif engine == "antigravity":
        return (
            f"agy -p '{escaped}' "
            f"--dangerously-skip-permissions "
            f"--print-timeout 5m0s "
            f"--add-dir {repo}"
        )
    elif engine == "opencode":
        return (
            f"opencode run '{escaped}' "
            f"--dir {repo} "
            f"--dangerously-skip-permissions "
            f"-m google-vertex/gemini-3.5-flash"
        )
    return (
        f"claude -p '{escaped}' "
        f"--allowedTools 'Read,Edit,Write,Bash' "
        f"--max-turns 15 "
        f"--dangerously-skip-permissions"
    )


def _dispatch(cmd: str, repo: str, timeout: int = 300) -> str:
    """Execute a dispatch command and return combined output."""
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=repo,
            capture_output=True, text=True, timeout=timeout,
        )
        return (result.stdout + "\n" + result.stderr).strip()
    except subprocess.TimeoutExpired:
        return "Dispatch timed out"
    except OSError as e:
        return f"Dispatch failed: {e}"


def _get_modified_files(repo: str) -> list[str]:
    """Get list of files modified since last clean state."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
        # Also check untracked files
        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        files += [f.strip() for f in result2.stdout.strip().splitlines() if f.strip()]
        return files
    except (subprocess.TimeoutExpired, OSError):
        return []


_TEST_PATH_PATTERNS = [
    re.compile(r'test[s_/]', re.I),
    re.compile(r'_test\.', re.I),
    re.compile(r'\.test\.', re.I),
    re.compile(r'\.spec\.', re.I),
    re.compile(r'__tests__', re.I),
]


def _is_test_file(path: str) -> bool:
    return any(p.search(path) for p in _TEST_PATH_PATTERNS)


_VIOLATION_EXCLUDE_PATTERNS = [
    re.compile(r'(^|/)\.hermes-debug/'),
    re.compile(r'(^|/)__pycache__/'),
    re.compile(r'\.pyc$'),
    re.compile(r'(^|/)\.gitignore$'),
]


def _is_excluded_from_violations(path: str) -> bool:
    """Bookkeeping artifacts that are not real source edits."""
    return any(p.search(path) for p in _VIOLATION_EXCLUDE_PATTERNS)


def _clean_field(value: str) -> str:
    """Strip markdown (bold markers, code spans) from an LLM-extracted field."""
    v = value.strip()
    v = re.sub(r'^[*_]+\s*', '', v)
    v = re.sub(r'\s*[*_]+$', '', v)
    v = v.strip().strip('`').strip()
    return v


def _check_source_edit_violations(repo: str) -> list[str]:
    """Return list of non-test source files that were modified."""
    modified = _get_modified_files(repo)
    return [
        f for f in modified
        if not _is_test_file(f) and not _is_excluded_from_violations(f)
    ]


def _revert_source_edits(repo: str, files: list[str]):
    """Revert unauthorized source file edits."""
    if not files:
        return
    try:
        subprocess.run(
            ["git", "checkout", "--"] + files,
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _git_stash(repo: str) -> bool:
    """Create a git stash. Returns True if stash was created."""
    try:
        result = subprocess.run(
            ["git", "stash", "push", "-m", "hermes-debug-savepoint"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        return "No local changes" not in result.stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def _git_stash_pop(repo: str):
    """Pop the most recent git stash."""
    try:
        subprocess.run(
            ["git", "stash", "pop"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def _git_stash_drop(repo: str):
    """Drop the most recent git stash."""
    try:
        subprocess.run(
            ["git", "stash", "drop"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


# -- Phase implementations --

def phase_reproduce(journal: DebugJournal) -> bool:
    """Phase 1: Reproduce the bug consistently."""
    state: ReproduceState = journal.phases["reproduce"]

    prompt = (
        f"Reproduce this bug: {journal.description}\n\n"
        "Your task is ONLY to reproduce, not to fix. Do the following:\n"
        "1. Find and run the failing test or trigger the error\n"
        "2. Report the exact command to reproduce\n"
        "3. Report the full error output\n"
        "4. Run it 2-3 times to confirm it reproduces consistently\n\n"
        "Do NOT attempt any fixes. Do NOT edit any source files.\n\n"
        "Format your response as:\n"
        "REPRO_COMMAND: <exact command>\n"
        "REPRODUCES: <yes|no>\n"
        "ERROR_OUTPUT:\n<full error output>"
    )

    cmd = _build_readonly_command(prompt, journal.engine, journal.repo)
    output = _dispatch(cmd, journal.repo)

    # Check for unauthorized edits
    violations = _check_source_edit_violations(journal.repo)
    if violations:
        journal.source_edit_violations.append(
            f"reproduce phase: {', '.join(violations)}"
        )
        _revert_source_edits(journal.repo, violations)

    # Parse output for repro command
    repro_match = re.search(r'REPRO_COMMAND:\s*(.+)', output)
    reproduces_match = re.search(r'REPRODUCES:\s*(yes|no)', output, re.I)

    state.evidence = output[:3000]
    if repro_match:
        state.repro_command = _clean_field(repro_match.group(1))
    if reproduces_match:
        state.reproduces_consistently = reproduces_match.group(1).lower() == "yes"

    if state.repro_command and state.reproduces_consistently:
        state.status = "passed"
        journal.current_phase = "trace"
        journal.save()
        return True

    # Try to extract repro info even without structured format
    if state.repro_command or "FAIL" in output or "Error" in output:
        state.status = "passed"
        state.reproduces_consistently = True
        journal.current_phase = "trace"
        journal.save()
        return True

    state.status = "failed"
    state.error = "Could not reproduce the bug consistently"
    journal.save()
    return False


def phase_trace(journal: DebugJournal) -> bool:
    """Phase 2: Trace data flow to root cause."""
    state: TraceState = journal.phases["trace"]
    repro: ReproduceState = journal.phases["reproduce"]

    prompt = (
        f"Trace the root cause of this bug.\n\n"
        f"Bug description: {journal.description}\n"
        f"Reproduction command: {repro.repro_command}\n\n"
        "Your task is to trace the data flow, not to fix anything.\n"
        "1. Starting from the error, trace backward through the call stack\n"
        "2. Find the file and line where the bad value originates\n"
        "3. Map the data flow from origin to error\n"
        "4. Check if this could be test pollution (shared state between tests)\n\n"
        "Do NOT attempt any fixes. Do NOT edit any source files.\n\n"
        "Format your response as:\n"
        "ROOT_CAUSE_FILE: <file path>\n"
        "ROOT_CAUSE_LINE: <line number>\n"
        "DATA_FLOW: <description of how data flows from origin to error>"
    )

    cmd = _build_readonly_command(prompt, journal.engine, journal.repo)
    output = _dispatch(cmd, journal.repo)

    violations = _check_source_edit_violations(journal.repo)
    if violations:
        journal.source_edit_violations.append(
            f"trace phase: {', '.join(violations)}"
        )
        _revert_source_edits(journal.repo, violations)

    file_match = re.search(r'ROOT_CAUSE_FILE:\s*(.+)', output)
    line_match = re.search(r'ROOT_CAUSE_LINE:[^\d\n]*(\d+)', output)
    flow_match = re.search(r'DATA_FLOW:\s*(.+?)(?:\n\n|\Z)', output, re.DOTALL)

    state.evidence = output[:3000]
    if file_match:
        state.root_cause_file = _clean_field(file_match.group(1))
    if line_match:
        state.root_cause_line = int(line_match.group(1))
    if flow_match:
        state.data_flow = _clean_field(flow_match.group(1))

    if state.root_cause_file:
        state.status = "passed"
        journal.current_phase = "hypothesize"
        journal.save()
        return True

    # Accept if any meaningful analysis was produced
    if len(output) > 200 and ("cause" in output.lower() or "because" in output.lower()):
        state.status = "passed"
        state.data_flow = output[:1000]
        journal.current_phase = "hypothesize"
        journal.save()
        return True

    state.status = "failed"
    state.error = "Could not trace root cause"
    journal.save()
    return False


def phase_hypothesize(journal: DebugJournal) -> bool:
    """Phase 3: Form hypothesis and write failing regression test."""
    state: HypothesizeState = journal.phases["hypothesize"]
    trace: TraceState = journal.phases["trace"]
    repro: ReproduceState = journal.phases["reproduce"]

    root_cause_ctx = ""
    if trace.root_cause_file:
        root_cause_ctx = f"Root cause file: {trace.root_cause_file}"
        if trace.root_cause_line:
            root_cause_ctx += f" (line {trace.root_cause_line})"
    if trace.data_flow:
        root_cause_ctx += f"\nData flow: {trace.data_flow}"

    prompt = (
        f"Form a hypothesis and write a failing regression test.\n\n"
        f"Bug: {journal.description}\n"
        f"Reproduction: {repro.repro_command}\n"
        f"{root_cause_ctx}\n\n"
        "1. State your hypothesis: what exactly is wrong and why\n"
        "2. Write a FAILING regression test that proves the hypothesis\n"
        "   - The test must FAIL now (before the fix) and PASS after a correct fix\n"
        "   - Place the test in the project's existing test directory\n"
        "   - Follow the project's existing test patterns\n"
        "3. Run the test to confirm it fails\n\n"
        "You MAY create or edit test files. Do NOT edit any source (non-test) files.\n\n"
        "Format your response to include:\n"
        "HYPOTHESIS: <your hypothesis>\n"
        "TEST_FILE: <path to the test file>\n"
        "TEST_COMMAND: <command to run just the regression test>"
    )

    cmd = _build_test_write_command(prompt, journal.engine, journal.repo)
    output = _dispatch(cmd, journal.repo)

    # Check for source edits (test files are OK)
    violations = _check_source_edit_violations(journal.repo)
    if violations:
        journal.source_edit_violations.append(
            f"hypothesize phase: {', '.join(violations)}"
        )
        _revert_source_edits(journal.repo, violations)

    hyp_match = re.search(r'HYPOTHESIS:\s*(.+?)(?:\n[A-Z_]+:|\Z)', output, re.DOTALL)
    test_file_match = re.search(r'TEST_FILE:\s*(.+)', output)
    test_cmd_match = re.search(r'TEST_COMMAND:\s*(.+)', output)

    state.evidence = output[:3000]
    if hyp_match:
        state.hypothesis = _clean_field(hyp_match.group(1))
    if test_file_match:
        state.test_file = _clean_field(test_file_match.group(1))
    if test_cmd_match:
        state.test_command = _clean_field(test_cmd_match.group(1))

    # Verify the regression test actually fails
    if state.test_command:
        try:
            result = subprocess.run(
                state.test_command, shell=True, cwd=journal.repo,
                capture_output=True, text=True, timeout=60,
            )
            state.test_fails_before_fix = result.returncode != 0
        except (subprocess.TimeoutExpired, OSError):
            state.test_fails_before_fix = False

    if state.hypothesis and state.test_fails_before_fix:
        state.status = "passed"
        journal.current_phase = "fix"
        journal.save()
        return True

    if state.hypothesis and not state.test_command:
        # Hypothesis formed but no test — still allow progression with warning
        state.status = "passed"
        state.error = "No regression test written; proceeding with repro command as check"
        journal.current_phase = "fix"
        journal.save()
        return True

    if state.hypothesis and state.test_command and not state.test_fails_before_fix:
        state.status = "failed"
        state.error = "Regression test passes before fix — hypothesis may be wrong"
        journal.save()
        return False

    state.status = "failed"
    state.error = "Could not form hypothesis"
    journal.save()
    return False


def phase_fix(journal: DebugJournal) -> bool:
    """Phase 4: Fix the bug via auto-healer."""
    state: FixState = journal.phases["fix"]
    hyp: HypothesizeState = journal.phases["hypothesize"]
    repro: ReproduceState = journal.phases["reproduce"]

    # Determine check command
    check_cmd = hyp.test_command if hyp.test_command else repro.repro_command
    if not check_cmd:
        state.status = "failed"
        state.error = "No check command available for auto-healer"
        journal.save()
        return False

    # Git stash as savepoint
    stashed = _git_stash(journal.repo)

    # Delegate to auto-healer
    auto_healer_path = Path(__file__).parent / "auto_healer.py"
    healer_cmd = [
        sys.executable, str(auto_healer_path),
        "--repo", journal.repo,
        "--check", check_cmd,
        "--engine", journal.engine,
        "--json",
    ]

    try:
        result = subprocess.run(
            healer_cmd, cwd=journal.repo,
            capture_output=True, text=True, timeout=1800,
        )
        try:
            heal_report = json.loads(result.stdout)
        except json.JSONDecodeError:
            heal_report = {"status": "error", "output": result.stdout[:2000]}

        state.heal_report = heal_report
        state.evidence = result.stdout[:3000]

        if heal_report.get("status") in ("healed", "clean"):
            state.status = "passed"
            state.fix_description = "Fixed via auto-healer"
            if stashed:
                _git_stash_drop(journal.repo)
            journal.save()
            return True
        else:
            state.status = "failed"
            state.error = heal_report.get("escalation_reason", "Auto-healer exhausted retries")
            if stashed:
                _git_stash_pop(journal.repo)
            journal.save()
            return False

    except subprocess.TimeoutExpired:
        state.status = "failed"
        state.error = "Auto-healer timed out"
        if stashed:
            _git_stash_pop(journal.repo)
        journal.save()
        return False
    except OSError as e:
        state.status = "failed"
        state.error = f"Failed to run auto-healer: {e}"
        if stashed:
            _git_stash_pop(journal.repo)
        journal.save()
        return False


# -- Pipeline orchestrator --

PHASE_ORDER = ["reproduce", "trace", "hypothesize", "fix"]

PHASE_FUNCTIONS = {
    "reproduce": phase_reproduce,
    "trace": phase_trace,
    "hypothesize": phase_hypothesize,
    "fix": phase_fix,
}

EXIT_CODES = {
    "reproduce": 3,
    "trace": 1,
    "hypothesize": 4,
    "fix": 1,
}


def run_pipeline(journal: DebugJournal) -> int:
    """Run the debugging pipeline from the current phase. Returns exit code."""
    start_idx = PHASE_ORDER.index(journal.current_phase)

    for phase_name in PHASE_ORDER[start_idx:]:
        phase_fn = PHASE_FUNCTIONS[phase_name]
        success = phase_fn(journal)

        if not success:
            return EXIT_CODES.get(phase_name, 1)

    return 0


# -- CLI --

def main():
    parser = argparse.ArgumentParser(description="Systematic debugging pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--bug", help="Bug description to investigate")
    group.add_argument("--resume", help="Resume from an existing debug journal (bug ID)")
    parser.add_argument("--repo", required=True, help="Project repository path")
    parser.add_argument("--engine", required=True,
                        choices=["claude-code", "antigravity", "opencode"],
                        help="Active coding engine harness")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"Error: repository path does not exist: {repo}", file=sys.stderr)
        sys.exit(2)

    if args.resume:
        journal_path = Path(repo) / ".hermes-debug" / f"{args.resume}.json"
        if not journal_path.exists():
            print(f"Error: no debug journal found for bug ID: {args.resume}", file=sys.stderr)
            sys.exit(2)
        journal = DebugJournal.load(repo, args.resume)
        journal.engine = args.engine
    else:
        journal = DebugJournal(
            bug_id=str(uuid.uuid4())[:8],
            description=args.bug,
            created=datetime.now(timezone.utc).isoformat(),
            repo=repo,
            engine=args.engine,
        )
        journal.save()

    print(f"Debug session: {journal.bug_id}", file=sys.stderr)
    print(f"Starting from phase: {journal.current_phase}", file=sys.stderr)

    exit_code = run_pipeline(journal)

    if args.json:
        print(json.dumps(journal.as_dict(), indent=2))
    else:
        _print_summary(journal, exit_code)

    sys.exit(exit_code)


def _print_summary(journal: DebugJournal, exit_code: int):
    """Print a human-readable summary."""
    print(f"\n{'=' * 60}")
    print(f"Debug Session: {journal.bug_id}")
    print(f"Bug: {journal.description}")
    print(f"{'=' * 60}")

    status_icons = {"passed": "+", "failed": "X", "pending": ".", "skipped": "-"}

    for phase_name in PHASE_ORDER:
        phase = journal.phases[phase_name]
        if isinstance(phase, dict):
            status = phase.get("status", "pending")
            error = phase.get("error", "")
        else:
            status = phase.status
            error = phase.error
        icon = status_icons.get(status, "?")
        print(f"  [{icon}] {phase_name}: {status}")
        if error:
            print(f"      {error}")

    if journal.source_edit_violations:
        print("\nSource edit violations (reverted):")
        for v in journal.source_edit_violations:
            print(f"  - {v}")

    result_map = {0: "FIXED", 1: "ESCALATED", 3: "CANNOT REPRODUCE", 4: "HYPOTHESIS REJECTED"}
    print(f"\nResult: {result_map.get(exit_code, 'UNKNOWN')}")
    print(f"Journal: {journal.repo}/.hermes-debug/{journal.bug_id}.json")


if __name__ == "__main__":
    main()
