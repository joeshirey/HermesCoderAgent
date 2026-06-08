#!/usr/bin/env python3
"""Retrospective memory loop: capture lessons from struggles, inject them later.

After a task required multiple auto-heal retries or a full systematic-debugger
session, the root cause and lesson learned would otherwise evaporate (the coding
engine has no memory between dispatches). This tool captures a concise lesson and
stores it per-repo, then injects the relevant prior lessons into future dispatches.

Subcommands:
    capture  Extract + store a lesson from an auto-heal report, a debug journal,
             or a final-review report.
    inject   Match stored lessons against a new task and emit a prompt snippet.
    list     Show the lessons stored for a repo.

Usage:
    # capture from a debug journal (.hermes-debug/<bug-id>.json):
    python3 retrospective.py capture --source debug --bug-id abc123 --repo /path --engine claude-code

    # capture from an auto-heal report (JSON via stdin):
    python3 auto_healer.py ... --json | \
        python3 retrospective.py capture --source heal --repo /path --task "fix flaky auth test"

    # inject relevant lessons before a new dispatch:
    python3 retrospective.py inject --repo /path --task "auth token refresh bug" --json

    # inspect stored lessons:
    python3 retrospective.py list --repo /path --json

Exit codes:
    0  Success (lesson captured via LLM / inject emitted / list ok)
    1  Nothing notable to capture (no struggle)
    2  Invalid arguments / missing source / journal not found
    3  LLM harness unavailable -- rules-only lesson still stored
"""

import argparse
import dataclasses
import hashlib
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from harness_llm import harness_generate, strip_fences, HarnessUnavailable


# -- Config defaults (overridable via ~/.hermes-coder/config.yaml) --

DEFAULT_MAX_INJECT = 3
DEFAULT_MATCH_THRESHOLD = 0.05
STORE_DIRNAME = ".hermes-lessons"
DEBUG_DIRNAME = ".hermes-debug"

# Small stopword set so generic verbs don't inflate keyword overlap.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
    "with", "is", "are", "was", "were", "be", "been", "it", "this", "that",
    "fix", "bug", "error", "issue", "test", "tests", "code", "file", "files",
    "add", "update", "change", "make", "use", "run", "when", "from", "into",
    "by", "as", "at", "if", "not", "no", "all", "any", "via", "out",
}


# -- Lesson model --

@dataclass
class Lesson:
    lesson_id: str
    created: str
    repo: str
    engine: str
    trigger: str  # heal-escalated | heal-retried | debug-fix | debug-escalated
    task: str
    root_cause: str
    lesson: str
    tags: list[str] = field(default_factory=list)
    source_ref: str = ""
    dedupe_key: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    def save(self) -> Path:
        store = _store_dir(self.repo)
        store.mkdir(parents=True, exist_ok=True)
        path = store / f"{self.lesson_id}.json"
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path


def _store_dir(repo: str) -> Path:
    return Path(repo) / STORE_DIRNAME


def load_lessons(repo: str) -> list[Lesson]:
    store = _store_dir(repo)
    if not store.exists():
        return []
    lessons = []
    for f in sorted(store.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            lessons.append(Lesson(
                lesson_id=data["lesson_id"],
                created=data.get("created", ""),
                repo=data.get("repo", repo),
                engine=data.get("engine", ""),
                trigger=data.get("trigger", ""),
                task=data.get("task", ""),
                root_cause=data.get("root_cause", ""),
                lesson=data.get("lesson", ""),
                tags=data.get("tags", []),
                source_ref=data.get("source_ref", ""),
                dedupe_key=data.get("dedupe_key", ""),
            ))
        except (json.JSONDecodeError, KeyError, OSError):
            continue
    return lessons


def _dedupe_key(trigger: str, source_ref: str) -> str:
    # Key on the deterministic source (bug-id / heal signature) so re-capturing
    # the same struggle is idempotent. LLM-summarized root causes vary per run,
    # so they cannot anchor dedup.
    raw = f"{trigger}::{source_ref}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _extract_tags(task: str, root_cause: str) -> list[str]:
    words = set(re.findall(r'[a-z]+', f"{task} {root_cause}".lower()))
    words = {w for w in words if len(w) >= 3 and w not in _STOPWORDS}
    return sorted(words)


# -- LLM summarization (with rules-only fallback) --

_SUMMARY_SYSTEM_PROMPT = """You analyze software debugging records and distill a single reusable lesson.
Given the raw evidence of a fix that required effort, output STRICT JSON only, no markdown fencing:
{"root_cause": "one sentence: what was actually wrong", "lesson": "one actionable sentence: what to do or check next time to avoid this"}
Be concrete and specific to the code involved. Do not restate the task description."""


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r'^```\w*\n?', '', content)
        content = re.sub(r'\n?```$', '', content)
    return content.strip()


