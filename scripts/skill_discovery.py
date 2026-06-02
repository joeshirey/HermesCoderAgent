#!/usr/bin/env python3
"""Skill discovery + injection: close the loop between the security pipeline (#6)
and the harness layer (Backlog #11).

At dispatch time the coordinator should *discover* the specialized skills a task
needs from a curated allowlist of trusted indexes, gate them by *source
reputation*, vet them through the EXISTING security gateway (security_auditor ->
vetted_vault -> container_runner), and *inject* the approved skills into whichever
harness is active. A documented weekly refresher re-pulls the curated indexes and
checks vaulted skills for updates.

This module is an orchestrator: it reuses #6 by import and never duplicates the
audit/vault/sandbox logic. Nothing fetched is ever executed on the host -- the
auditor is static + LLM only, and any executable scripts a skill ships are run
later, sandboxed, via container_runner (Tier-gated).

Reputation drives policy (decision: "gated by reputation"):
    trusted (anthropic/google/openai/aws/microsoft) -> auto-vault on a clean
        audit (no human --confirm), no code sandbox.
    known   (huggingface, modelcontextprotocol)     -> require --confirm, sandbox
        any shipped code.
    unknown / community                              -> require --confirm, sandbox.

A FAIL audit hard-blocks regardless of reputation. vetted_vault.classify() stays
authoritative for the on-disk registry tier; the reputation map layered here drives
the confirm-gate and the sandbox decision.

Scope: SKILL.md discovery/injection only. MCP-server discovery is a documented
follow-on (different injection surface: process-spawn + allowlist).

Usage:
    python3 skill_discovery.py discover --task "<t>" [--json]
    python3 skill_discovery.py vet --task "<t>" [--all] [--confirm] [--dry-run] [--json]
    python3 skill_discovery.py inject --name <vaulted-name> [--engine <e>] [--json]
    python3 skill_discovery.py refresh [--confirm] [--dry-run] [--json]

Exit codes:
    0  ok / dry-run
    1  held back (awaiting --confirm) or audit FAIL hard-block
    2  invalid arguments / source not found
    3  LLM harness unavailable during audit, or a network pull failed (degraded)
"""

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import skill_ingest  # noqa: E402
import container_runner  # noqa: E402
from vetted_vault import (  # noqa: E402
    load_registry, VAULT_DIR,
)
from harness_llm import resolve_engine  # noqa: E402
from github_lifecycle import _read_flat_yaml_value  # noqa: E402


# -- Config defaults (overridable via ~/.hermes-coder/config.yaml) --

HERMES_HOME = Path.home() / ".hermes-coder"
INDEX_CACHE_DIR = HERMES_HOME / "skills" / ".hub" / "index-cache"
CONFIG_PATH = HERMES_HOME / "config.yaml"

DEFAULT_ALLOWLIST = ["anthropics", "openai", "google", "firebase",
                     "microsoft", "aws",
                     "huggingface", "modelcontextprotocol"]

# Allowlist key -> (repo, subdir to scan for SKILL.md). The single mapping that
# lets `refresh` re-pull a curated index live (clone -> walk SKILL.md -> cache).
# Keys absent here keep whatever snapshot is cached and are not live-pulled.
INDEX_SOURCES = {
    "anthropics": ("anthropics/skills", "skills"),
    "google":     ("google/skills", "skills"),
    "firebase":   ("firebase/agent-skills", "skills"),
    # Microsoft scatters skills across .github/skills + .github/plugins/*/skills,
    # AWS across skills/* + plugins/*/skills -- walk the whole repo ("") for both.
    "microsoft":  ("microsoft/skills", ""),
    "aws":        ("aws/agent-toolkit-for-aws", ""),
}
DEFAULT_TOP_K = 3
EXECUTABLE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".sh", ".bash", ".zsh", ".rb", ".go",
}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WORD_RE = re.compile(r"[a-z]+")

