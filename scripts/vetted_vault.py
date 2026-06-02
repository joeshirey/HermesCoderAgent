#!/usr/bin/env python3
"""Vetted-vault: trust tiers + SHA-256 registry for skills/tools (safe slice of #6).

This is the cheap, no-execution groundwork for the Dynamic Skill & Tool Injection
security gateway. It classifies a source into a reputation tier, hashes its
contents (SHA-256), and maintains an immutable local registry + vault copy.

It deliberately does NOT execute code, run an LLM/static security auditor, or
spin up containers -- those are the genuinely risky pieces and stay deferred to
Phase 4 (to land alongside an actual third-party ingestion path). Until then this
gateway is a near-no-op: local user-authored skills classify as Tier 1 and are
auto-approved. Vaulting a Tier 2/3 source requires an explicit --confirm, because
there is no automated auditor yet -- a human must review the source first.

Global store (tools are shared across repos):
    registry: ~/.hermes-coder/vetted_tools.json
    vault:    ~/.hermes-coder/vetted_vault/<name>/

Usage:
    python3 vetted_vault.py classify --source <path> [--origin <org>]
    python3 vetted_vault.py hash --source <path>
    python3 vetted_vault.py check --source <path>
    python3 vetted_vault.py vault --source <path> --name <n> [--origin <org>] [--confirm]
    python3 vetted_vault.py status --source <path>
    python3 vetted_vault.py list
    python3 vetted_vault.py update --source <upstream> --name <n> [--confirm]

Phase 4 (now operational): the auditor (security_auditor.py), container runner
(container_runner.py), and ingestion pipeline (skill_ingest.py) are live. The
`update` subcommand runs the diff-audit lifecycle: re-hash upstream, audit a
changed tree, and atomically replace the vault copy (archiving the prior version
for rollback) only after a non-FAIL audit and --confirm.

Exit codes:
    0  Success (classified / hashed / approved / vaulted / listed / up-to-date / updated)
    1  Blocked -- unknown source, unapproved Tier 2/3, outdated awaiting confirm, or audit FAIL
    2  Invalid arguments / source not found / fetch failed
    3  LLM harness unavailable during an update audit (static-only verdict still gated)
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# -- Config defaults (overridable via ~/.hermes-coder/config.yaml) --

HERMES_HOME = Path.home() / ".hermes-coder"
REGISTRY_PATH = HERMES_HOME / "vetted_tools.json"
VAULT_DIR = HERMES_HOME / "vetted_vault"
ARCHIVE_DIR = VAULT_DIR / ".archive"
LOCAL_TIER1_DIRS = [HERMES_HOME / "skills", HERMES_HOME / "scripts"]
TRUSTED_ORGS = ["google", "anthropic", "aws", "microsoft", "modelcontextprotocol"]
REQUIRE_CONFIRM_TIERS = {2, 3}
IGNORE_NAMES = {".git", "__pycache__", ".DS_Store", ".hermes-worktrees"}
_URL_RE = re.compile(r"^(https?://|git@|git://|ssh://)", re.IGNORECASE)


# -- Dataclass --

@dataclass
class VaultEntry:
    sha256: str
    name: str
    tier: int
    origin: str = ""
    status: str = "approved"  # approved | pending | outdated
    vaulted_path: str = ""
    first_seen: str = ""
    approved_at: str = ""
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "sha256": self.sha256,
            "name": self.name,
            "tier": self.tier,
            "origin": self.origin,
            "status": self.status,
            "vaulted_path": self.vaulted_path,
            "first_seen": self.first_seen,
            "approved_at": self.approved_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VaultEntry":
        return cls(
            sha256=d.get("sha256", ""),
            name=d.get("name", ""),
            tier=int(d.get("tier", 3)),
            origin=d.get("origin", ""),
            status=d.get("status", "approved"),
            vaulted_path=d.get("vaulted_path", ""),
            first_seen=d.get("first_seen", ""),
            approved_at=d.get("approved_at", ""),
            notes=d.get("notes", ""),
        )


# -- Helpers --

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _derive_name(source: Path) -> str:
    return source.name


def classify(source: Path, origin: Optional[str] = None,
             tier1_dirs: Optional[list] = None,
             trusted_orgs: Optional[list] = None) -> int:
    """Assign a reputation tier. 1 = local/official, 2 = trusted org, 3 = unknown."""
    tier1_dirs = tier1_dirs if tier1_dirs is not None else LOCAL_TIER1_DIRS
    trusted_orgs = trusted_orgs if trusted_orgs is not None else TRUSTED_ORGS

    try:
        resolved = source.resolve()
    except OSError:
        resolved = source

    for base in tier1_dirs:
        try:
            resolved.relative_to(Path(base).resolve())
            return 1
        except (ValueError, OSError):
            continue

    if origin:
        low = origin.lower()
        if any(org in low for org in trusted_orgs):
            return 2

    return 3


def compute_sha256(source: Path) -> str:
    """Deterministic SHA-256 over a file or directory tree."""
    h = hashlib.sha256()
    if source.is_file():
        h.update(b"file\0")
        h.update(source.name.encode("utf-8"))
        h.update(b"\0")
        h.update(source.read_bytes())
        return h.hexdigest()

    files = []
    for p in source.rglob("*"):
        if not p.is_file():
            continue
        if any(part in IGNORE_NAMES for part in p.relative_to(source).parts):
            continue
        files.append(p)

    files.sort(key=lambda p: str(p.relative_to(source)))
    for p in files:
        rel = str(p.relative_to(source))
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    """Load registry keyed by name -> VaultEntry."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {name: VaultEntry.from_dict(d) for name, d in raw.items() if isinstance(d, dict)}