def _llm_summarize(evidence: str, engine: Optional[str]) -> Optional[dict]:
    """Return {"root_cause","lesson"} via the active coding harness, or None
    if the harness is unreachable / the response is unparseable."""
    try:
        raw = harness_generate(
            evidence, engine=engine, system=_SUMMARY_SYSTEM_PROMPT, timeout=120
        )
    except HarnessUnavailable:
        return None
    content = strip_fences(raw)
    try:
        parsed = json.loads(content)
        root_cause = str(parsed.get("root_cause", "")).strip()
        lesson = str(parsed.get("lesson", "")).strip()
        if root_cause or lesson:
            return {"root_cause": root_cause, "lesson": lesson}
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


# -- Capture: debug journal source --

def _capture_from_debug(repo: str, bug_id: str,
                        engine: str) -> tuple[Optional[Lesson], int, str]:
    """Returns (lesson_or_none, exit_code, message)."""
    journal_path = Path(repo) / DEBUG_DIRNAME / f"{bug_id}.json"
    if not journal_path.exists():
        return None, 2, f"No debug journal found for bug ID: {bug_id}"

    try:
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, 2, f"Could not read debug journal: {e}"

    description = data.get("description", "")
    phases = data.get("phases", {})
    trace = phases.get("trace", {})
    fix = phases.get("fix", {})
    heal_report = fix.get("heal_report", {}) if isinstance(fix, dict) else {}

    root_cause_file = trace.get("root_cause_file", "")
    root_cause_line = trace.get("root_cause_line")
    data_flow = trace.get("data_flow", "")

    # Require at least a traced root cause to be worth a lesson.
    if not (root_cause_file or data_flow):
        return None, 1, "Debug journal has no traced root cause; nothing notable to capture"

    fix_passed = fix.get("status") == "passed"
    trigger = "debug-fix" if fix_passed else "debug-escalated"

    loc = root_cause_file + (f":{root_cause_line}" if root_cause_line else "")
    evidence_parts = [
        f"Bug: {description}",
        f"Root cause location: {loc}" if loc else "",
        f"Data flow: {data_flow}" if data_flow else "",
        f"Fix outcome: {'fixed' if fix_passed else 'escalated (auto-healer exhausted retries)'}",
        f"Fix detail: {fix.get('fix_description') or fix.get('error', '')}",
    ]
    if heal_report:
        evidence_parts.append(
            f"Auto-heal status: {heal_report.get('status', '')}; "
            f"attempts: {len(heal_report.get('attempts', []))}; "
            f"escalation: {heal_report.get('escalation_reason', '')}"
        )
    evidence = "\n".join(p for p in evidence_parts if p)

    summary = _llm_summarize(evidence, engine)
    exit_code = 0
    if summary is None:
        # Rules-only fallback
        rc = f"{loc}: {data_flow}".strip(": ").strip() if (loc or data_flow) else description
        lesson_text = (
            f"Check {loc} when working on similar behavior; "
            f"the root cause traced to: {data_flow or 'see debug journal'}."
        ) if not fix_passed else (
            f"Previously fixed here: {loc or 'see debug journal'}. "
            f"Re-verify this path when touching related code."
        )
        summary = {"root_cause": rc or description, "lesson": lesson_text}
        exit_code = 3

    return _build_lesson(
        repo, engine, trigger, description, summary, source_ref=bug_id
    ), exit_code, ""


# -- Capture: auto-heal report source --

def _read_heal_json(heal_file: Optional[str]) -> tuple[Optional[dict], str]:
    """Read a HealReport JSON from a file path ('-' or None = stdin)."""
    try:
        if not heal_file or heal_file == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(heal_file).read_text(encoding="utf-8")
    except OSError as e:
        return None, f"Could not read heal report: {e}"
    raw = raw.strip()
    if not raw:
        return None, "Empty heal report input"
    try:
        return json.loads(raw), ""
    except json.JSONDecodeError as e:
        return None, f"Heal report is not valid JSON: {e}"