# Source-reputation map: org/marketplace -> policy. The single source of truth
# tying source -> trust -> confirm-gate + sandbox. Substring-matched against an
# index entry's repo/source, mirroring vetted_vault.classify().
SOURCE_REPUTATION = {
    "anthropic":            {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "google":               {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "firebase":             {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "openai":               {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "aws":                  {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "microsoft":            {"trust": "trusted",   "tier": 2, "sandbox_code": False},
    "huggingface":          {"trust": "known",     "tier": 2, "sandbox_code": True},
    "modelcontextprotocol": {"trust": "known",     "tier": 2, "sandbox_code": True},
    # community (deferred / opt-in): lobehub, browse.sh, clawhub -> untrusted.
}
DEFAULT_REPUTATION = {"trust": "untrusted", "tier": 3, "sandbox_code": True}


# -- Dataclasses --

@dataclass
class IndexEntry:
    name: str
    description: str
    tags: list = field(default_factory=list)
    repo: str = ""
    identifier: str = ""
    path: str = ""
    source_org: str = ""  # reputation key (index name when repo is absent)

    def as_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description, "tags": self.tags,
            "repo": self.repo, "identifier": self.identifier, "path": self.path,
            "source_org": self.source_org,
        }


@dataclass
class Candidate:
    entry: IndexEntry
    reputation: dict
    score: float

    def as_dict(self) -> dict:
        return {
            "name": self.entry.name,
            "score": round(self.score, 3),
            "trust": self.reputation.get("trust"),
            "tier": self.reputation.get("tier"),
            "sandbox_code": self.reputation.get("sandbox_code"),
            "repo": self.entry.repo,
            "identifier": self.entry.identifier,
            "source_org": self.entry.source_org,
            "description": self.entry.description[:160],
        }


@dataclass
class VetResult:
    name: str
    trust: str
    tier: int
    verdict: str = ""
    vaulted: bool = False
    vault_path: str = ""
    sandboxed: bool = False
    sandbox_status: str = ""
    status: str = ""  # approved | blocked | awaiting_confirmation | reused | error
    degraded: bool = False
    warning: str = ""
    command_preview: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name, "trust": self.trust, "tier": self.tier,
            "verdict": self.verdict, "vaulted": self.vaulted,
            "vault_path": self.vault_path, "sandboxed": self.sandboxed,
            "sandbox_status": self.sandbox_status, "status": self.status,
            "degraded": self.degraded, "warning": self.warning,
            "command_preview": self.command_preview, "error": self.error,
        }


# -- Config reading (stdlib-only; no PyYAML) --

def _read_discovery_config(path: Path = CONFIG_PATH) -> dict:
    """Parse the indented `skill_discovery:` block. Supports scalar keys and a
    single-line inline list for `allowlist_indexes`. Nested `source_reputation`
    overrides are not parsed here -- the in-code SOURCE_REPUTATION map applies."""
    result: dict = {}
    if not path.is_file():
        return result
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    in_block = False
    for line in lines:
        if not in_block:
            if re.match(r"^skill_discovery:\s*$", line):
                in_block = True
            continue
        if line.startswith((" ", "\t")):
            m = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*)$", line)
            if not m:
                continue
            key, raw = m.group(1), re.sub(r"\s+#.*$", "", m.group(2)).strip()
            if raw.startswith("[") and raw.endswith("]"):
                result[key] = [v.strip().strip("\"'") for v in raw[1:-1].split(",") if v.strip()]
            elif raw:
                result[key] = raw.strip("\"'")
        elif line.strip():
            break  # dedent to a new top-level key ends the block
    return result


def _allowlist() -> list:
    cfg = _read_discovery_config()
    val = cfg.get("allowlist_indexes")
    if isinstance(val, list) and val:
        return val
    return list(DEFAULT_ALLOWLIST)


def _top_k() -> int:
    cfg = _read_discovery_config()
    try:
        return int(cfg.get("top_k", DEFAULT_TOP_K))
    except (TypeError, ValueError):
        return DEFAULT_TOP_K


def _repo_discovery_allowed(repo: str) -> bool:
    """Per-repo gate: external skill discovery is on unless the repo's
    `.hermes-github.yaml` sets `skill_discovery: local-only`. A missing file or
    key means allow (default external)."""
    val = _read_flat_yaml_value(Path(repo) / ".hermes-github.yaml",
                                "skill_discovery")
    return val != "local-only"


# -- Reputation --

def reputation_for(*hints: str) -> dict:
    """Map an entry's repo/source/index-key to a reputation policy via substring
    match (handles plural org names, e.g. 'anthropics/skills' -> 'anthropic')."""
    blob = " ".join(h for h in hints if h).lower()
    for org, policy in SOURCE_REPUTATION.items():
        if org in blob:
            return dict(policy)
    return dict(DEFAULT_REPUTATION)


# -- Index normalization (heterogeneous schemas -> IndexEntry) --

def _adapt_flat(raw: list, source_key: str) -> list:
    """Anthropic/HuggingFace flat shape: list of
    {name, description, repo, path, identifier, tags, source}."""
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("identifier")
        if not name:
            continue
        out.append(IndexEntry(
            name=str(name),
            description=str(item.get("description", "")),
            tags=[str(t) for t in item.get("tags", []) if isinstance(t, (str, int))],
            repo=str(item.get("repo") or ""),
            identifier=str(item.get("identifier") or name),
            path=str(item.get("path") or ""),
            source_org=str(item.get("repo") or item.get("source") or source_key),
        ))
    return out


def _adapt_lobehub(raw: dict, source_key: str) -> list:
    """LobeHub nested shape: {agents: [{author, identifier, meta:{description,tags,title}}]}."""
    out = []
    for agent in raw.get("agents", []):
        if not isinstance(agent, dict):
            continue
        meta = agent.get("meta", {}) if isinstance(agent.get("meta"), dict) else {}
        ident = agent.get("identifier")
        name = meta.get("title") or ident
        if not name:
            continue
        out.append(IndexEntry(
            name=str(name),
            description=str(meta.get("description", "")),
            tags=[str(t) for t in meta.get("tags", []) if isinstance(t, (str, int))],
            repo=str(agent.get("author") or ""),
            identifier=str(ident or name),
            path="",
            source_org=str(agent.get("author") or source_key),
        ))
    return out


def _load_index(path: Path, source_key: str) -> list:
    """Load + normalize one cached index file. Skips empty/unreadable files."""
    try:
        if path.stat().st_size <= 2:  # e.g. an empty "[]"
            return []
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict) and "agents" in raw:
        return _adapt_lobehub(raw, source_key)
    if isinstance(raw, list):
        return _adapt_flat(raw, source_key)
    return []


def _index_files_for(key: str) -> list:
    """Cache files matching an allowlist key (e.g. 'anthropics' -> anthropics_*.json)."""
    if not INDEX_CACHE_DIR.exists():
        return []
    return sorted(INDEX_CACHE_DIR.glob(f"{key}*.json"))


def load_allowlist_indexes(allowlist: Optional[list] = None) -> list:
    """Load + normalize every cached index on the curated allowlist."""
    allowlist = allowlist if allowlist is not None else _allowlist()
    entries: list = []
    for key in allowlist:
        for fp in _index_files_for(key):
            entries.extend(_load_index(fp, key))
    return entries


# -- Live index building (refresh): clone -> walk SKILL.md -> cache --

_FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_BLOCK_SCALAR = {">", ">-", ">+", "|", "|-", "|+"}


def _parse_frontmatter(text: str) -> Optional[dict]:
    """Pull name/description/tags from a SKILL.md frontmatter block. Stdlib-only,
    handles inline scalars, YAML folded/literal block scalars (`>-`, `|`), and
    both inline (`[a, b]`) and block (`- a`) tag lists."""
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end == -1:
        return None
    lines = text[3:end].split("\n")
    fields: dict = {}
    i, n = 0, len(lines)
    while i < n:
        m = _FM_KEY_RE.match(lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in _BLOCK_SCALAR:  # folded/literal scalar: gather indented lines
            i += 1
            buf = []
            while i < n and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            fields[key] = " ".join(b for b in buf if b)
        elif not val and key == "tags":  # block list
            i += 1
            items = []
            while i < n and re.match(r"^\s*-\s+", lines[i]):
                items.append(re.sub(r"^\s*-\s+", "", lines[i]).strip().strip("\"'"))
                i += 1
            fields[key] = items
        else:
            fields[key] = val.strip("\"'")
            i += 1
    if "name" not in fields:
        return None
    tags = fields.get("tags", [])
    if isinstance(tags, str):
        tags = ([t.strip().strip("\"'") for t in tags.strip("[]").split(",") if t.strip()]
                if tags.startswith("[") else [])
    desc = fields.get("description", "")
    return {"name": str(fields["name"]),
            "description": desc if isinstance(desc, str) else "",
            "tags": tags}


def _is_plugin_path(rel: str) -> bool:
    """A skill path nested under a plugin dir (the non-canonical bundled copy)."""
    return "plugins/" in rel.replace("\\", "/")


def _build_index_for_repo(repo: str, scan_subdir: str = "") -> tuple:
    """Shallow-clone `repo`, walk its SKILL.md files, and return (entries, error)
    as flat-schema dicts ready to cache. Never executes anything it fetches."""
    url = f"https://github.com/{repo}.git" if "://" not in repo else repo
    tmp = Path(tempfile.mkdtemp(prefix="hermes-index-"))
    dest = tmp / "repo"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True, text=True, timeout=180,
        )
        if proc.returncode != 0:
            return [], f"git clone failed: {proc.stderr.strip()[-200:]}"
        root = dest / scan_subdir if scan_subdir else dest
        if not root.exists():
            return [], f"scan path {scan_subdir!r} not found in {repo}"
        # Some repos (microsoft, aws) ship the same skill twice -- standalone and
        # bundled inside a plugin dir. Dedupe by name, preferring the canonical
        # standalone copy (path without a /plugins/ segment) so a skill never
        # burns two discovery slots. Plugin-only skills have no collision and stay.
        by_name = {}
        for sk in sorted(root.rglob("SKILL.md")):
            fm = _parse_frontmatter(sk.read_text(encoding="utf-8", errors="replace"))
            if not fm:
                continue
            rel = str(sk.parent.relative_to(dest))
            entry = {
                "name": fm["name"],
                "description": fm["description"],
                "tags": fm["tags"],
                "repo": repo,
                "path": rel,
                "identifier": f"{repo}/{rel}",
            }
            prev = by_name.get(fm["name"])
            if prev is None or (_is_plugin_path(prev["path"]) and not _is_plugin_path(rel)):
                by_name[fm["name"]] = entry
        return list(by_name.values()), ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], f"clone/walk failed: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _write_index_cache(key: str, entries: list) -> Path:
    """Atomically write the canonical cache for a key and remove stale siblings."""
    INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    canonical = INDEX_CACHE_DIR / f"{key}_index.json"
    tmp = canonical.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    tmp.replace(canonical)
    for stale in INDEX_CACHE_DIR.glob(f"{key}*.json"):
        if stale != canonical:
            stale.unlink()
    return canonical