def save_registry(registry: dict, path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {name: entry.as_dict() for name, entry in registry.items()}
    path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def check_source(source: Path, origin: Optional[str], registry: dict,
                 name: Optional[str] = None) -> dict:
    """Resolve a source to a vault status.

    Identity is the tool name (defaults to the source basename, override with
    --name). Approval is recognized first by checksum (an approved entry with a
    matching SHA, under any name) per the RFC's checksum-bypass, then by name.
    """
    tier = classify(source, origin)
    name = name or _derive_name(source)
    sha = compute_sha256(source)

    if tier == 1:
        return {"status": "approved", "tier": tier, "name": name, "sha256": sha,
                "reason": "Tier 1 (local/official) — auto-approved, audit bypassed"}

    for entry in registry.values():
        if entry.sha256 == sha and entry.status == "approved":
            return {"status": "approved", "tier": tier, "name": name, "sha256": sha,
                    "reason": f"checksum matches approved vault entry {entry.name!r}"}

    entry = registry.get(name)
    if entry is None:
        return {"status": "unknown", "tier": tier, "name": name, "sha256": sha,
                "reason": "not in vault — requires vetting before injection"}
    if entry.sha256 != sha:
        return {"status": "outdated", "tier": tier, "name": name, "sha256": sha,
                "reason": "source changed since approval — re-vet the diff",
                "approved_sha256": entry.sha256}
    return {"status": entry.status, "tier": tier, "name": name, "sha256": sha,
            "reason": f"registry status is {entry.status!r}"}


# -- Subcommand handlers --

def cmd_classify(args) -> int:
    source = Path(args.source)
    if not source.exists():
        return _fail(f"source not found: {args.source}", args.json)
    tier = classify(source, args.origin)
    labels = {1: "Tier 1 (local / official)", 2: "Tier 2 (trusted org)", 3: "Tier 3 (unknown / ad-hoc)"}
    result = {"source": str(source), "tier": tier, "label": labels[tier], "origin": args.origin or ""}
    _emit(result, args.json, f"{labels[tier]}  <-  {source}")
    return 0


def cmd_hash(args) -> int:
    source = Path(args.source)
    if not source.exists():
        return _fail(f"source not found: {args.source}", args.json)
    sha = compute_sha256(source)
    _emit({"source": str(source), "sha256": sha}, args.json, f"{sha}  {source}")
    return 0


def cmd_check(args) -> int:
    source = Path(args.source)
    if not source.exists():
        return _fail(f"source not found: {args.source}", args.json)
    registry = load_registry()
    result = check_source(source, args.origin, registry, name=args.name)
    _emit(result, args.json,
          f"[{result['status']}] {result['name']} (tier {result['tier']}) — {result['reason']}")
    return 0 if result["status"] == "approved" else 1


def cmd_status(args) -> int:
    # status is check with the full registry entry attached when present
    source = Path(args.source)
    if not source.exists():
        return _fail(f"source not found: {args.source}", args.json)
    registry = load_registry()
    result = check_source(source, args.origin, registry, name=args.name)
    entry = registry.get(result["name"])
    if entry:
        result["entry"] = entry.as_dict()
    _emit(result, args.json,
          f"[{result['status']}] {result['name']} (tier {result['tier']}) — {result['reason']}")
    return 0 if result["status"] == "approved" else 1


def cmd_vault(args) -> int:
    source = Path(args.source)
    if not source.exists():
        return _fail(f"source not found: {args.source}", args.json)

    name = args.name or _derive_name(source)
    tier = classify(source, args.origin)

    if tier in REQUIRE_CONFIRM_TIERS and not args.confirm:
        preview = (
            f"python3 vetted_vault.py vault --source '{args.source}' --name '{name}'"
            + (f" --origin '{args.origin}'" if args.origin else "")
            + " --confirm"
        )
        result = {
            "status": "awaiting_confirmation",
            "tier": tier,
            "name": name,
            "warning": (
                "No automated security auditor exists yet (deferred to Phase 4). "
                f"A human must review this Tier {tier} source before approval. "
                "Re-run with --confirm only after manual review."
            ),
            "command_preview": preview,
        }
        _emit(result, args.json,
              f"BLOCKED: Tier {tier} source {name!r} needs manual review.\n"
              f"  {result['warning']}\n  $ {preview}")
        return 1

    sha = compute_sha256(source)
    dest = VAULT_DIR / name
    try:
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest / source.name)
        else:
            shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
    except OSError as e:
        return _fail(f"failed to copy into vault: {e}", args.json)

    registry = load_registry()
    existing = registry.get(name)
    first_seen = existing.first_seen if existing else _now()
    entry = VaultEntry(
        sha256=sha, name=name, tier=tier, origin=args.origin or "",
        status="approved", vaulted_path=str(dest),
        first_seen=first_seen, approved_at=_now(),
        notes="approved via --confirm (manual review)" if tier in REQUIRE_CONFIRM_TIERS
              else "Tier 1 auto-approved",
    )
    registry[name] = entry
    save_registry(registry)

    result = {"status": "approved", **entry.as_dict()}
    _emit(result, args.json, f"APPROVED {name} (tier {tier}) -> {dest}")
    return 0


