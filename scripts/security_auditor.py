#!/usr/bin/env python3
"""Security auditor: static + LLM code audit -> FAIL | WARN | PASS (Backlog #6, Phase 4).

The first guard in the dynamic skill/tool ingestion pipeline. It reviews a source
tree for dangerous patterns WITHOUT EVER EXECUTING IT. Two phases:

  Phase A -- static regex scan (deterministic). Carries the blocking weight: any
             FAIL-category match makes the aggregate verdict FAIL.
  Phase B -- LLM rubric pass (advisory/corroborating), run through the active
             coding harness. It only escalates, never overrides a clean static
             pass into PASS. If the harness is unavailable, Phase B is skipped
             and the static-only verdict still gates (exit 3).

Aggregate verdict: any FAIL (static or LLM) -> FAIL; else any WARN -> WARN; else PASS.

This auditor is import-safe: `from security_auditor import audit_source` runs no I/O.

Usage:
    python3 security_auditor.py --source <path> [--static-only] [--model <m>]
                                [--max-llm-files <n>] [--json]

Exit codes:
    0  PASS or WARN (non-blocking; check the `verdict` field, not just the code)
    1  FAIL (blocked)
    2  Invalid arguments / source not found
    3  LLM harness unavailable during the LLM pass (static-only verdict still provided)
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from harness_llm import (  # noqa: E402
    harness_generate, strip_fences, resolve_engine, HarnessUnavailable,
)


DEFAULT_MAX_LLM_FILES = 12
MAX_LLM_FILE_CHARS = 6000
OUTPUT_TAIL = 4000

AUDITED_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".sh", ".bash", ".zsh", ".rb", ".go", ".json", ".yaml", ".yml",
}
IGNORE_NAMES = {".git", "__pycache__", ".DS_Store", "node_modules", ".hermes-worktrees"}

VERDICT_FAIL = "FAIL"
VERDICT_WARN = "WARN"
VERDICT_PASS = "PASS"


# -- Static rule set --
# Each entry: (category, severity, compiled regex). Severity FAIL hard-blocks;
# WARN is advisory. Patterns are intentionally conservative -- a false WARN costs
# a human glance; a missed FAIL ships malware.

_RULES: list[tuple[str, str, "re.Pattern"]] = [
    # --- Code execution (FAIL) ---
    ("code-exec", VERDICT_FAIL, re.compile(r"\beval\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\bexec\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\bos\.system\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\bos\.popen\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\bpickle\.loads?\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\b__import__\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"\bnew\s+Function\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"child_process\.(exec|execSync)\s*\(")),
    ("code-exec", VERDICT_FAIL, re.compile(r"`[^`]*\$\([^`]*`")),  # shell backtick cmd-subst
    # --- Obfuscation (FAIL) ---
    ("obfuscation", VERDICT_FAIL, re.compile(r"base64\.b64decode\s*\([^)]*\)\s*\)?\s*$", re.MULTILINE)),
    ("obfuscation", VERDICT_FAIL, re.compile(r"(?:eval|exec)\s*\(\s*base64\.b64decode")),
    ("obfuscation", VERDICT_FAIL, re.compile(r"(?:eval|exec)\s*\(\s*atob\s*\(")),
    ("obfuscation", VERDICT_FAIL, re.compile(r"['\"][A-Za-z0-9+/]{120,}={0,2}['\"]")),  # long opaque b64
    ("obfuscation", VERDICT_FAIL, re.compile(r"['\"](?:[0-9a-fA-F]{2}){60,}['\"]")),     # long opaque hex
    # --- Sensitive-path / credential access (FAIL) ---
    ("sensitive-path", VERDICT_FAIL, re.compile(r"\.aws[/\\]credentials")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"~?/?\.aws\b")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"~?/?\.ssh\b")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"\bid_rsa\b")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"\.netrc\b")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"~?/?\.config/gh\b")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"Keychain|security\s+find-generic-password")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"Login\s?Data|Cookies\.sqlite|cookies\.sqlite")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"os\.environ(?:\.get)?\s*[\(\[][^)\]]*(?:_TOKEN|_KEY|_SECRET|PASSWORD)")),
    ("sensitive-path", VERDICT_FAIL, re.compile(r"process\.env\.[A-Za-z_]*(?:TOKEN|KEY|SECRET|PASSWORD)")),
    # --- Network egress (WARN) ---
    ("network-egress", VERDICT_WARN, re.compile(r"requests\.(post|put|patch)\s*\(")),
    ("network-egress", VERDICT_WARN, re.compile(r"urllib\.request\.(urlopen|Request)\s*\(")),
    ("network-egress", VERDICT_WARN, re.compile(r"\bsocket\.socket\s*\(")),
    ("network-egress", VERDICT_WARN, re.compile(r"\bfetch\s*\(")),
    ("network-egress", VERDICT_WARN, re.compile(r"https?://[^\s'\"]+")),
    ("network-egress", VERDICT_WARN, re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),  # hardcoded IP
    ("network-egress", VERDICT_WARN, re.compile(r"\b(curl|wget|nc|ncat)\b")),
]


LLM_SYSTEM_PROMPT = """You are a strict security code auditor reviewing a third-party \
skill/tool before it is allowed into a coding agent. You do NOT execute the code; \
you only read it. Flag anything that could exfiltrate secrets, execute arbitrary \
or obfuscated code, read credential/SSH/cloud-config files, or make hidden network \
calls. Be conservative: when unsure, escalate.