# -- Discovery --

# Filler words carry no discriminating signal and inflate generic skills' scores
# (e.g. "xlsx" matching "a"/"for"/"in"). Dropped from both task and entry words.
_STOPWORDS = {
    "a", "an", "the", "for", "in", "of", "to", "and", "or", "on", "with", "this",
    "that", "you", "your", "it", "is", "are", "be", "as", "at", "by", "from",
    "use", "using", "used", "when", "any", "all", "into", "via", "if", "but",
    # Generic task-framing verbs/nouns: they appear in almost every task phrasing
    # ("add X", "build the Y", "integration with Z") and match too many skills.
    # IDF weighting downweights them too, but stoplisting them is a cheap backstop
    # so they never even register as overlap.
    "add", "create", "build", "make", "implement", "setup", "integrate",
    "integration", "update", "write", "new", "need", "want", "get",
}


def _entry_words(entry: IndexEntry) -> set:
    """Normalized bag of words for an index entry (name + description + tags),
    stopwords removed."""
    words: set = set()
    for tag in entry.tags:
        words.update(tag.lower().split("-"))
        words.add(tag.lower())
    words.update(_WORD_RE.findall(entry.description.lower()))
    words.update(_WORD_RE.findall(entry.name.lower()))
    return words - _STOPWORDS


