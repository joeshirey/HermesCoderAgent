#!/usr/bin/env python3
"""Parallel multi-task dispatcher.

Executes a pre-declared batch of independent coding tasks concurrently, each
isolated in its own git worktree + branch. It does NOT decide what is
independent -- decomposition is the coordinator's job. This script only runs the
mechanics safely: serial worktree creation (avoids git index lock races),
concurrent dispatch, result collection. It never merges and never deletes
existing branches -- the coordinator reviews each branch and merges sequentially.

Usage:
    # Spec on stdin
    echo '{"tasks":[{"id":"api","prompt":"...","scope":["src/api/**"]}]}' \\
        | python3 parallel_dispatch.py --repo /path/to/repo --engine claude-code

    # Spec from a file, dry run (no worktrees created, no engines invoked)
    python3 parallel_dispatch.py --repo /path/to/repo --spec batch.json --dry-run

Exit codes:
    0  All dispatches succeeded
    1  One or more dispatches failed (report still emitted)
    2  Invalid arguments / not a git repo / bad spec
"""

import argparse
import fnmatch
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from auto_healer import build_dispatch_command

try:
    from dispatch_receipts import record as _record_dispatch
except ImportError:
    _record_dispatch = None


# -- Config defaults (overridable via ~/.hermes-coder/config.yaml) --

DEFAULT_MAX_PARALLEL = 3
DEFAULT_TIMEOUT = 600
DEFAULT_WORKTREE_DIRNAME = ".hermes-worktrees"
DEFAULT_BRANCH_PREFIX = "hermes/"
DEFAULT_MAX_TURNS = 15
ENGINES = ["claude-code", "antigravity", "opencode"]
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
OUTPUT_TAIL_CHARS = 2000


# -- Dataclasses --

@dataclass
class TaskSpec:
    id: str
    prompt: str
    scope: list = field(default_factory=list)
    max_turns: int = DEFAULT_MAX_TURNS

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt,
            "scope": self.scope,
            "max_turns": self.max_turns,
        }


@dataclass
class DispatchResult:
    id: str
    branch: str
    worktree: str
    status: str  # success | failed | timeout | error
    returncode: Optional[int] = None
    duration_s: float = 0.0
    output_tail: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "branch": self.branch,
            "worktree": self.worktree,
            "status": self.status,
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 1),
            "output_tail": self.output_tail,
            "error": self.error,
        }


@dataclass
class BatchReport:
    engine: str
    repo: str
    base_ref: str
    dry_run: bool = False
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "engine": self.engine,
            "repo": self.repo,
            "base_ref": self.base_ref,
            "dry_run": self.dry_run,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "results": [r.as_dict() for r in self.results],
            "warnings": self.warnings,
        }


# -- Git helpers --