Respond with ONLY a JSON object, no prose, no markdown fences:
{"verdict": "FAIL|WARN|PASS", "findings": [{"category": "...", "severity": "FAIL|WARN", "note": "...", "file": "..."}]}

Use FAIL for clear malicious/dangerous behavior, WARN for suspicious-but-plausible, \
PASS for clean code."""


@dataclass
class AuditFinding:
    file: str
    line: int
    severity: str
    category: str
    snippet: str

    def as_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "severity": self.severity,
            "category": self.category,
            "snippet": self.snippet,
        }


@dataclass
class AuditReport:
    source: str
    verdict: str
    static_findings: list = field(default_factory=list)
    llm_findings: list = field(default_factory=list)
    llm_used: bool = False
    model: str = ""

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "verdict": self.verdict,
            "static_findings": [f.as_dict() for f in self.static_findings],
            "llm_findings": self.llm_findings,
            "llm_used": self.llm_used,
            "model": self.model,
        }


# -- File discovery --

def _iter_source_files(source: Path):
    if source.is_file():
        if source.suffix.lower() in AUDITED_EXTENSIONS:
            yield source
        return
    for p in sorted(source.rglob("*")):
        if not p.is_file():
            continue
        if any(part in IGNORE_NAMES for part in p.relative_to(source).parts):
            continue
        if p.suffix.lower() in AUDITED_EXTENSIONS:
            yield p


def _rel(source: Path, p: Path) -> str:
    try:
        return str(p.relative_to(source)) if source.is_dir() else p.name
    except ValueError:
        return str(p)


# -- Phase A: static --

def static_scan(source: Path) -> list:
    findings: list = []
    for fp in _iter_source_files(source):
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = _rel(source, fp)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for category, severity, pattern in _RULES:
                if pattern.search(line):
                    snippet = line.strip()
                    if len(snippet) > 200:
                        snippet = snippet[:197] + "..."
                    findings.append(AuditFinding(rel, lineno, severity, category, snippet))
    return findings


# -- Phase B: LLM (advisory) --

def llm_scan(source: Path, engine: Optional[str], max_files: int) -> Optional[list]:
    """Send source excerpts to the active coding harness. Returns findings
    list, or raises HarnessUnavailable if the harness can't be reached."""
    files = list(_iter_source_files(source))[:max_files]
    if not files:
        return []

    parts = []
    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > MAX_LLM_FILE_CHARS:
            text = text[:MAX_LLM_FILE_CHARS] + "\n... (truncated)"
        parts.append(f"=== FILE: {_rel(source, fp)} ===\n{text}")

    payload = "\n\n".join(parts)
    raw = harness_generate(
        payload, engine=engine, system=LLM_SYSTEM_PROMPT, timeout=180,
        tier="premium",
    )
    content = strip_fences(raw)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Model returned unparseable output -> treat as a single advisory WARN.
        return [{"category": "llm-unparseable", "severity": VERDICT_WARN,
                 "note": "LLM response was not valid JSON; manual review advised",
                 "file": ""}]
    findings = parsed.get("findings", [])
    verdict = str(parsed.get("verdict", "")).upper()
    if verdict in (VERDICT_FAIL, VERDICT_WARN) and not findings:
        findings = [{"category": "llm-verdict", "severity": verdict,
                     "note": f"LLM returned overall verdict {verdict} without itemized findings",
                     "file": ""}]
    return findings