def _compute_idf(entries: list) -> dict:
    """Inverse document frequency over the index corpus. A term in few skills
    (e.g. 'firestore') gets a high weight; a term in many skills (e.g. 'backend')
    trends to ~0. This is what stops two generic-word matches from outranking a
    single on-topic, distinctive-term match."""
    n = len(entries)
    df: dict = {}
    for entry in entries:
        for word in _entry_words(entry):
            df[word] = df.get(word, 0) + 1
    # log((N+1)/(df+1)): always >= 0, and 0 for a term present in every entry.
    return {word: math.log((n + 1) / (count + 1)) for word, count in df.items()}


def _score_entry(task_words: set, entry: IndexEntry,
                 idf: Optional[dict] = None) -> float:
    """Relevance score for an entry against a task. With an IDF map (the normal
    path from discover()), score = summed IDF weight of the overlapping terms,
    normalized by the task's total IDF mass — so a rare on-topic match dominates
    coincidental filler matches. Without an IDF map, falls back to the legacy flat
    overlap ratio."""
    overlap = task_words & _entry_words(entry)
    if not overlap:
        return 0.0
    if idf is None:
        return len(overlap) / max(len(task_words), 1)
    weight = sum(idf.get(w, 0.0) for w in overlap)
    total = sum(idf.get(w, 0.0) for w in task_words) or 1.0
    return weight / total