def is_git_repo(repo: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", repo, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, OSError):
        return False


def resolve_base_ref(repo: str, base: Optional[str]) -> Optional[str]:
    ref = base or "HEAD"
    try:
        result = subprocess.run(
            ["git", "-C", repo, "rev-parse", ref],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def prune_worktrees(repo: str) -> None:
    """Clear stale worktree admin entries (e.g. dirs deleted out-of-band, or a
    leftover lock) so they don't block `worktree add` in subsequent batches.
    Only removes entries whose working tree is already gone — worktrees kept for
    review still have their directories and are untouched. Best-effort."""
    try:
        subprocess.run(
            ["git", "-C", repo, "worktree", "prune"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


def create_worktree(repo: str, worktree_path: str, branch: str, base_ref: str) -> tuple[bool, str]:
    """Create a worktree on a new branch. Returns (ok, message)."""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "worktree", "add", "-b", branch, worktree_path, base_ref],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout).strip()
    except subprocess.TimeoutExpired:
        return False, "git worktree add timed out"
    except OSError as e:
        return False, f"git worktree add failed: {e}"


# -- Spec parsing / validation --

def parse_spec(raw: str) -> tuple[Optional[list], Optional[str]]:
    """Parse and validate the batch spec. Returns (tasks, error_message)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, f"spec is not valid JSON: {e}"

    if not isinstance(data, dict) or "tasks" not in data:
        return None, "spec must be an object with a 'tasks' array"

    tasks_raw = data["tasks"]
    if not isinstance(tasks_raw, list) or not tasks_raw:
        return None, "spec 'tasks' must be a non-empty array"

    tasks = []
    seen_ids = set()
    for i, t in enumerate(tasks_raw):
        if not isinstance(t, dict):
            return None, f"task #{i} is not an object"
        tid = t.get("id")
        if not tid or not isinstance(tid, str) or not ID_RE.match(tid):
            return None, f"task #{i} has missing or invalid 'id' (allowed: letters, digits, _ , -)"
        if tid in seen_ids:
            return None, f"duplicate task id: {tid!r}"
        seen_ids.add(tid)
        prompt = t.get("prompt")
        if not prompt or not isinstance(prompt, str):
            return None, f"task {tid!r} has missing or empty 'prompt'"
        scope = t.get("scope", [])
        if not isinstance(scope, list):
            return None, f"task {tid!r} 'scope' must be an array of globs"
        max_turns = t.get("max_turns", DEFAULT_MAX_TURNS)
        if not isinstance(max_turns, int) or max_turns < 1:
            return None, f"task {tid!r} 'max_turns' must be a positive integer"
        tasks.append(TaskSpec(id=tid, prompt=prompt, scope=scope, max_turns=max_turns))

    return tasks, None


def scope_overlap_warnings(tasks: list) -> list:
    """Flag pairs of tasks whose declared scope globs overlap. Informational only."""
    warnings = []
    for i in range(len(tasks)):
        for j in range(i + 1, len(tasks)):
            a, b = tasks[i], tasks[j]
            if _globs_overlap(a.scope, b.scope):
                warnings.append(
                    f"tasks {a.id!r} and {b.id!r} have overlapping scope globs; "
                    f"worktrees isolate them, but review the merge carefully"
                )
    return warnings


def _globs_overlap(globs_a: list, globs_b: list) -> bool:
    """Heuristic: do any two globs plausibly cover the same paths?"""
    for ga in globs_a:
        for gb in globs_b:
            if ga == gb:
                return True
            if fnmatch.fnmatch(_glob_stem(ga), gb) or fnmatch.fnmatch(_glob_stem(gb), ga):
                return True
    return False


def _glob_stem(glob: str) -> str:
    """Strip trailing wildcard segments so 'src/api/**' -> 'src/api'."""
    return glob.rstrip("*").rstrip("/") or glob


# -- Dispatch --

def dispatch_one(task: TaskSpec, worktree_path: str, branch: str,
                 engine: str, timeout: int) -> DispatchResult:
    cmd = build_dispatch_command(task.prompt, engine, worktree_path, max_turns=task.max_turns)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=worktree_path,
            capture_output=True, text=True, timeout=timeout,
        )
        duration = time.monotonic() - start
        output = (proc.stdout + "\n" + proc.stderr).strip()
        status = "success" if proc.returncode == 0 else "failed"
        if status == "success" and _record_dispatch is not None:
            try:
                # Receipt for the worktree (commits made there) — the merge-back
                # into the base repo is a coordinator git action, not a lifecycle
                # commit, so no base-repo receipt is needed.
                _record_dispatch(worktree_path, engine=engine,
                                 source="parallel_dispatch")
            except Exception:
                pass
        return DispatchResult(
            id=task.id, branch=branch, worktree=worktree_path, status=status,
            returncode=proc.returncode, duration_s=duration,
            output_tail=output[-OUTPUT_TAIL_CHARS:],
        )
    except subprocess.TimeoutExpired:
        return DispatchResult(
            id=task.id, branch=branch, worktree=worktree_path, status="timeout",
            duration_s=time.monotonic() - start,
            error=f"dispatch timed out after {timeout}s",
        )
    except OSError as e:
        return DispatchResult(
            id=task.id, branch=branch, worktree=worktree_path, status="error",
            duration_s=time.monotonic() - start,
            error=f"failed to dispatch: {e}",
        )


def run_batch(repo: str, tasks: list, engine: str, base_ref: str,
              worktree_dir: str, branch_prefix: str,
              max_parallel: int, timeout: int, dry_run: bool) -> BatchReport:
    report = BatchReport(engine=engine, repo=repo, base_ref=base_ref, dry_run=dry_run,
                         total=len(tasks))
    report.warnings = scope_overlap_warnings(tasks)

    wt_root = Path(worktree_dir)
    if not wt_root.is_absolute():
        wt_root = Path(repo) / worktree_dir

    plans = []  # (task, worktree_path, branch)
    for task in tasks:
        worktree_path = str(wt_root / task.id)
        branch = f"{branch_prefix}{task.id}"
        plans.append((task, worktree_path, branch))

    if dry_run:
        for task, worktree_path, branch in plans:
            cmd = build_dispatch_command(task.prompt, engine, worktree_path,
                                         max_turns=task.max_turns)
            report.results.append(DispatchResult(
                id=task.id, branch=branch, worktree=worktree_path, status="dry-run",
                output_tail=cmd,
            ))
        report.succeeded = 0
        report.failed = 0
        return report

    # Startup prune: clear stale worktree admin so leftover/locked dirs from a
    # prior interrupted batch don't block creation here.
    prune_worktrees(repo)

    ready = []  # (task, worktree_path, branch)
    try:
        # 1. Serial worktree creation (git index/refs writes must not race)
        for task, worktree_path, branch in plans:
            ok, msg = create_worktree(repo, worktree_path, branch, base_ref)
            if ok:
                ready.append((task, worktree_path, branch))
            else:
                report.results.append(DispatchResult(
                    id=task.id, branch=branch, worktree=worktree_path, status="error",
                    error=f"worktree creation failed: {msg}",
                ))

        # 2. Concurrent dispatch into the prepared worktrees
        if ready:
            with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
                futures = {
                    pool.submit(dispatch_one, task, wt, br, engine, timeout): task.id
                    for task, wt, br in ready
                }
                for fut in as_completed(futures):
                    report.results.append(fut.result())
    finally:
        # Exit/error prune: tidy admin entries for worktrees that failed to
        # materialize, without touching the populated dirs kept for review.
        prune_worktrees(repo)

    report.results.sort(key=lambda r: r.id)
    report.succeeded = sum(1 for r in report.results if r.status == "success")
    report.failed = len(report.results) - report.succeeded
    return report


# -- Output --

def print_human(report: BatchReport) -> None:
    print(f"Batch: {report.total} task(s) | engine={report.engine} | base={report.base_ref[:12]}")
    if report.dry_run:
        print("(dry run — no worktrees created, no engines invoked)\n")
    for w in report.warnings:
        print(f"  WARNING: {w}")
    if report.warnings:
        print()
    for r in report.results:
        if report.dry_run:
            print(f"  [{r.id}] -> {r.worktree}")
            print(f"      branch: {r.branch}")
            print(f"      cmd:    {r.output_tail}")
        else:
            line = f"  [{r.id}] {r.status} ({r.duration_s:.1f}s) branch={r.branch}"
            if r.error:
                line += f" — {r.error}"
            print(line)
    if not report.dry_run:
        print(f"\n{report.succeeded} succeeded, {report.failed} failed.")
        kept = [r.worktree for r in report.results if r.status != "error"]
        if kept:
            print("Worktrees kept for review (merge sequentially, never auto-merge):")
            for wt in kept:
                print(f"  {wt}   (remove after merge: git worktree remove {wt})")


# -- Main --

def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch independent tasks concurrently in isolated git worktrees")
    parser.add_argument("--repo", required=True, help="Target git repository")
    parser.add_argument("--spec", default="-", help="Batch spec JSON file ('-' = stdin, default)")
    parser.add_argument("--engine", default="claude-code", choices=ENGINES, help="Coding engine harness")
    parser.add_argument("--max-parallel", type=int, default=DEFAULT_MAX_PARALLEL, help="Max concurrent dispatches")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Per-dispatch timeout (seconds)")
    parser.add_argument("--base", default=None, help="Base ref for worktree branches (default: current HEAD)")
    parser.add_argument("--worktree-dir", default=DEFAULT_WORKTREE_DIRNAME, help="Worktree root (rel to repo or absolute)")
    parser.add_argument("--branch-prefix", default=DEFAULT_BRANCH_PREFIX, help="Branch name prefix")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print planned commands; create/dispatch nothing")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    if not is_git_repo(args.repo):
        _fail(f"not a git repository: {args.repo}", args.json)

    # Read spec
    if args.spec == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(args.spec).read_text(encoding="utf-8")
        except OSError as e:
            _fail(f"cannot read spec file: {e}", args.json)

    tasks, err = parse_spec(raw)
    if err:
        _fail(err, args.json)

    base_ref = resolve_base_ref(args.repo, args.base)
    if not base_ref:
        _fail(f"cannot resolve base ref: {args.base or 'HEAD'}", args.json)

    report = run_batch(
        repo=args.repo, tasks=tasks, engine=args.engine, base_ref=base_ref,
        worktree_dir=args.worktree_dir, branch_prefix=args.branch_prefix,
        max_parallel=args.max_parallel, timeout=args.timeout, dry_run=args.dry_run,
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print_human(report)

    sys.exit(0 if report.failed == 0 else 1)


def _fail(message: str, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"status": "error", "error": message}, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
