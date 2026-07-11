#!/usr/bin/env python3
"""Auto-healer: automated fix loop for failed checks.

Parses test/lint/type-check failures, builds escalating fix prompts,
and dispatches them through the active coding engine harness.

Usage:
    python3 auto_healer.py --repo /path/to/project --check "pytest -x" --engine claude-code
    python3 auto_healer.py --repo /path/to/project --check "ruff check" --engine antigravity --json
    python3 auto_healer.py --repo /path/to/project --check "npm test" --engine opencode --max-attempts 2

Exit codes:
    0  All checks passing (healed or already clean)
    1  Escalated (all attempts failed)
    2  Invalid arguments
    3  Check command itself errored (not a test failure — infrastructure problem)
"""

import argparse
import dataclasses
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from harness_llm import resolve_claude_model, resolve_tier_model, sanitize_claude_model
except ImportError:
    def resolve_claude_model() -> str:
        return ""

    def resolve_tier_model(tier) -> str:
        return ""

    def sanitize_claude_model(model: str) -> str:
        return model
try:
    from loop_events import emit as _emit_loop_event
except ImportError:
    _emit_loop_event = None
try:
    from dispatch_receipts import record as _record_dispatch
except ImportError:
    _record_dispatch = None


@dataclass
class FailureTarget:
    file_path: str
    line: Optional[int]
    message: str
    error_type: str  # test, lint, type, build, generic

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class HealAttempt:
    attempt: int
    prompt_summary: str
    output: str
    success: bool

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class HealReport:
    status: str  # healed, escalated, clean
    attempts: list[HealAttempt] = field(default_factory=list)
    remaining_failures: list[FailureTarget] = field(default_factory=list)
    escalation_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "attempts": [a.as_dict() for a in self.attempts],
            "remaining_failures": [f.as_dict() for f in self.remaining_failures],
            "escalation_reason": self.escalation_reason,
        }


# -- Failure parsers --

_PYTEST_FAILED = re.compile(
    r'^FAILED\s+(.+?)::(\S+?)(?:\s+-\s+(.+))?$', re.MULTILINE
)
_PYTEST_ERROR = re.compile(
    r'^E\s+(.+)$', re.MULTILINE
)
_PYTEST_SHORT = re.compile(
    r'^(?:FAILED|ERROR)\s+(.+?)\s+-\s+(.+)$', re.MULTILINE
)

_RUFF_FLAKE8 = re.compile(
    r'^(.+?):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)$', re.MULTILINE
)

_ESLINT = re.compile(
    r'^\s*(\d+):(\d+)\s+(error|warning)\s+(.+?)\s+(\S+)$', re.MULTILINE
)
_ESLINT_FILE = re.compile(
    r'^(/[^\s]+|[A-Z]:\\[^\s]+)$', re.MULTILINE
)

_TSC = re.compile(
    r'^(.+?)\((\d+),(\d+)\):\s+error\s+(TS\d+):\s+(.+)$', re.MULTILINE
)

_GO = re.compile(
    r'^(.+?):(\d+):(?:(\d+):)?\s+(.+)$', re.MULTILINE
)

_GENERIC_ERROR = re.compile(
    r'^.*(?:error|Error|FAIL|FAILED|fatal).*$', re.MULTILINE
)


def parse_failures(output: str) -> list[FailureTarget]:
    """Extract structured failure targets from check output."""
    targets = []
    seen = set()

    def _add(fp, line, msg, etype):
        key = (fp, line, msg[:80])
        if key not in seen:
            seen.add(key)
            targets.append(FailureTarget(fp, line, msg.strip(), etype))

    for m in _PYTEST_FAILED.finditer(output):
        _add(m.group(1), None, f"{m.group(2)}: {m.group(3) or 'failed'}", "test")

    for m in _RUFF_FLAKE8.finditer(output):
        _add(m.group(1), int(m.group(2)), f"{m.group(4)} {m.group(5)}", "lint")

    # eslint: file header lines followed by line:col errors
    current_eslint_file = None
    for line in output.splitlines():
        file_match = _ESLINT_FILE.match(line.strip())
        if file_match:
            current_eslint_file = file_match.group(1)
            continue
        if current_eslint_file:
            em = _ESLINT.match(line)
            if em and em.group(3) == "error":
                _add(current_eslint_file, int(em.group(1)),
                     f"{em.group(5)} {em.group(4)}", "lint")

    for m in _TSC.finditer(output):
        _add(m.group(1), int(m.group(2)), f"{m.group(4)} {m.group(5)}", "type")

    if not targets:
        for m in _GO.finditer(output):
            msg = m.group(4)
            if any(kw in msg.lower() for kw in ("error", "undefined", "cannot", "unused")):
                _add(m.group(1), int(m.group(2)), msg, "build")

    if not targets:
        for m in _GENERIC_ERROR.finditer(output):
            line_text = m.group(0).strip()
            if line_text and len(line_text) < 500:
                _add("unknown", None, line_text, "generic")

    return targets