def discover(task: str, repo: Optional[str] = None, top_k: Optional[int] = None,
             engine: Optional[str] = None, allowlist: Optional[list] = None) -> list:
    """Rank curated-allowlist skills against a task. Best-effort: returns [] if
    no index loads, never blocks a dispatch. No writes."""
    top_k = top_k if top_k is not None else _top_k()
    if repo and not _repo_discovery_allowed(repo):
        return []  # repo opted into local-only skills; fail-open downstream
    entries = load_allowlist_indexes(allowlist)
    if not entries:
        return []
    task_words = set(_WORD_RE.findall(task.lower())) - _STOPWORDS
    idf = _compute_idf(entries)
    scored = []
    for entry in entries:
        score = _score_entry(task_words, entry, idf)
        if score <= 0:
            continue
        rep = reputation_for(entry.repo, entry.source_org)
        scored.append(Candidate(entry=entry, reputation=rep, score=score))
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:top_k]


# -- Vet + vault (reuses the #6 ingestion pipeline) --

def _safe_name(entry: IndexEntry) -> str:
    base = entry.name or entry.identifier or "skill"
    name = _SAFE_NAME_RE.sub("-", base).strip("-._")
    return name or "skill"


def _fetch_skill(entry: IndexEntry) -> tuple:
    """Clone the entry's repo (shallow) and return the SKILL subdir as a local
    path for ingestion. Returns (path, tempdir_to_clean, error). Never executes."""
    if not entry.repo:
        return None, None, "entry has no repo coordinate to fetch"
    url = f"https://github.com/{entry.repo}.git" if "://" not in entry.repo else entry.repo
    tmp = Path(tempfile.mkdtemp(prefix="hermes-discover-"))
    dest = tmp / "repo"
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None, f"git clone failed: {e}"
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None, f"git clone failed: {proc.stderr.strip()[-300:]}"
    subdir = (dest / entry.path) if entry.path else dest
    if not subdir.exists():
        shutil.rmtree(tmp, ignore_errors=True)
        return None, None, f"path {entry.path!r} not found in {entry.repo}"
    return subdir, tmp, ""


def _ships_code(path: Path) -> bool:
    for p in path.rglob("*"):
        if p.is_file() and p.suffix.lower() in EXECUTABLE_EXTENSIONS:
            return True
    return False


def _already_vaulted(name: str) -> bool:
    entry = load_registry().get(name)
    return entry is not None and entry.status == "approved"


def _sandbox_check(name: str, tier: int) -> tuple:
    """Smoke-probe a vaulted skill's shipped code in the sandbox (lock-in, from
    the vault). Returns (sandboxed: bool, status: str)."""
    run_args = SimpleNamespace(
        from_vault=name, source=None, cmd="ls -la",
        image=None, tier=tier, timeout=120,
        allow_unvaulted=False, dry_run=False,
    )
    try:
        result, _code = container_runner.run_sandboxed(run_args)
    except Exception as e:  # never let a sandbox hiccup break vetting
        return False, f"sandbox error: {e}"
    return (result.status in ("success", "dry-run")), result.status


