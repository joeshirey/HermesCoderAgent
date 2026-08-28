#!/usr/bin/env python3
"""Per-repo onboarding: capture a repo's permissions on first touch.

The coordinator interviews the user the first time it works in a repo and
persists the answers so every later command honors them without re-asking.
Three things are captured, stored across the two existing per-repo config files:

  .hermes-github.yaml   autonomy, default_base, skill_discovery
  .hermes-backlog.yaml  enabled, project_name

A repo counts as *onboarded* once `.hermes-github.yaml` exists. `--skip` writes
a safe-default marker (gated / no backlog / local-only) so a declined interview
still onboards the repo and is never re-asked.

Stdlib only; no PyYAML. Reuses the flat-YAML reader and autonomy constants from
github_lifecycle so the config format has one source of truth.

Usage:
    python3 repo_onboarding.py status --repo /path [--json]
    python3 repo_onboarding.py init --repo /path --autonomy gated \\
            --backlog true --backlog-project Demo --skill-discovery external
    python3 repo_onboarding.py init --repo /path --skip

Exit codes:
    0  Success (status reported / repo onboarded)
    1  Refused: would overwrite existing values without --force
    2  Invalid arguments / nothing to do
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from github_lifecycle import (  # noqa: E402
    AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY,
    resolve_autonomy,
    resolve_base,
)

GITHUB_FILE = ".hermes-github.yaml"
BACKLOG_FILE = ".hermes-backlog.yaml"
SKILL_DISCOVERY_LEVELS = ["external", "local-only"]
DEFAULT_SKILL_DISCOVERY = "external"

_KEY_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")


# -- flat-YAML read / write (stdlib-only, order-preserving) --

def _read_all_flat(path: Path) -> dict:
    """Read every top-level `key: value` from a flat YAML file (order kept)."""
    result: dict = {}
    if not path.is_file():
        return result
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        m = _KEY_RE.match(line)
        if m:
            v = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("\"'")
            result[m.group(1)] = v
    return result


def _write_flat_yaml(path: Path, updates: dict, force: bool,
                     header: str = "") -> dict:
    """Merge `updates` into the flat-YAML file at `path`, preserving other keys.

    Refuses (no write) when a provided key already holds a different value and
    `force` is False. A re-run that changes nothing is a no-op success."""
    existing = _read_all_flat(path)
    conflicts = {k: (existing[k], v) for k, v in updates.items()
                 if k in existing and existing[k] != v}
    if conflicts and not force:
        return {"written": False, "noop": False, "conflicts": conflicts,
                "path": str(path)}
    changed = any(existing.get(k) != v for k, v in updates.items())
    if not changed and path.is_file():
        return {"written": False, "noop": True, "conflicts": {},
                "path": str(path)}
    merged = dict(existing)
    merged.update(updates)
    lines = []
    if header:
        lines.append(f"# {header}")
    lines.extend(f"{k}: {v}" for k, v in merged.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"written": True, "noop": False, "conflicts": {}, "path": str(path)}


# -- settings inspection --

def _skill_discovery_for(repo: str) -> str:
    val = _read_all_flat(Path(repo) / GITHUB_FILE).get("skill_discovery")
    return val if val in SKILL_DISCOVERY_LEVELS else DEFAULT_SKILL_DISCOVERY


def _backlog_for(repo: str) -> dict:
    cfg = _read_all_flat(Path(repo) / BACKLOG_FILE)
    return {
        "enabled": str(cfg.get("enabled", "")).lower() == "true",
        "project_name": cfg.get("project_name") or None,
    }


def _resolved_settings(repo: str) -> dict:
    backlog = _backlog_for(repo)
    return {
        "autonomy": resolve_autonomy(repo, None),
        "default_base": resolve_base(repo, None),
        "skill_discovery": _skill_discovery_for(repo),
        "backlog_enabled": backlog["enabled"],
        "backlog_project": backlog["project_name"],
    }


def _is_onboarded(repo: str) -> bool:
    return (Path(repo) / GITHUB_FILE).is_file()


# -- commands --

def cmd_status(args, repo: str) -> tuple:
    out = {
        "onboarded": _is_onboarded(repo),
        "files": {
            GITHUB_FILE: (Path(repo) / GITHUB_FILE).is_file(),
            BACKLOG_FILE: (Path(repo) / BACKLOG_FILE).is_file(),
        },
        "settings": _resolved_settings(repo),
    }
    return out, 0


def cmd_init(args, repo: str) -> tuple:
    github_updates: dict = {}
    backlog_updates: dict = {}

    if args.skip:
        github_updates = {"autonomy": DEFAULT_AUTONOMY,
                          "skill_discovery": "local-only"}
        backlog_updates = {"enabled": "false"}
    else:
        github_updates["autonomy"] = args.autonomy
        if args.default_base:
            github_updates["default_base"] = args.default_base
        if args.skill_discovery:
            github_updates["skill_discovery"] = args.skill_discovery
        if args.backlog == "true":
            backlog_updates["enabled"] = "true"
            if args.backlog_project:
                backlog_updates["project_name"] = args.backlog_project
        elif args.backlog == "false":
            backlog_updates["enabled"] = "false"

    repo_path = Path(repo)
    writes = []
    refused = {}

    gh_res = _write_flat_yaml(repo_path / GITHUB_FILE, github_updates,
                              args.force, header="hermes-coder per-repo GitHub config")
    writes.append(gh_res)
    if gh_res["conflicts"]:
        refused[GITHUB_FILE] = gh_res["conflicts"]

    if backlog_updates:
        bl_res = _write_flat_yaml(repo_path / BACKLOG_FILE, backlog_updates,
                                  args.force,
                                  header="hermes-coder per-repo backlog config")
        writes.append(bl_res)
        if bl_res["conflicts"]:
            refused[BACKLOG_FILE] = bl_res["conflicts"]

    if refused:
        out = {
            "status": "refused",
            "reason": "would overwrite existing values; re-run with --force",
            "conflicts": refused,
            "onboarded": _is_onboarded(repo),
        }
        return out, 1

    out = {
        "status": "onboarded",
        "skipped": bool(args.skip),
        "onboarded": _is_onboarded(repo),
        "wrote": [w["path"] for w in writes if w["written"]],
        "unchanged": [w["path"] for w in writes if w.get("noop")],
        "settings": _resolved_settings(repo),
    }
    return out, 0


def _emit(out: dict, as_json: bool):
    if as_json:
        print(json.dumps(out, indent=2))
        return
    status = out.get("status")
    if status == "refused":
        print("REFUSED: would overwrite existing values; re-run with --force")
        for fname, conflicts in out["conflicts"].items():
            for key, (old, new) in conflicts.items():
                print(f"  {fname}: {key} {old!r} -> {new!r}")
        return
    if "onboarded" in out and status is None:  # status command
        print(f"onboarded: {out['onboarded']}")
        s = out["settings"]
        print(f"  autonomy:        {s['autonomy']}")
        print(f"  default_base:    {s['default_base']}")
        print(f"  skill_discovery: {s['skill_discovery']}")
        print(f"  backlog:         {'on' if s['backlog_enabled'] else 'off'}"
              + (f" (project: {s['backlog_project']})" if s['backlog_project'] else ""))
        return
    # init success
    verb = "Onboarded (skipped — safe defaults)" if out.get("skipped") else "Onboarded"
    print(f"{verb}: {os.path.basename(os.getcwd())}")
    for p in out.get("wrote", []):
        print(f"  wrote {p}")
    for p in out.get("unchanged", []):
        print(f"  unchanged {p}")
    s = out["settings"]
    print(f"  autonomy={s['autonomy']} skill_discovery={s['skill_discovery']} "
          f"backlog={'on' if s['backlog_enabled'] else 'off'}")


HANDLERS = {"status": cmd_status, "init": cmd_init}


def main():
    parser = argparse.ArgumentParser(
        description="Per-repo onboarding for the hermes-coder coordinator")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="Repository path (local filesystem path, NOT a gh owner/repo slug)")
    common.add_argument("--json", action="store_true", help="Output as JSON")

    sub.add_parser("status", parents=[common],
                   help="Report onboarding state + resolved per-repo settings")

    p_init = sub.add_parser("init", parents=[common],
                            help="Persist the interview answers (idempotent)")
    p_init.add_argument("--autonomy", choices=AUTONOMY_LEVELS,
                        default=DEFAULT_AUTONOMY,
                        help="Remote autonomy for PRs/pushes (default: gated)")
    p_init.add_argument("--default-base", default=None,
                        help="Default base branch for PRs")
    p_init.add_argument("--backlog", choices=["true", "false"], default=None,
                        help="Manage the backlog as GitHub Issues")
    p_init.add_argument("--backlog-project", default=None,
                        help="Backlog project name (when --backlog true)")
    p_init.add_argument("--skill-discovery", choices=SKILL_DISCOVERY_LEVELS,
                        default=None,
                        help="Allow external skill discovery, or local-only")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite existing values that differ")
    p_init.add_argument("--skip", action="store_true",
                        help="Decline the interview; write safe defaults "
                             "(gated / no backlog / local-only)")

    args = parser.parse_args()

    from repo_paths import resolve_repo_path
    repo = resolve_repo_path(args.repo)
    if not repo:
        print(f"Error: repository path does not exist: {args.repo}", file=sys.stderr)
        sys.exit(2)

    out, code = HANDLERS[args.command](args, repo)
    _emit(out, args.json)
    sys.exit(code)


if __name__ == "__main__":
    main()