def _capture_from_heal(repo: str, heal_file: Optional[str], task: str,
                       engine: str) -> tuple[Optional[Lesson], int, str]:
    report, err = _read_heal_json(heal_file)
    if report is None:
        return None, 2, err

    status = report.get("status", "")
    attempts = report.get("attempts", [])
    remaining = report.get("remaining_failures", [])
    escalation = report.get("escalation_reason", "")

    # Gate: only struggles are worth a lesson.
    if status == "escalated":
        trigger = "heal-escalated"
    elif status in ("healed", "clean") and len(attempts) > 1:
        trigger = "heal-retried"
    else:
        return None, 1, "Clean or single-attempt heal; nothing notable to capture"

    failure_lines = []
    for f in remaining[:5]:
        loc = f.get("file_path", "unknown")
        if f.get("line"):
            loc += f":{f['line']}"
        failure_lines.append(f"- [{f.get('error_type', '?')}] {loc}: {f.get('message', '')}")

    last_output = ""
    if attempts:
        last_output = (attempts[-1].get("output", "") or "")[:1500]

    evidence_parts = [
        f"Task: {task}",
        f"Auto-heal status: {status} after {len(attempts)} attempt(s)",
        f"Escalation reason: {escalation}" if escalation else "",
        ("Remaining failures:\n" + "\n".join(failure_lines)) if failure_lines else "",
        f"Last fix-attempt output (truncated):\n{last_output}" if last_output else "",
    ]
    evidence = "\n".join(p for p in evidence_parts if p)

    summary = _llm_summarize(evidence, engine)
    exit_code = 0
    if summary is None:
        rc = escalation or (failure_lines[0] if failure_lines else f"Auto-heal {status} for: {task}")
        if trigger == "heal-escalated":
            lesson_text = (
                "This class of failure resisted automated fixing -- needs a careful manual "
                "root-cause pass before dispatching again. "
                + (f"Remaining: {failure_lines[0]}" if failure_lines else "")
            ).strip()
        else:
            lesson_text = (
                f"Fixable but took {len(attempts)} attempts; the first obvious fix did not work. "
                "Read the affected file fully before editing next time."
            )
        summary = {"root_cause": rc, "lesson": lesson_text}
        exit_code = 3

    sig = hashlib.sha256(f"{status}{escalation}{task}".encode("utf-8")).hexdigest()[:8]
    return _build_lesson(
        repo, engine, trigger, task, summary, source_ref=f"heal-{sig}"
    ), exit_code, ""


# -- Capture: final-review report source --