# -- Check runner --

def run_checks(repo: str, check_cmd: str, timeout: int = 120) -> tuple[bool, str]:
    """Run the check command. Returns (passed, combined_output)."""
    try:
        result = subprocess.run(
            check_cmd,
            shell=True,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        combined = result.stdout + "\n" + result.stderr
        return result.returncode == 0, combined.strip()
    except subprocess.TimeoutExpired:
        return False, f"Check command timed out after {timeout}s: {check_cmd}"
    except OSError as e:
        return False, f"Failed to run check command: {e}"


# -- Prompt builder --

def _format_failures(targets: list[FailureTarget]) -> str:
    lines = []
    for t in targets:
        loc = f"{t.file_path}"
        if t.line:
            loc += f":{t.line}"
        lines.append(f"- [{t.error_type}] {loc}: {t.message}")
    return "\n".join(lines)


def _read_file_context(repo: str, file_path: str, line: Optional[int],
                       context_lines: int = 10) -> Optional[str]:
    """Read a window of lines around the error location."""
    # Linters may emit absolute paths; joining those onto repo would silently
    # resolve to the absolute path (pathlib drops the left operand) and leak a
    # full host path into the prompt. Use the absolute path as-is, join only
    # relative ones, and display a repo-relative path when possible.
    fp = Path(file_path)
    full_path = fp if fp.is_absolute() else Path(repo) / file_path
    if not full_path.is_file():
        return None
    try:
        all_lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if line is None or line < 1:
        return None
    start = max(0, line - context_lines - 1)
    end = min(len(all_lines), line + context_lines)
    numbered = [f"{i + 1:4d} | {all_lines[i]}" for i in range(start, end)]
    try:
        display = str(full_path.relative_to(repo))
    except ValueError:
        display = file_path
    return f"--- {display} (lines {start + 1}-{end}) ---\n" + "\n".join(numbered)


def build_fix_prompt(targets: list[FailureTarget], attempt: int,
                     prior_attempts: list[HealAttempt],
                     repo: str = "") -> str:
    """Build an escalating fix prompt based on attempt number."""
    failure_list = _format_failures(targets)

    if attempt == 1:
        return (
            "Fix ONLY these specific issues. Do NOT refactor or change anything else.\n\n"
            f"{failure_list}\n\n"
            "After fixing, run the check command to verify the fix works."
        )

    if attempt == 2:
        context_blocks = []
        if repo:
            for t in targets[:5]:
                ctx = _read_file_context(repo, t.file_path, t.line)
                if ctx:
                    context_blocks.append(ctx)
        context_str = "\n\n".join(context_blocks) if context_blocks else "(no file context available)"

        prior_output = ""
        if prior_attempts:
            last = prior_attempts[-1]
            prior_output = (
                f"\n\nThe previous fix attempt did not resolve all issues. "
                f"Prior attempt output (truncated):\n{last.output[:2000]}"
            )

        return (
            "Fix these issues. The previous attempt did not fully resolve them.\n\n"
            f"Failures:\n{failure_list}\n\n"
            f"File context around errors:\n{context_str}"
            f"{prior_output}\n\n"
            "Focus on understanding WHY the previous fix didn't work before trying again. "
            "After fixing, run the check command to verify."
        )

    # attempt 3+: simplified, one-file-at-a-time approach
    files = {}
    for t in targets:
        files.setdefault(t.file_path, []).append(t)

    if len(files) == 1:
        fp, file_targets = next(iter(files.items()))
        return (
            f"Focus on this single file: {fp}\n\n"
            f"Remaining failures:\n{_format_failures(file_targets)}\n\n"
            "This is the final attempt. Read the file carefully, understand the root cause, "
            "and make the minimal fix. Run the check command to verify."
        )

    all_prompts = []
    for fp, file_targets in files.items():
        all_prompts.append(
            f"In {fp}, fix:\n{_format_failures(file_targets)}"
        )
    return (
        "Final attempt. Fix each file independently:\n\n"
        + "\n\n".join(all_prompts)
        + "\n\nRun the check command to verify all fixes."
    )


# -- Dispatch command builder --

def build_dispatch_command(prompt: str, engine: str, repo: str,
                           max_turns: int = 10, model: str = "") -> str:
    """Build the CLI command for the active harness."""
    escaped = prompt.replace("'", "'\\''")
    m = sanitize_claude_model(model) or resolve_claude_model()
    model_flag = f" --model {m}" if m else ""

    if engine == "claude-code":
        return (
            f"claude -p '{escaped}' "
            f"--allowedTools 'Read,Edit,Bash' "
            f"--max-turns {max_turns} "
            f"--dangerously-skip-permissions{model_flag}"
        )
    elif engine == "antigravity":
        timeout_go = f"{max(max_turns * 30, 180)}s"
        return (
            f"agy -p '{escaped}' "
            f"--dangerously-skip-permissions "
            f"--print-timeout {timeout_go} "
            f"--add-dir {repo}"
        )
    elif engine == "opencode":
        return (
            f"opencode run '{escaped}' "
            f"--dir {repo} "
            f"--dangerously-skip-permissions "
            f"-m google-vertex/gemini-3.5-flash"
        )
    else:
        # Unknown engine, fall back to claude-code
        return (
            f"claude -p '{escaped}' "
            f"--allowedTools 'Read,Edit,Bash' "
            f"--max-turns {max_turns} "
            f"--dangerously-skip-permissions{model_flag}"
        )


def build_dispatch_argv(prompt: str, engine: str, repo: str,
                        max_turns: int = 10, model: str = "") -> list:
    """List-form (execve) equivalent of build_dispatch_command, for auto_healer's
    own heal loop. Runs with shell=False so the fix prompt — which embeds parsed
    test/lint/build output from the repo under repair — can never be interpreted
    as shell syntax, no manual quote-escaping required.

    parallel_dispatch keeps using the shell-string build_dispatch_command above:
    it composes that string with timeout/worktree/backgrounding wrappers that
    need a shell.
    """
    m = sanitize_claude_model(model) or resolve_claude_model()
    if engine == "antigravity":
        timeout_go = f"{max(max_turns * 30, 180)}s"
        return ["agy", "-p", prompt, "--dangerously-skip-permissions",
                "--print-timeout", timeout_go, "--add-dir", repo]
    if engine == "opencode":
        return ["opencode", "run", prompt, "--dir", repo,
                "--dangerously-skip-permissions", "-m", "google-vertex/gemini-3.5-flash"]
    # claude-code, and fallback for any unknown engine
    argv = ["claude", "-p", prompt, "--allowedTools", "Read,Edit,Bash",
            "--max-turns", str(max_turns), "--dangerously-skip-permissions"]
    if m:
        argv += ["--model", m]
    return argv


# -- Main heal loop --

def heal(repo: str, check_cmd: str, engine: str,
         max_attempts: int = 3, check_timeout: int = 120) -> HealReport:
    """Run the auto-heal loop. Returns a HealReport."""
    # Initial check
    passed, output = run_checks(repo, check_cmd, check_timeout)
    if passed:
        return HealReport(status="clean")

    targets = parse_failures(output)
    if not targets:
        targets = [FailureTarget("unknown", None, output[:500], "generic")]

    attempts = []
    for attempt_num in range(1, max_attempts + 1):
        prompt = build_fix_prompt(targets, attempt_num, attempts, repo)
        # Model ladder: early attempts run the standard tier; the final
        # attempt (last stop before human escalation) bumps to premium.
        tier = "premium" if attempt_num == max_attempts else "standard"
        argv = build_dispatch_argv(prompt, engine, repo,
                                   max_turns=10 + (attempt_num * 5),
                                   model=resolve_tier_model(tier))

        try:
            fix_result = subprocess.run(
                argv,
                cwd=repo,
                capture_output=True,
                text=True,
                timeout=600,
            )
            fix_output = (fix_result.stdout + "\n" + fix_result.stderr).strip()
            if _record_dispatch is not None:
                try:
                    _record_dispatch(repo, engine=engine,
                                     model=resolve_tier_model(tier),
                                     source="auto_healer")
                except Exception:
                    pass
        except subprocess.TimeoutExpired:
            fix_output = "Fix dispatch timed out after 600s"
        except OSError as e:
            fix_output = f"Failed to dispatch fix: {e}"

        passed, check_output = run_checks(repo, check_cmd, check_timeout)
        attempt = HealAttempt(
            attempt=attempt_num,
            prompt_summary=prompt[:200] + ("..." if len(prompt) > 200 else ""),
            output=fix_output[:3000],
            success=passed,
        )
        attempts.append(attempt)

        if passed:
            return HealReport(status="healed", attempts=attempts)

        # Re-parse for next iteration (failures may have changed)
        targets = parse_failures(check_output)
        if not targets:
            targets = [FailureTarget("unknown", None, check_output[:500], "generic")]

    return HealReport(
        status="escalated",
        attempts=attempts,
        remaining_failures=targets,
        escalation_reason=f"All {max_attempts} fix attempts failed. Manual intervention required.",
    )


def generate_escalation_report(report: HealReport) -> str:
    """Format a human-readable escalation summary."""
    lines = [
        f"Auto-Heal Report: {report.status.upper()}",
        f"Attempts: {len(report.attempts)}",
        "",
    ]

    for a in report.attempts:
        lines.append(f"--- Attempt {a.attempt} ---")
        lines.append(f"Prompt: {a.prompt_summary}")
        lines.append(f"Result: {'PASSED' if a.success else 'FAILED'}")
        if not a.success:
            lines.append(f"Output (truncated): {a.output[:500]}")
        lines.append("")

    if report.remaining_failures:
        lines.append("Remaining failures:")
        for f in report.remaining_failures:
            loc = f.file_path
            if f.line:
                loc += f":{f.line}"
            lines.append(f"  [{f.error_type}] {loc}: {f.message}")
        lines.append("")

    if report.escalation_reason:
        lines.append(f"Escalation: {report.escalation_reason}")

    return "\n".join(lines)


# -- CLI --

def main():
    parser = argparse.ArgumentParser(description="Auto-heal failed checks")
    parser.add_argument("--repo", required=True, help="Project repository path (local filesystem path, NOT a gh owner/repo slug)")
    parser.add_argument("--check", required=True, help="Check command to run (e.g., 'pytest -x')")
    parser.add_argument("--engine", required=True,
                        choices=["claude-code", "antigravity", "opencode"],
                        help="Active coding engine harness")
    parser.add_argument("--max-attempts", type=int, default=3,
                        help="Maximum fix attempts before escalating (default: 3)")
    parser.add_argument("--check-timeout", type=int, default=120,
                        help="Timeout for check command in seconds (default: 120)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    from repo_paths import resolve_repo_path
    repo = resolve_repo_path(args.repo)
    if not repo:
        print(f"Error: repository path does not exist: {args.repo}", file=sys.stderr)
        sys.exit(2)

    report = heal(
        repo=repo,
        check_cmd=args.check,
        engine=args.engine,
        max_attempts=args.max_attempts,
        check_timeout=args.check_timeout,
    )

    # Durable outcome trail for loop_health.py (reports otherwise only reach
    # stdout). Best-effort.
    if _emit_loop_event is not None:
        try:
            _emit_loop_event(
                "heal", repo=str(repo), status=report.status,
                attempts=len(report.attempts), engine=args.engine,
                check=args.check[:80])
        except Exception:
            pass

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        if report.status == "clean":
            print("All checks passing. Nothing to heal.")
        elif report.status == "healed":
            print(f"Healed after {len(report.attempts)} attempt(s).")
        else:
            print(generate_escalation_report(report))

    exit_codes = {"clean": 0, "healed": 0, "escalated": 1}
    sys.exit(exit_codes.get(report.status, 1))


if __name__ == "__main__":
    main()
