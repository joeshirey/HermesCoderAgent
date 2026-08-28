#!/usr/bin/env python3
"""Skill ingest: the end-to-end dynamic skill/tool ingestion pipeline (Backlog #6, Phase 4).

This is the "door" that makes the security guards load-bearing. It is the only
sanctioned way a third-party skill or MCP server enters the vault:

    fetch -> quarantine -> classify tier -> security audit
        FAIL  -> hard block (nothing vaulted)
        PASS/WARN -> vault (immutable lock-in copy)  [Tier 2/3 require --confirm]

Nothing fetched is ever executed during ingestion -- the auditor is static + LLM
only, and execution happens later through container_runner.py (sandboxed).

Usage:
    python3 skill_ingest.py ingest --source <path|git-url> --name <n>
                                   [--origin <org>] [--confirm]
                                   [--static-only] [--model <m>] [--json]

Exit codes:
    0  Vaulted / approved
    1  Blocked -- audit FAIL, or Tier 2/3 awaiting --confirm
    2  Invalid arguments / fetch failed
    3  LLM harness unavailable during audit (static-only audit still gated the decision)
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
import security_auditor  # noqa: E402
from vetted_vault import (  # noqa: E402
    HERMES_HOME, VAULT_DIR, REQUIRE_CONFIRM_TIERS, IGNORE_NAMES,
    classify, compute_sha256, load_registry, save_registry, VaultEntry,
)


QUARANTINE_DIR = HERMES_HOME / ".hermes-quarantine"
_URL_RE = re.compile(r"^(https?://|git@|git://|ssh://)", re.IGNORECASE)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# Local-path ingestion is restricted to genuine first-party skills. Anything else
# (e.g. a hand-authored SKILL.md dropped in /tmp) must arrive via a real remote
# URL so it carries verifiable provenance. This is what stops a fabricated skill
# from being ingested -- see _local_source_allowed.
_LOCAL_SOURCE_ROOTS = (HERMES_HOME / "skills", HERMES_HOME / "scripts")


def _local_source_allowed(src_path: Path) -> bool:
    """A non-URL source is allowed only when it lives under a first-party root."""
    try:
        resolved = src_path.resolve()
    except OSError:
        return False
    for root in _LOCAL_SOURCE_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


@dataclass
class IngestReport:
    name: str
    source: str
    tier: int
    verdict: str
    vaulted: bool
    vault_path: str
    status: str  # approved | blocked | awaiting_confirmation | error
    findings_summary: dict = field(default_factory=dict)
    warning: str = ""
    command_preview: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "tier": self.tier,
            "verdict": self.verdict,
            "vaulted": self.vaulted,
            "vault_path": self.vault_path,
            "status": self.status,
            "findings_summary": self.findings_summary,
            "warning": self.warning,
            "command_preview": self.command_preview,
            "error": self.error,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_url(source: str) -> bool:
    return bool(_URL_RE.match(source))


def fetch_to_quarantine(source: str, name: str, trusted_local: bool = False) -> tuple:
    """Copy/clone the source into quarantine. Returns (path, error). Never executes it.

    A non-URL (local-path) source is only accepted when it lives under a first-party
    root (see _local_source_allowed) OR when `trusted_local` is set -- the latter is
    reserved for callers (e.g. skill_discovery) that already cloned the source from a
    verified remote into a temp dir. This is what blocks a hand-authored skill dropped
    in /tmp from being ingested as if it had real provenance."""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = QUARANTINE_DIR / name
    if dest.exists():
        shutil.rmtree(dest)

    if _is_url(source):
        try:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", source, str(dest)],
                capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return None, f"git clone failed: {e}"
        if proc.returncode != 0:
            return None, f"git clone failed: {proc.stderr.strip()[-500:]}"
        return dest, ""

    src_path = Path(source)
    if not src_path.exists():
        return None, f"source not found: {source}"
    if not trusted_local and not _local_source_allowed(src_path):
        return None, (
            f"refusing local source outside first-party roots: {source}. "
            "Ingest a remote URL (verifiable provenance) or place the skill under "
            f"{HERMES_HOME / 'skills'}. Fabricated/hand-authored skills are not vaultable."
        )
    try:
        if src_path.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest / src_path.name)
        else:
            shutil.copytree(src_path, dest, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
    except OSError as e:
        return None, f"failed to copy into quarantine: {e}"
    return dest, ""


def _summarize_findings(report) -> dict:
    static_fail = sum(1 for f in report.static_findings if f.severity == "FAIL")
    static_warn = sum(1 for f in report.static_findings if f.severity == "WARN")
    llm_fail = sum(1 for f in report.llm_findings
                   if str(f.get("severity", "")).upper() == "FAIL")
    llm_warn = sum(1 for f in report.llm_findings
                   if str(f.get("severity", "")).upper() == "WARN")
    top = [f.as_dict() for f in report.static_findings[:8]]
    return {
        "static_fail": static_fail, "static_warn": static_warn,
        "llm_fail": llm_fail, "llm_warn": llm_warn,
        "llm_used": report.llm_used, "top_static": top,
    }


def _vault_copy(quarantined: Path, name: str, tier: int, origin: str,
                verdict: str) -> VaultEntry:
    """Copy the quarantined tree into the immutable vault and register it approved."""
    sha = compute_sha256(quarantined)
    dest = VAULT_DIR / name
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(quarantined, dest, ignore=shutil.ignore_patterns(*IGNORE_NAMES))

    registry = load_registry()
    existing = registry.get(name)
    first_seen = existing.first_seen if existing else _now()
    entry = VaultEntry(
        sha256=sha, name=name, tier=tier, origin=origin or "",
        status="approved", vaulted_path=str(dest),
        first_seen=first_seen, approved_at=_now(),
        notes=f"ingested; audit verdict={verdict}",
    )
    registry[name] = entry
    save_registry(registry)
    return entry


def ingest(source: str, name: str, origin: Optional[str], confirm: bool,
           static_only: bool, model: Optional[str] = None,
           engine: Optional[str] = None, trusted_local: bool = False) -> tuple:
    """Run the full pipeline. Returns (IngestReport, exit_code).

    `model` is accepted for backward compatibility and ignored; the audit's
    LLM pass runs through the active coding harness (`engine`).

    `trusted_local` lets a caller that already fetched from a verified remote
    (e.g. skill_discovery, which git-cloned the source) ingest from the temp
    clone path. Direct CLI ingestion leaves it False, so a bare local path must
    live under a first-party root -- see fetch_to_quarantine/_local_source_allowed."""
    quarantined, err = fetch_to_quarantine(source, name, trusted_local=trusted_local)
    if err:
        return IngestReport(name=name, source=source, tier=0, verdict="",
                            vaulted=False, vault_path="", status="error", error=err), 2

    try:
        tier = classify(quarantined, origin)
        audit_report, harness_down = security_auditor.audit_source(
            quarantined, static_only=static_only, engine=engine,
        )
        verdict = audit_report.verdict
        summary = _summarize_findings(audit_report)

        # FAIL -> hard block, vault nothing.
        if verdict == security_auditor.VERDICT_FAIL:
            return IngestReport(
                name=name, source=source, tier=tier, verdict=verdict,
                vaulted=False, vault_path="", status="blocked",
                findings_summary=summary,
                warning="Security audit returned FAIL -- ingestion hard-blocked. "
                        "Nothing was vaulted.",
            ), 1

        # Tier 2/3 require explicit human confirmation (no auto-approval of untrusted code).
        if tier in REQUIRE_CONFIRM_TIERS and not confirm:
            preview = (
                f"python3 skill_ingest.py ingest --source '{source}' --name '{name}'"
                + (f" --origin '{origin}'" if origin else "")
                + " --confirm"
            )
            return IngestReport(
                name=name, source=source, tier=tier, verdict=verdict,
                vaulted=False, vault_path="", status="awaiting_confirmation",
                findings_summary=summary, command_preview=preview,
                warning=(f"Tier {tier} source passed the audit with verdict {verdict}, but a "
                         "human must review it before vaulting. Re-run with --confirm after review."),
            ), 1

        # PASS/WARN (+ confirm if needed) -> vault.
        entry = _vault_copy(quarantined, name, tier, origin or "", verdict)
        exit_code = 3 if harness_down else 0
        return IngestReport(
            name=name, source=source, tier=tier, verdict=verdict,
            vaulted=True, vault_path=entry.vaulted_path, status="approved",
            findings_summary=summary,
            warning=("Audit ran static-only (LLM harness unavailable); static verdict gated the "
                     "decision." if harness_down else ""),
        ), exit_code
    finally:
        # The vault holds the kept copy; quarantine is always cleaned up.
        if quarantined and quarantined.exists():
            shutil.rmtree(quarantined, ignore_errors=True)


# -- CLI --

def cmd_ingest(args) -> int:
    if not _NAME_RE.match(args.name):
        msg = {"status": "error", "error": f"invalid --name: {args.name!r}"}
        print(json.dumps(msg, indent=2) if args.json else f"ERROR: {msg['error']}",
              file=None if args.json else sys.stderr)
        return 2

    report, code = ingest(
        args.source, args.name, args.origin, args.confirm,
        args.static_only, engine=args.engine,
    )
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(f"[{report.status}] {report.name} (tier {report.tier}) verdict={report.verdict}")
        if report.warning:
            print(f"  {report.warning}")
        if report.vaulted:
            print(f"  vaulted -> {report.vault_path}")
        if report.command_preview:
            print(f"  $ {report.command_preview}")
        if report.error:
            print(f"  error: {report.error}", file=sys.stderr)
        fs = report.findings_summary
        if fs:
            print(f"  findings: static FAIL={fs.get('static_fail', 0)} "
                  f"WARN={fs.get('static_warn', 0)} | llm FAIL={fs.get('llm_fail', 0)} "
                  f"WARN={fs.get('llm_warn', 0)} (llm_used={fs.get('llm_used')})")
    return code


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end skill/tool ingestion (fetch->audit->vault)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="Fetch, audit, and (if clean) vault a third-party source")
    p.add_argument("--source", required=True, help="Local path or git/http(s) URL")
    p.add_argument("--name", required=True, help="Tool identity (vault + registry key)")
    p.add_argument("--origin", default=None, help="Origin org/host (for tier classification)")
    p.add_argument("--confirm", action="store_true", help="Confirm vaulting a Tier 2/3 source after manual review")
    p.add_argument("--static-only", action="store_true", help="Skip the LLM audit pass")
    p.add_argument("--engine", default=None,
                   choices=["claude-code", "antigravity", "opencode"],
                   help="Coding harness for the audit's LLM pass (default: config coding.default_engine)")
    p.add_argument("--model", default=None,
                   help="Deprecated/ignored; the audit uses the coding harness")
    p.add_argument("--json", action="store_true", help="Emit JSON")
    p.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