def _capture_from_review(repo: str, review_file: Optional[str], task: str,
                         engine: str) -> tuple[Optional[Lesson], int, str]:
    """Capture a lesson from a final_review.py report (JSON via file/stdin).

    The evidence is the review verdict, the targeted fixes the review agent made
    (changes: what/why), and any residual risks it flagged. A clean pass with no
    fixes and no residual risks is not notable and is skipped."""
    try:
        if not review_file or review_file == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(review_file).read_text(encoding="utf-8")
    except OSError as e:
        return None, 2, f"Could not read review report: {e}"
    raw = raw.strip()
    if not raw:
        return None, 2, "Empty review report input"
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, 2, f"Review report is not valid JSON: {e}"

    verdict = str(report.get("verdict", "")).strip().lower()
    changes = report.get("changes") or []
    residual = report.get("residual_risks") or []
    report_task = task or report.get("task", "") or "final review"

    # Gate: a clean pass with nothing fixed and nothing flagged is not worth a lesson.
    if verdict == "pass" and not changes and not residual:
        return None, 1, "Clean final review; nothing notable to capture"

    if verdict == "blocked":
        trigger = "review-blocked"
    elif changes:
        trigger = "review-fixed"
    else:
        trigger = "review-flagged"

    change_lines = []
    for c in changes[:8]:
        if isinstance(c, dict):
            what = str(c.get("what", "")).strip()
            why = str(c.get("why", "")).strip()
            change_lines.append(f"- {what}" + (f" (why: {why})" if why else ""))
        else:
            change_lines.append(f"- {str(c).strip()}")
    risk_lines = [f"- {str(r).strip()}" for r in residual[:8]]

    evidence_parts = [
        f"Task: {report_task}",
        f"Final-review verdict: {verdict or 'unknown'}",
        ("Fixes the reviewer made:\n" + "\n".join(change_lines)) if change_lines else "",
        ("Residual risks flagged:\n" + "\n".join(risk_lines)) if risk_lines else "",
    ]
    evidence = "\n".join(p for p in evidence_parts if p)

    summary = _llm_summarize(evidence, engine)
    exit_code = 0
    if summary is None:
        if trigger == "review-blocked":
            rc = risk_lines[0][2:] if risk_lines else f"Final review blocked: {report_task}"
            lesson_text = (
                "The final-review gate blocked delivery -- a blocking defect slipped past "
                "the per-task review. Re-check this class of issue before shipping next time."
            )
        elif trigger == "review-fixed":
            rc = change_lines[0][2:] if change_lines else f"Final review made fixes: {report_task}"
            lesson_text = (
                "The final-review gate had to fix issues the per-task review missed; "
                "watch for this pattern earlier in the next dispatch."
            )
        else:
            rc = risk_lines[0][2:] if risk_lines else f"Final review flagged risks: {report_task}"
            lesson_text = (
                "The final-review gate flagged residual risks even though it passed; "
                "consider addressing these proactively in similar work."
            )
        summary = {"root_cause": rc, "lesson": lesson_text}
        exit_code = 3

    sig = hashlib.sha256(
        (verdict + "".join(change_lines) + "".join(risk_lines) + report_task).encode("utf-8")
    ).hexdigest()[:8]
    return _build_lesson(
        repo, engine, trigger, report_task, summary, source_ref=f"review-{sig}"
    ), exit_code, ""


def _build_lesson(repo: str, engine: str, trigger: str, task: str,
                  summary: dict, source_ref: str) -> Lesson:
    root_cause = summary.get("root_cause", "")
    lesson_text = summary.get("lesson", "")
    return Lesson(
        lesson_id=str(uuid.uuid4())[:8],
        created=datetime.now(timezone.utc).isoformat(),
        repo=repo,
        engine=engine,
        trigger=trigger,
        task=task,
        root_cause=root_cause,
        lesson=lesson_text,
        tags=_extract_tags(task, root_cause),
        source_ref=source_ref,
        dedupe_key=_dedupe_key(trigger, source_ref),
    )


def _store_with_dedup(lesson: Lesson) -> tuple[str, bool]:
    """Save unless a lesson with the same dedupe_key exists. Returns (id, stored)."""
    for existing in load_lessons(lesson.repo):
        if existing.dedupe_key and existing.dedupe_key == lesson.dedupe_key:
            return existing.lesson_id, False
    lesson.save()
    return lesson.lesson_id, True


# -- Inject: keyword matching --