def cmd_list(args) -> int:
    registry = load_registry()
    entries = [e.as_dict() for e in registry.values()]
    if args.json:
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
    else:
        if not entries:
            print("Vault is empty.")
        else:
            print(f"{len(entries)} vaulted tool(s):")
            for e in entries:
                print(f"  [{e['status']}] {e['name']} (tier {e['tier']}) "
                      f"{e['sha256'][:12]}  {e['vaulted_path']}")
    return 0


def cmd_remove(args) -> int:
    """Delete a vaulted entry: drop the on-disk copy and its registry record.

    Use this to retract a tool that should never have been vaulted (e.g. a
    fabricated/hand-authored skill). Removal is gated behind --confirm so it is
    never an accidental one-keystroke wipe."""
    name = args.name
    registry = load_registry(REGISTRY_PATH)
    entry = registry.get(name)
    dest = VAULT_DIR / name
    on_disk = dest.exists()

    if not entry and not on_disk:
        return _fail(f"no vaulted entry named {name!r}", args.json)

    if not args.confirm:
        preview = f"python3 vetted_vault.py remove --name '{name}' --confirm"
        result = {
            "status": "awaiting_confirmation", "name": name,
            "registered": bool(entry), "on_disk": on_disk,
            "vaulted_path": str(dest),
            "warning": "Removal deletes the vault copy and registry record. "
                       "Re-run with --confirm.",
            "command_preview": preview,
        }
        _emit(result, args.json,
              f"BLOCKED: would remove {name!r} (registered={bool(entry)}, "
              f"on_disk={on_disk}).\n  $ {preview}")
        return 1

    if on_disk:
        try:
            shutil.rmtree(dest)
        except OSError as e:
            return _fail(f"failed to remove vault copy: {e}", args.json)
    if entry:
        del registry[name]
        save_registry(registry, REGISTRY_PATH)

    result = {"status": "removed", "name": name,
              "deregistered": bool(entry), "deleted_path": str(dest) if on_disk else ""}
    _emit(result, args.json,
          f"REMOVED {name} (deregistered={bool(entry)}, deleted={on_disk})")
    return 0