# -- Aggregation --

def _aggregate(static_findings: list, llm_findings: list) -> str:
    for f in static_findings:
        if f.severity == VERDICT_FAIL:
            return VERDICT_FAIL
    for f in llm_findings:
        if str(f.get("severity", "")).upper() == VERDICT_FAIL:
            return VERDICT_FAIL
    if any(f.severity == VERDICT_WARN for f in static_findings):
        return VERDICT_WARN
    if any(str(f.get("severity", "")).upper() == VERDICT_WARN for f in llm_findings):
        return VERDICT_WARN
    return VERDICT_PASS


def audit_source(source: Path, static_only: bool = False,
                 model: Optional[str] = None,
                 max_llm_files: int = DEFAULT_MAX_LLM_FILES,
                 engine: Optional[str] = None) -> tuple:
    """Run the audit. Returns (AuditReport, harness_down: bool).

    The LLM pass runs through the active coding harness (`engine`), not a local
    model; `model` is accepted for backward compatibility and ignored. The
    second tuple element is True only when the LLM pass was requested but the
    harness was unreachable -- callers map that to exit code 3 while still
    using the report.
    """
    static_findings = static_scan(source)
    llm_findings: list = []
    llm_used = False
    harness_down = False

    if not static_only:
        try:
            result = llm_scan(source, engine, max_llm_files)
            llm_findings = result or []
            llm_used = True
        except HarnessUnavailable:
            harness_down = True

    verdict = _aggregate(static_findings, llm_findings)
    report = AuditReport(
        source=str(source), verdict=verdict,
        static_findings=static_findings, llm_findings=llm_findings,
        llm_used=llm_used, model=resolve_engine(engine) if llm_used else "",
    )
    return report, harness_down


# -- CLI --

def _print_human(report: AuditReport, harness_down: bool) -> None:
    print(f"VERDICT: {report.verdict}  <-  {report.source}")
    if report.static_findings:
        print(f"\nStatic findings ({len(report.static_findings)}):")
        for f in report.static_findings:
            print(f"  [{f.severity}] {f.category} {f.file}:{f.line}  {f.snippet}")
    else:
        print("\nStatic findings: none")
    if report.llm_used:
        if report.llm_findings:
            print(f"\nLLM findings ({len(report.llm_findings)}):")
            for f in report.llm_findings:
                print(f"  [{f.get('severity', '?')}] {f.get('category', '?')} "
                      f"{f.get('file', '')}  {f.get('note', '')}")
        else:
            print("\nLLM findings: none")
    elif harness_down:
        print("\nLLM pass: SKIPPED (LLM harness unavailable) -- static-only verdict")
    else:
        print("\nLLM pass: skipped (--static-only)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Static + LLM security auditor (never executes the source)")
    parser.add_argument("--source", required=True, help="Path to the source file or directory to audit")
    parser.add_argument("--static-only", action="store_true", help="Skip the LLM pass")
    parser.add_argument("--engine", default=None,
                        choices=["claude-code", "antigravity", "opencode"],
                        help="Coding harness for the LLM pass (default: config coding.default_engine)")
    parser.add_argument("--model", default=None,
                        help="Deprecated/ignored; the LLM pass uses the coding harness")
    parser.add_argument("--max-llm-files", type=int, default=DEFAULT_MAX_LLM_FILES,
                        help="Max number of files to send to the LLM pass")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.exists():
        msg = {"status": "error", "error": f"source not found: {args.source}"}
        print(json.dumps(msg, indent=2) if args.json else f"ERROR: {msg['error']}",
              file=None if args.json else sys.stderr)
        sys.exit(2)

    report, harness_down = audit_source(
        source, static_only=args.static_only,
        engine=args.engine, max_llm_files=args.max_llm_files,
    )

    if args.json:
        out = report.as_dict()
        out["harness_down"] = harness_down
        print(json.dumps(out, indent=2))
    else:
        _print_human(report, harness_down)

    if report.verdict == VERDICT_FAIL:
        sys.exit(1)
    if harness_down:
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