def match_lessons(repo: str, task: str, max_inject: int,
                  threshold: float) -> list[dict]:
    task_words = set(re.findall(r'[a-z]+', task.lower()))
    task_words = {w for w in task_words if len(w) >= 3 and w not in _STOPWORDS}
    if not task_words:
        return []

    scored = []
    for lesson in load_lessons(repo):
        lesson_words = set(lesson.tags)
        overlap = task_words & lesson_words
        if not overlap:
            continue
        score = len(overlap) / max(len(task_words), 1)
        if score >= threshold:
            scored.append({
                "lesson_id": lesson.lesson_id,
                "trigger": lesson.trigger,
                "task": lesson.task,
                "root_cause": lesson.root_cause,
                "lesson": lesson.lesson,
                "score": round(score, 3),
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:max_inject]


def build_snippet(matches: list[dict]) -> str:
    if not matches:
        return ""
    lines = ["## Lessons from prior work in this repo"]
    for m in matches:
        rc = f" (root cause: {m['root_cause']})" if m.get("root_cause") else ""
        lines.append(f"- [{m['trigger']}] {m['lesson']}{rc}")
    return "\n".join(lines)


# -- CLI handlers --

def cmd_capture(args) -> int:
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        _emit_error(args, f"Repository path does not exist: {repo}")
        return 2

    if args.source == "debug":
        if not args.bug_id:
            _emit_error(args, "--bug-id is required for --source debug")
            return 2
        lesson, code, msg = _capture_from_debug(repo, args.bug_id, args.engine)
    elif args.source == "review":
        lesson, code, msg = _capture_from_review(repo, args.review_file, args.task, args.engine)
    else:  # heal
        if not args.task:
            _emit_error(args, "--task is required for --source heal")
            return 2
        lesson, code, msg = _capture_from_heal(repo, args.heal_file, args.task, args.engine)

    if lesson is None:
        # code is 1 (nothing notable) or 2 (invalid/missing)
        if args.json:
            print(json.dumps({"status": "skipped", "reason": msg}, indent=2))
        else:
            print(msg)
        return code

    lesson_id, stored = _store_with_dedup(lesson)
    result = {
        "status": "captured" if stored else "duplicate",
        "lesson_id": lesson_id,
        "trigger": lesson.trigger,
        "root_cause": lesson.root_cause,
        "lesson": lesson.lesson,
        "tags": lesson.tags,
        "via": "rules" if code == 3 else "llm",
        "stored": stored,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if stored:
            print(f"Captured lesson {lesson_id} [{lesson.trigger}] (via {result['via']})")
            print(f"  Root cause: {lesson.root_cause}")
            print(f"  Lesson: {lesson.lesson}")
        else:
            print(f"Duplicate of existing lesson {lesson_id}; not stored.")
    return code


def cmd_inject(args) -> int:
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        _emit_error(args, f"Repository path does not exist: {repo}")
        return 2
    if not args.task:
        _emit_error(args, "--task is required")
        return 2

    matches = match_lessons(repo, args.task, args.max, args.threshold)
    snippet = build_snippet(matches)

    if args.json:
        print(json.dumps({"lessons": matches, "snippet": snippet}, indent=2))
    else:
        print(snippet)
    return 0


def cmd_list(args) -> int:
    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        _emit_error(args, f"Repository path does not exist: {repo}")
        return 2

    lessons = load_lessons(repo)
    if args.json:
        print(json.dumps([l.as_dict() for l in lessons], indent=2))
    else:
        if not lessons:
            print("No lessons stored for this repo.")
        for l in lessons:
            print(f"{l.lesson_id}  {l.created}  [{l.trigger}]")
            print(f"    task: {l.task}")
            print(f"    lesson: {l.lesson}")
            print(f"    tags: {', '.join(l.tags)}")
    return 0


def _emit_error(args, msg: str):
    if getattr(args, "json", False):
        print(json.dumps({"status": "error", "error": msg}, indent=2))
    else:
        print(f"Error: {msg}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Retrospective memory loop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cap = sub.add_parser("capture", help="Capture a lesson from a heal report or debug journal")
    p_cap.add_argument("--repo", required=True)
    p_cap.add_argument("--source", required=True, choices=["heal", "debug", "review"])
    p_cap.add_argument("--bug-id", help="Debug journal bug ID (for --source debug)")
    p_cap.add_argument("--heal-file", help="HealReport JSON path; '-' or omit = stdin (for --source heal)")
    p_cap.add_argument("--review-file", help="final_review report JSON path; '-' or omit = stdin (for --source review)")
    p_cap.add_argument("--task", help="Task description (required for --source heal)")
    p_cap.add_argument("--engine", default="", choices=["", "claude-code", "antigravity", "opencode"],
                       help="Coding harness for the LLM summary (default: config coding.default_engine)")
    p_cap.add_argument("--model", default=None,
                       help="Deprecated/ignored; the LLM summary uses the coding harness")
    p_cap.add_argument("--json", action="store_true")
    p_cap.set_defaults(func=cmd_capture)

    p_inj = sub.add_parser("inject", help="Match stored lessons against a task and emit a snippet")
    p_inj.add_argument("--repo", required=True)
    p_inj.add_argument("--task", required=True)
    p_inj.add_argument("--max", type=int, default=DEFAULT_MAX_INJECT)
    p_inj.add_argument("--threshold", type=float, default=DEFAULT_MATCH_THRESHOLD)
    p_inj.add_argument("--json", action="store_true")
    p_inj.set_defaults(func=cmd_inject)

    p_list = sub.add_parser("list", help="List stored lessons for a repo")
    p_list.add_argument("--repo", required=True)
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