def _is_url(source: str) -> bool:
    return bool(_URL_RE.match(source))


def _fetch_upstream(source: str) -> tuple:
    """Fetch upstream into a fresh temp dir for re-hashing/auditing. Never executes it.

    Returns (path, tempdir_to_clean, error). For a local file, the temp dir holds a
    copy of just that file so hashing matches the vaulted layout.
    """
    tmp = Path(tempfile.mkdtemp(prefix="hermes-update-"))
    if _is_url(source):
        dest = tmp / "upstream"
        try:
            proc = subprocess.run(
                ["git", "clone", "--depth", "1", source, str(dest)],
                capture_output=True, text=True, timeout=180,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, f"git clone failed: {e}"
        if proc.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, f"git clone failed: {proc.stderr.strip()[-500:]}"
        return dest, tmp, ""

    src_path = Path(source)
    if not src_path.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None, f"source not found: {source}"
    dest = tmp / "upstream"
    try:
        if src_path.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest / src_path.name)
        else:
            shutil.copytree(src_path, dest, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
    except OSError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None, f"failed to copy upstream: {e}"
    return dest, tmp, ""


def cmd_update(args) -> int:
    """Diff-audit lifecycle: re-hash upstream, audit a changed tree, atomically replace."""
    registry = load_registry()
    name = args.name
    entry = registry.get(name)
    if entry is None:
        return _fail(f"{name!r} is not vaulted -- use vault/ingest first", args.json)

    upstream, tmp, err = _fetch_upstream(args.source)
    if err:
        return _fail(err, args.json)

    try:
        new_sha = compute_sha256(upstream)
        if new_sha == entry.sha256:
            result = {"status": "up-to-date", "name": name, "sha256": new_sha,
                      "reason": "upstream matches the vaulted copy"}
            _emit(result, args.json, f"[up-to-date] {name} {new_sha[:12]}")
            return 0

        # Source changed -> surgical audit of the new tree.
        sys.path.insert(0, str(Path(__file__).parent))
        import security_auditor  # noqa
        audit_report, harness_down = security_auditor.audit_source(
            upstream, static_only=args.static_only, engine=args.engine,
        )
        verdict = audit_report.verdict
        diff_card = {
            "name": name, "local_sha": entry.sha256, "upstream_sha": new_sha,
            "verdict": verdict, "tier": entry.tier,
            "static_fail": sum(1 for f in audit_report.static_findings if f.severity == "FAIL"),
            "static_warn": sum(1 for f in audit_report.static_findings if f.severity == "WARN"),
            "llm_used": audit_report.llm_used,
        }

        if verdict == "FAIL":
            result = {"status": "blocked", **diff_card,
                      "warning": "Upstream audit FAILED -- vault copy left unchanged."}
            _emit(result, args.json,
                  f"[blocked] {name}: upstream audit FAIL; vault unchanged")
            return 1

        if not args.confirm:
            preview = (f"python3 vetted_vault.py update --source '{args.source}' "
                       f"--name '{name}' --confirm")
            result = {"status": "awaiting_confirmation", **diff_card,
                      "command_preview": preview,
                      "warning": (f"Upstream changed (verdict {verdict}). Review the diff, then "
                                  "re-run with --confirm to replace the vault copy.")}
            _emit(result, args.json,
                  f"[outdated] {name}: {entry.sha256[:12]} -> {new_sha[:12]} "
                  f"(verdict {verdict})\n  $ {preview}")
            return 1

        # Atomic replace + archive the previous version for rollback.
        dest = Path(entry.vaulted_path) if entry.vaulted_path else (VAULT_DIR / name)
        archive_path = ARCHIVE_DIR / name / entry.sha256
        try:
            if dest.exists():
                archive_path.parent.mkdir(parents=True, exist_ok=True)
                if archive_path.exists():
                    shutil.rmtree(archive_path)
                shutil.copytree(dest, archive_path,
                                ignore=shutil.ignore_patterns(*IGNORE_NAMES))
            staging = dest.parent / f"{name}.new"
            if staging.exists():
                shutil.rmtree(staging)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(upstream, staging, ignore=shutil.ignore_patterns(*IGNORE_NAMES))
            if dest.exists():
                shutil.rmtree(dest)
            os.replace(staging, dest)
        except OSError as e:
            return _fail(f"failed to replace vault copy: {e}", args.json)

        entry.sha256 = new_sha
        entry.status = "approved"
        entry.approved_at = _now()
        entry.vaulted_path = str(dest)
        entry.notes = f"updated via diff-audit; verdict={verdict}; prev archived {ARCHIVE_DIR.name}"
        registry[name] = entry
        save_registry(registry)

        result = {"status": "updated", **diff_card,
                  "vaulted_path": str(dest), "archived_to": str(archive_path)}
        _emit(result, args.json,
              f"[updated] {name} -> {new_sha[:12]} (prev archived under {archive_path})")
        return 3 if harness_down else 0
    finally:
        if tmp and Path(tmp).exists():
            shutil.rmtree(tmp, ignore_errors=True)


# -- Output helpers --

def _emit(result: dict, as_json: bool, human: str) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print(human)


def _fail(message: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"status": "error", "error": message}, indent=2))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 2