def vet_candidate(cand: Candidate, confirm: bool = False, dry_run: bool = False,
                  engine: Optional[str] = None) -> VetResult:
    """Fetch -> audit -> (reputation-gated) vault -> (Tier-gated) sandbox. Reuses
    skill_ingest.ingest() for the audit+vault core; layers the reputation gate on
    top by auto-supplying confirm only for trusted sources."""
    name = _safe_name(cand.entry)
    trust = cand.reputation.get("trust", "untrusted")
    rep_tier = int(cand.reputation.get("tier", 3))

    # Reuse without refetch when an approved copy is already current.
    if _already_vaulted(name):
        return VetResult(name=name, trust=trust, tier=rep_tier, status="reused",
                         vaulted=True, verdict="(cached)",
                         vault_path=str(VAULT_DIR / name),
                         warning="already approved in the vault")

    if dry_run:
        preview = (f"python3 skill_discovery.py vet --task '<task>' --confirm  "
                   f"# would fetch+audit+vault {name!r} ({trust})")
        return VetResult(name=name, trust=trust, tier=rep_tier, status="dry-run",
                         command_preview=preview,
                         warning=f"dry-run: {trust} source {name!r} would be vetted")

    subdir, tmp, err = _fetch_skill(cand.entry)
    if err:
        return VetResult(name=name, trust=trust, tier=rep_tier, status="error", error=err)

    try:
        # Reputation gate: trusted sources auto-vault on a clean audit (we supply
        # confirm); known/untrusted require the operator's --confirm.
        auto_confirm = confirm or (trust == "trusted")
        # subdir is a temp checkout we cloned from cand.entry.repo (verified remote
        # provenance), so we pass trusted_local to let ingest accept the local path.
        report, code = skill_ingest.ingest(
            str(subdir), name, cand.entry.source_org, auto_confirm,
            static_only=False, engine=engine, trusted_local=True,
        )
        degraded = code == 3
        result = VetResult(
            name=name, trust=trust, tier=rep_tier, verdict=report.verdict,
            vaulted=report.vaulted, vault_path=report.vault_path,
            status=report.status, degraded=degraded,
            warning=report.warning, command_preview=report.command_preview,
            error=report.error,
        )
        if report.status == "blocked" or not report.vaulted:
            return result

        # Code sandbox: known/untrusted shipped code must pass a sandboxed probe.
        if cand.reputation.get("sandbox_code") and _ships_code(subdir):
            sandboxed, status = _sandbox_check(name, rep_tier)
            result.sandboxed = sandboxed
            result.sandbox_status = status
        return result
    finally:
        if tmp and Path(tmp).exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _vet_exit_code(results: list) -> int:
    if any(r.status in ("blocked",) for r in results):
        return 1
    if any(r.status == "awaiting_confirmation" for r in results):
        return 1
    if any(r.degraded for r in results):
        return 3
    return 0


# -- Injection (per-harness) --

def _read_skill_body(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            text = text[end + 3:]
    return text.strip()


def injection_payload(vaulted_names: list) -> str:
    """Concatenate the SKILL.md bodies of approved vaulted skills."""
    registry = load_registry()
    parts = []
    for name in vaulted_names:
        entry = registry.get(name)
        if entry is None or entry.status != "approved":
            continue
        base = Path(entry.vaulted_path) if entry.vaulted_path else (VAULT_DIR / name)
        skill_md = base / "SKILL.md"
        if not skill_md.exists():
            found = list(base.rglob("SKILL.md"))
            if not found:
                continue
            skill_md = found[0]
        body = _read_skill_body(skill_md)
        if body:
            parts.append(f"## Skill: {name}\n\n{body}")
    return "\n\n---\n\n".join(parts)


def inject_for_harness(engine: str, payload: str) -> dict:
    """Map an injection payload to the per-harness mechanism. Mirrors SOUL.md."""
    eng = resolve_engine(engine)
    if not payload:
        return {"engine": eng, "args": [], "note": "no approved skills to inject"}
    if eng == "claude-code":
        return {"engine": eng, "args": ["--append-system-prompt", payload],
                "mechanism": "append-system-prompt"}
    if eng == "antigravity":
        return {"engine": eng, "prompt_prefix": payload, "mechanism": "prompt-prepend"}
    if eng == "opencode":
        tmp = Path(tempfile.mkdtemp(prefix="hermes-inject-")) / "skills.md"
        tmp.write_text(payload, encoding="utf-8")
        return {"engine": eng, "args": ["-f", str(tmp)], "context_file": str(tmp),
                "mechanism": "context-file"}
    return {"engine": eng, "args": [], "note": "unknown engine"}


# -- Refresh (documented weekly cron; never auto-registered) --

def cmd_refresh(args) -> int:
    """Report (and, with --confirm, perform) a re-pull of the curated indexes plus
    a vaulted-skill update check. Network-tolerant: a failed pull keeps the stale
    cache (degraded). The actual upstream-pull wiring is intentionally
    conservative -- the dry-run path is the supported live verification."""
    allowlist = _allowlist()
    do_pull = bool(args.confirm) and not bool(args.dry_run)
    degraded = False
    planned = []
    for key in allowlist:
        files = _index_files_for(key)
        rec = {
            "index": key,
            "repo": INDEX_SOURCES.get(key, ("", ""))[0],
            "cached_files": [f.name for f in files],
            "status": "cached" if files else "no-cache",
        }
        if do_pull and key in INDEX_SOURCES:
            repo, subdir = INDEX_SOURCES[key]
            entries, err = _build_index_for_repo(repo, subdir)
            if err or not entries:
                # Network-tolerant: keep the stale cache, mark degraded.
                degraded = True
                rec["status"] = "pull-failed (kept stale cache)"
                rec["error"] = err or "no SKILL.md entries found"
            else:
                path = _write_index_cache(key, entries)
                rec["status"] = "refreshed"
                rec["entries"] = len(entries)
                rec["cached_files"] = [path.name]
        elif do_pull and key not in INDEX_SOURCES:
            rec["status"] = rec["status"] + " (no live source wired)"
        planned.append(rec)

    # Vaulted-skill update check: approved entries from curated origins.
    registry = load_registry()
    curated_orgs = list(SOURCE_REPUTATION.keys())
    update_candidates = []
    for name, entry in registry.items():
        if entry.status != "approved":
            continue
        origin_blob = f"{entry.origin}".lower()
        if any(org in origin_blob for org in curated_orgs):
            update_candidates.append({"name": name, "origin": entry.origin,
                                      "sha256": entry.sha256[:12]})

    if do_pull:
        note = ("Re-pulled live sources (clone -> walk SKILL.md -> cache). "
                "Keys without a wired source in INDEX_SOURCES kept their snapshot. "
                "Vaulted-skill updates still run via vetted_vault update.")
    else:
        note = ("dry-run: no indexes re-pulled, no vault changes. "
                "Re-run with --confirm to live-pull wired sources "
                "(anthropics/google/firebase) and run vaulted-skill updates.")
    result = {
        "action": "refresh",
        "dry_run": bool(args.dry_run),
        "pulled": do_pull,
        "degraded": degraded,
        "allowlist": allowlist,
        "planned_indexes": planned,
        "vaulted_update_candidates": update_candidates,
        "note": note,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"[refresh] pulled={do_pull} dry_run={result['dry_run']}  allowlist={allowlist}")
        for p in planned:
            extra = f" ({p['entries']} entries)" if p.get("entries") else ""
            print(f"  {p['index']}: {p['status']}{extra} {p['cached_files']}")
        if update_candidates:
            print(f"  vaulted update candidates ({len(update_candidates)}):")
            for u in update_candidates:
                print(f"    {u['name']} ({u['origin']}) {u['sha256']}")
        else:
            print("  vaulted update candidates: none")
        print(f"  {result['note']}")
    return 3 if degraded else 0


# -- Subcommand handlers --

def cmd_discover(args) -> int:
    cands = discover(args.task, repo=args.repo, engine=args.engine)
    payload = {"task": args.task, "count": len(cands),
               "candidates": [c.as_dict() for c in cands]}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if not cands:
            print("No remote skill candidates (fail-open to local-only).")
        else:
            print(f"{len(cands)} candidate(s) for: {args.task}")
            for c in cands:
                d = c.as_dict()
                print(f"  [{d['trust']}] {d['name']} (score {d['score']}, "
                      f"tier {d['tier']}, sandbox={d['sandbox_code']}) <- {d['repo']}")
    return 0


def cmd_vet(args) -> int:
    cands = discover(args.task, repo=args.repo, engine=args.engine)
    if not cands:
        msg = {"task": args.task, "status": "ok", "results": [],
               "note": "no remote candidates (fail-open to local-only)"}
        print(json.dumps(msg, indent=2) if args.json
              else "No remote candidates (fail-open to local-only).")
        return 0
    targets = cands if args.all else cands[:1]
    results = [vet_candidate(c, confirm=args.confirm, dry_run=args.dry_run,
                             engine=args.engine) for c in targets]
    code = _vet_exit_code(results)
    if args.json:
        print(json.dumps({"task": args.task, "results": [r.as_dict() for r in results]},
                         indent=2))
    else:
        for r in results:
            print(f"[{r.status}] {r.name} ({r.trust}, tier {r.tier}) verdict={r.verdict} "
                  f"vaulted={r.vaulted} sandboxed={r.sandboxed}")
            if r.warning:
                print(f"  {r.warning}")
            if r.command_preview:
                print(f"  $ {r.command_preview}")
            if r.error:
                print(f"  error: {r.error}", file=sys.stderr)
    return code


def cmd_inject(args) -> int:
    spec = inject_for_harness(args.engine, injection_payload([args.name]))
    if args.json:
        print(json.dumps(spec, indent=2))
    else:
        print(f"[inject] engine={spec['engine']} mechanism={spec.get('mechanism', 'n/a')}")
        if spec.get("context_file"):
            print(f"  context_file: {spec['context_file']}")
        if spec.get("args"):
            print(f"  args: {spec['args'][0]} <payload {len(str(spec['args'][-1]))} chars>")
        if spec.get("note"):
            print(f"  {spec['note']}")
    return 0


# -- Main --

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dynamic skill discovery + reputation-gated injection (#11)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_engine(p):
        p.add_argument("--engine", default=None,
                       choices=["claude-code", "antigravity", "opencode"],
                       help="Coding harness (default: config coding.default_engine)")
        p.add_argument("--json", action="store_true", help="Emit JSON")

    p_disc = sub.add_parser("discover", help="Rank curated-allowlist skills for a task (no writes)")
    p_disc.add_argument("--task", required=True, help="Task description")
    p_disc.add_argument("--repo", default=None, help="Repository path for context")
    add_engine(p_disc)
    p_disc.set_defaults(func=cmd_discover)

    p_vet = sub.add_parser("vet", help="Discover + fetch + audit + (gated) vault + sandbox")
    p_vet.add_argument("--task", required=True, help="Task description")
    p_vet.add_argument("--repo", default=None, help="Repository path for context")
    p_vet.add_argument("--all", action="store_true", help="Vet all top-K candidates (default: top 1)")
    p_vet.add_argument("--confirm", action="store_true",
                       help="Confirm vaulting a known/untrusted source after review")
    p_vet.add_argument("--dry-run", action="store_true", help="Plan only; no fetch/audit/vault")
    add_engine(p_vet)
    p_vet.set_defaults(func=cmd_vet)

    p_inj = sub.add_parser("inject", help="Emit the per-harness injection spec for a vaulted skill")
    p_inj.add_argument("--name", required=True, help="Approved vault entry name")
    add_engine(p_inj)
    p_inj.set_defaults(func=cmd_inject)

    p_ref = sub.add_parser("refresh", help="Re-pull curated indexes + vaulted update check")
    p_ref.add_argument("--confirm", action="store_true", help="Apply re-pull + vault updates")
    p_ref.add_argument("--dry-run", action="store_true", help="Report only; no writes")
    add_engine(p_ref)
    p_ref.set_defaults(func=cmd_refresh)

    args = parser.parse_args()
    if hasattr(args, "engine"):
        args.engine = resolve_engine(args.engine)
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