# -- Main --

def main() -> None:
    parser = argparse.ArgumentParser(description="Trust tiers + SHA-256 vetted vault for skills/tools")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p, need_source=True):
        if need_source:
            p.add_argument("--source", required=True, help="Path to the skill/tool source")
        p.add_argument("--origin", default=None, help="Origin org/host (for tier classification)")
        p.add_argument("--json", action="store_true", help="Emit JSON")

    p_classify = sub.add_parser("classify", help="Assign a reputation tier")
    add_common(p_classify)
    p_classify.set_defaults(func=cmd_classify)

    p_hash = sub.add_parser("hash", help="Compute the deterministic SHA-256")
    add_common(p_hash)
    p_hash.set_defaults(func=cmd_hash)

    p_check = sub.add_parser("check", help="Resolve a source to a vault status")
    add_common(p_check)
    p_check.add_argument("--name", default=None, help="Tool identity (default: source basename)")
    p_check.set_defaults(func=cmd_check)

    p_status = sub.add_parser("status", help="Full status incl. registry entry")
    add_common(p_status)
    p_status.add_argument("--name", default=None, help="Tool identity (default: source basename)")
    p_status.set_defaults(func=cmd_status)

    p_vault = sub.add_parser("vault", help="Copy into the vault and register as approved")
    add_common(p_vault)
    p_vault.add_argument("--name", default=None, help="Vault name (default: source basename)")
    p_vault.add_argument("--confirm", action="store_true", help="Confirm vaulting a Tier 2/3 source after manual review")
    p_vault.set_defaults(func=cmd_vault)

    p_list = sub.add_parser("list", help="List vaulted entries")
    p_list.add_argument("--json", action="store_true", help="Emit JSON")
    p_list.set_defaults(func=cmd_list)

    p_remove = sub.add_parser("remove", help="Delete a vaulted entry (vault copy + registry record)")
    p_remove.add_argument("--name", required=True, help="Vaulted tool name to remove")
    p_remove.add_argument("--confirm", action="store_true", help="Confirm deletion")
    p_remove.add_argument("--json", action="store_true", help="Emit JSON")
    p_remove.set_defaults(func=cmd_remove)

    p_update = sub.add_parser("update", help="Diff-audit an upstream change and replace the vault copy")
    p_update.add_argument("--source", required=True, help="Upstream path or git/http(s) URL")
    p_update.add_argument("--name", required=True, help="Vaulted tool name to update")
    p_update.add_argument("--confirm", action="store_true", help="Apply the update after reviewing the diff")
    p_update.add_argument("--static-only", action="store_true", help="Skip the LLM audit pass")
    p_update.add_argument("--engine", default=None,
                          choices=["claude-code", "antigravity", "opencode"],
                          help="Coding harness for the audit's LLM pass (default: config coding.default_engine)")
    p_update.add_argument("--model", default=None,
                          help="Deprecated/ignored; the audit uses the coding harness")
    p_update.add_argument("--json", action="store_true", help="Emit JSON")
    p_update.set_defaults(func=cmd_update)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
