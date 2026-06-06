#!/usr/bin/env python3
"""GitHub-Integrated Backlog Management — Phases 1 & 2.

Makes GitHub Issues the canonical backlog. This tool initializes the namespaced
label schema, classifies backlog metadata (Type/Severity/Effort/Risk/Impact/
Confidence), drafts a context-rich issue body (RFC section 4 template), humanizes
the prose, and creates or enriches issues via the gh CLI.

Phase 2 adds the nightly triage engine (`triage`): it sweeps a repo's open
issues, finds the untriaged ones (no `type:*` label, or carrying
`backlog:needs-triage`), classifies + rewrites each to the section-4 template
with read-only codebase research, and applies the result via the same autonomy
ladder (gated → digest; --confirm/push-draft/full → edit + groom comment +
`backlog:groomed`). Bounded per run by --limit. Never closes or merges.

Opt-in is per-repo: a `.hermes-backlog.yaml` with `enabled: true` must exist in
the repository root, otherwise every mutating subcommand is bypassed (exit 4).

Remote-mutating actions (init-labels, create, enrich) respect a per-project
autonomy setting, mirroring github_lifecycle.py. Precedence:
    --autonomy flag > <repo>/.hermes-backlog.yaml > config.yaml github_backlog
    > hard default "gated".
In "gated" mode a mutation requires --confirm; otherwise the tool returns an
"awaiting_confirmation" preview without touching the remote. --dry-run always
previews and never mutates.

This tool only ever CREATES or ENRICHS issues. It never closes or merges.
Issue bodies never include a Co-Authored-By trailer (author is the repository owner).

Usage:
    python3 github_backlog.py init-labels --repo /path --confirm
    python3 github_backlog.py create --repo /path --title "..." --task "..." --confirm
    python3 github_backlog.py enrich --repo /path --issue 42 --confirm
    python3 github_backlog.py triage --repo /path --dry-run --json
    python3 github_backlog.py list --repo /path --json
    python3 github_backlog.py status --repo /path --issue 42 --json

Exit codes:
    0  Success / dry-run
    1  Blocked — gated mutation without --confirm (awaiting confirmation)
    2  Invalid arguments / gh or git preflight failure
    3  LLM harness down — degraded (heuristic metadata + template body, issue still usable)
    4  Repo not opted in (.hermes-backlog.yaml missing or enabled != true)
"""

import argparse
import dataclasses
import difflib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Sibling modules (stdlib-only project).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_lifecycle import (  # noqa: E402
    AUTONOMY_LEVELS,
    DEFAULT_AUTONOMY,
    _run,
    _dispatch,
    _extract_message,
    _strip_coauthor,
    _humanize_text,
    _preflight,
    _read_flat_yaml_value,
    build_readonly_dispatch,
)

try:  # metadata classifier — graceful if unavailable
    from dynamic_curator import triage as _triage
except ImportError:  # pragma: no cover
    _triage = None

try:  # harness-routed LLM for grooming dedup-confirm + decomposition — graceful
    from harness_llm import (
        harness_generate, strip_fences, resolve_engine, HarnessUnavailable,
    )
except ImportError:  # pragma: no cover
    harness_generate = None

    class HarnessUnavailable(Exception):
        pass

    def strip_fences(text):
        return text

    def resolve_engine(cli_engine=None):
        return cli_engine or "claude-code"

DISPATCH_LIMIT = 6000

# T-shirt size -> effort label value.
_SIZE_TO_EFFORT = {"S": "S", "M": "M", "L": "L", "XL": "XL"}


# -- Label schema (RFC section 2) --
# (name, 6-hex color without '#', description)
LABEL_SCHEMA = [
    # Type
    ("type:feature", "0e8a16", "Category of work: a new capability"),
    ("type:bug", "d73a4a", "Category of work: a defect fix"),
    ("type:refactor", "fbca04", "Category of work: internal restructuring"),
    ("type:chore", "c2e0c6", "Category of work: maintenance / tooling"),
    ("type:spike", "5319e7", "Category of work: research / investigation"),
    # Severity
    ("severity:critical", "b60205", "Urgency: must fix now"),
    ("severity:high", "d93f0b", "Urgency: high"),
    ("severity:medium", "fbca04", "Urgency: medium"),
    ("severity:low", "0e8a16", "Urgency: low"),
    ("severity:nit", "c5def5", "Urgency: cosmetic / nit"),
    # Effort (LOE, T-shirt)
    ("effort:S", "bfdadc", "Effort: small"),
    ("effort:M", "bfdadc", "Effort: medium"),
    ("effort:L", "bfdadc", "Effort: large"),
    ("effort:XL", "bfdadc", "Effort: extra large (consider decomposition)"),
    # Risk
    ("risk:high", "b60205", "Regression risk: high"),
    ("risk:medium", "fbca04", "Regression risk: medium"),
    ("risk:low", "0e8a16", "Regression risk: low"),
    # Impact
    ("impact:user-visible", "1d76db", "Impact: benefits users directly"),
    ("impact:internal-debt", "5319e7", "Impact: pays down technical debt"),
    ("impact:dev-experience", "0052cc", "Impact: improves developer experience"),
    # Confidence
    ("confidence:high", "0e8a16", "Certainty of files & approach: high"),
    ("confidence:medium", "fbca04", "Certainty of files & approach: medium"),
    ("confidence:low", "d93f0b", "Certainty of files & approach: low"),
    # Status (backlog state machine)
    ("backlog:needs-triage", "ededed", "Backlog state: needs triage"),
    ("backlog:draft-suggestion", "ededed", "Backlog state: agent draft suggestion"),
    ("backlog:groomed", "ededed", "Backlog state: groomed / enriched"),
    ("backlog:blocked", "ededed", "Backlog state: blocked by dependencies"),
    ("backlog:ready", "0e8a16", "Backlog state: ready for implementation"),
]

# Mutually-exclusive backlog state labels. Applying one clears the others so an
# issue never carries two states at once (e.g. needs-triage + groomed).
BACKLOG_STATE_LABELS = {
    "backlog:needs-triage", "backlog:draft-suggestion", "backlog:groomed",
    "backlog:blocked", "backlog:ready",
}


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


@dataclass
class BacklogResult:
    status: str  # created, enriched, labels-synced, awaiting_confirmation,
                 # dry-run, not_opted_in, error
    action: str
    issue_number: Optional[int] = None
    issue_url: str = ""
    labels: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    command_preview: list = field(default_factory=list)
    details: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class TriageReport:
    status: str  # ok, dry-run, awaiting_confirmation, error
    action: str = "triage"
    processed: int = 0
    groomed: int = 0
    awaiting: int = 0
    skipped: int = 0
    items: list = field(default_factory=list)
    details: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class GroomingReport:
    status: str  # ok, dry-run, awaiting_confirmation, error
    action: str = "groom"
    bottlenecks: list = field(default_factory=list)
    cycles: list = field(default_factory=list)
    duplicates: list = field(default_factory=list)
    decompositions: list = field(default_factory=list)
    stale: list = field(default_factory=list)
    applied: list = field(default_factory=list)
    details: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


# -- opt-in + autonomy resolution --

def is_opted_in(repo: str) -> bool:
    v = _read_flat_yaml_value(Path(repo) / ".hermes-backlog.yaml", "enabled")
    return (v or "").lower() == "true"


def project_name(repo: str) -> str:
    return _read_flat_yaml_value(Path(repo) / ".hermes-backlog.yaml",
                                 "project_name") or ""


def _read_global_backlog() -> dict:
    """Parse the indented `github_backlog:` block from the global config.yaml."""
    cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    result = {}
    if not cfg.is_file():
        return result
    try:
        lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return result
    in_block = False
    for line in lines:
        if not in_block:
            if re.match(r'^github_backlog:\s*$', line):
                in_block = True
            continue
        if line.startswith((" ", "\t")):
            m = re.match(r'^\s+([A-Za-z0-9_]+):\s*(.*)$', line)
            if m:
                v = re.sub(r'\s+#.*$', '', m.group(2)).strip().strip('"\'')
                result[m.group(1)] = v
        elif line.strip():
            break
    return result


def _default_triage_limit() -> int:
    try:
        return int(_read_global_backlog().get("triage_limit", "20"))
    except (TypeError, ValueError):
        return 20


def _triage_comment_enabled() -> bool:
    v = _read_global_backlog().get("triage_comment", "true")
    return str(v).lower() != "false"


def _groom_int(key: str, fallback: int) -> int:
    try:
        return int(_read_global_backlog().get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _groom_float(key: str, fallback: float) -> float:
    try:
        return float(_read_global_backlog().get(key, fallback))
    except (TypeError, ValueError):
        return fallback


def _groom_llm_confirm_default() -> bool:
    v = _read_global_backlog().get("groom_llm_confirm_dup", "true")
    return str(v).lower() != "false"


def resolve_autonomy(repo: str, cli_flag: Optional[str]) -> str:
    if cli_flag in AUTONOMY_LEVELS:
        return cli_flag
    v = _read_flat_yaml_value(Path(repo) / ".hermes-backlog.yaml", "autonomy")
    if v in AUTONOMY_LEVELS:
        return v
    g = _read_global_backlog()
    if g.get("autonomy") in AUTONOMY_LEVELS:
        return g["autonomy"]
    return DEFAULT_AUTONOMY


def _gated(autonomy: str, confirm: bool, dry_run: bool) -> bool:
    """True when a mutation must be held back for confirmation."""
    if dry_run:
        return False
    if confirm:
        return False
    return autonomy == "gated"


# -- metadata classification (RFC section 2) --

_BUG_RE = re.compile(r'\b(bug|fix|broken|crash|error|regression|fail(?:ing|ure)?)\b', re.I)
_REFACTOR_RE = re.compile(r'\b(refactor|restructure|clean[\s-]?up|rename|reorganize)\b', re.I)
_CHORE_RE = re.compile(r'\b(chore|bump|upgrade|dependency|deps|tooling|ci|lint|format)\b', re.I)
_SPIKE_RE = re.compile(r'\b(spike|investigate|research|explore|prototype|evaluate)\b', re.I)

_SEV_CRIT_RE = re.compile(r'\b(critical|urgent|security|data\s*loss|outage|p0)\b', re.I)
_SEV_HIGH_RE = re.compile(r'\b(important|high\s*priority|blocking|p1)\b', re.I)
_SEV_LOW_RE = re.compile(r'\b(nice[\s-]?to[\s-]?have|minor|cosmetic|typo|nit)\b', re.I)

_RISK_HIGH_RE = re.compile(r'\b(migration|auth|authentication|payment|database|schema|breaking|delete|drop)\b', re.I)
_RISK_LOW_RE = re.compile(r'\b(doc|docs|comment|test|readme|log(?:ging)?)\b', re.I)

_IMPACT_USER_RE = re.compile(r'\b(user|customer|ui|ux|frontend|feature|api)\b', re.I)
_IMPACT_DEV_RE = re.compile(r'\b(developer|dev[\s-]?experience|dx|tooling|build|ci|lint)\b', re.I)


def _heuristic_facets(text: str) -> dict:
    """Conservative heuristic Type/Severity/Risk/Impact when the LLM is absent."""
    t = text or ""
    if _BUG_RE.search(t):
        ftype = "bug"
    elif _REFACTOR_RE.search(t):
        ftype = "refactor"
    elif _SPIKE_RE.search(t):
        ftype = "spike"
    elif _CHORE_RE.search(t):
        ftype = "chore"
    else:
        ftype = "feature"

    if _SEV_CRIT_RE.search(t):
        severity = "critical"
    elif _SEV_HIGH_RE.search(t):
        severity = "high"
    elif _SEV_LOW_RE.search(t):
        severity = "low"
    else:
        severity = "medium"

    if _RISK_HIGH_RE.search(t):
        risk = "high"
    elif _RISK_LOW_RE.search(t):
        risk = "low"
    else:
        risk = "medium"

    if _IMPACT_USER_RE.search(t):
        impact = "user-visible"
    elif _IMPACT_DEV_RE.search(t):
        impact = "dev-experience"
    else:
        impact = "internal-debt"

    return {"type": ftype, "severity": severity, "risk": risk, "impact": impact}


def classify_metadata(task: str, repo: Optional[str], engine: Optional[str] = None) -> tuple:
    """Return (metadata, exit_code). Effort/confidence reuse dynamic_curator.triage;
    Type/Severity/Risk/Impact via heuristics. exit_code 3 if the LLM harness was down."""
    facets = _heuristic_facets(task)
    effort, confidence, code = "M", "medium", 0

    if _triage is not None:
        try:
            tri, tcode = _triage(task, repo=repo, engine=engine)
            effort = _SIZE_TO_EFFORT.get(tri.get("size", "M"), "M")
            confidence = tri.get("confidence", "medium")
            if confidence not in ("high", "medium", "low"):
                confidence = "medium"
            code = tcode  # 3 when the LLM harness is unavailable
        except Exception:
            code = 3

    metadata = {
        "type": facets["type"],
        "severity": facets["severity"],
        "effort": effort,
        "risk": facets["risk"],
        "impact": facets["impact"],
        "confidence": confidence,
    }
    return metadata, code


def metadata_labels(metadata: dict) -> list:
    return [
        f"type:{metadata['type']}",
        f"severity:{metadata['severity']}",
        f"effort:{metadata['effort']}",
        f"risk:{metadata['risk']}",
        f"impact:{metadata['impact']}",
        f"confidence:{metadata['confidence']}",
    ]


# -- issue body drafting (RFC section 4) --

def _relations_block(metadata: dict, depends_on=None, blocks=None, related=None) -> str:
    payload = {
        "metadata": metadata,
        "depends_on": depends_on or [],
        "blocks": blocks or [],
        "related": related or [],
    }
    return "<!-- relations-metadata\n" + json.dumps(payload, indent=2) + "\n-->"


def parse_relations_metadata(body: str) -> Optional[dict]:
    m = re.search(r'<!--\s*relations-metadata\s*(\{.*?\})\s*-->', body or "",
                  re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _research_sections(task: str, repo: str, engine: str) -> Optional[str]:
    """Use a read-only harness dispatch to research the Technical Context and
    Implementation Guidelines. Returns markdown or None if unavailable."""
    prompt = (
        "You are documenting a backlog issue for this repository. Do NOT edit any "
        "files — read only. For the task below, output GitHub-flavored markdown with "
        "exactly these two sections and nothing else:\n\n"
        "## Technical Context & Research\n"
        "- **Impacted Files:** (list the real files most likely to change)\n"
        "- **Existing Patterns:** (point to a concrete file/function to follow)\n"
        "- **APIs/Libraries Needed:** (note any libraries already used here)\n\n"
        "## Implementation Guidelines & Pitfalls\n"
        "- **Suggested Approach:** (2-4 concrete steps)\n"
        "- **Risks & Regressions:** (what could break)\n"
        "- **Known Gotchas:** (anything subtle in this codebase)\n\n"
        f"Task: {task}"
    )
    out = _dispatch(build_readonly_dispatch(prompt, engine, repo), repo)
    out = _extract_message(out)
    if out and "Technical Context" in out:
        return out
    return None


def _research_objective(title: str, task: str, repo: str, engine: str, metadata: Optional[dict] = None) -> str:
    """Use a read-only harness dispatch to draft a detailed Objective & Business Value section."""
    effort = (metadata or {}).get("effort", "M")
    risk = (metadata or {}).get("risk", "medium")
    severity = (metadata or {}).get("severity", "medium")

    # Determine length and verbosity rules based on effort, risk, and complexity
    if effort == "S":
        length_rule = (
            "Keep the write-up extremely concise: exactly 2 to 4 sentences in a single short paragraph. "
            "Do NOT write multiple paragraphs. Focus on a quick, clear definition of the goal."
        )
    elif effort == "M":
        length_rule = (
            "Keep the write-up concise: exactly 1 to 2 short paragraphs. "
            "Focus clearly on the objective and immediate business value."
        )
    elif effort == "L":
        length_rule = (
            "Write a thorough 2 to 3 paragraph description. "
            "Explain the technical/system motivation, the ultimate goal, and the positive impact on business/operations."
        )
    else:  # XL
        length_rule = (
            "Write a detailed and highly comprehensive multi-paragraph description (3 to 5 paragraphs). "
            "Elaborate on the background context, architectural significance, operational necessity, "
            "and long-term value to developers and non-technical stakeholders."
        )

    if risk == "high" or severity == "critical":
        length_rule += (
            " Since this task is high-risk or critical severity, explicitly highlight the "
            "safety, security, or stability implications of this work."
        )

    prompt = (
        "You are documenting a backlog issue for this repository. Do NOT edit any "
        "files — read only. For the task below, write a description of the Objective and its Business Value. "
        "Detail the problem being solved, the ultimate goal, and the value it brings to the user or system health. "
        "Ensure anyone (both developers and non-technical stakeholders) can understand the content.\n\n"
        f"Length & Verbosity Guideline: {length_rule}\n\n"
        f"Title: {title}\n"
        f"Task Description: {task}\n\n"
        "Output ONLY the description text, with no headers, no intro/outro, and no code fences."
    )
    out = _dispatch(build_readonly_dispatch(prompt, engine, repo), repo)
    return _extract_message(out).strip()


def _default_technical_sections() -> str:
    return (
        "## 🔬 Technical Context & Research\n"
        "- **Impacted Files:** _TBD — identify during triage._\n"
        "- **Existing Patterns:** _TBD._\n"
        "- **APIs/Libraries Needed:** _TBD._\n\n"
        "## ⚠️ Implementation Guidelines & Pitfalls\n"
        "- **Suggested Approach:** _TBD._\n"
        "- **Risks & Regressions:** _TBD._\n"
        "- **Known Gotchas:** _TBD._"
    )


def draft_issue_body(title: str, task: str, metadata: dict, repo: str,
                     engine: str, use_harness: bool, humanize: bool,
                     existing_objective: str = "") -> str:
    """Build the RFC section-4 context-rich markdown body."""
    objective = existing_objective.strip()
    if not objective and use_harness:
        objective = _research_objective(title, task, repo, engine, metadata)
    if not objective:
        objective = (task or title).strip()

    if humanize and objective:
        objective = _humanize_text(objective, "issue", repo)

    technical = None
    if use_harness:
        technical = _research_sections(task or title, repo, engine)
    if not technical:
        technical = _default_technical_sections()

    sec_security = (
        "## 🛡️ Security & Safety Impact\n"
        "- **Touches Authentication/Authorization?** TBD\n"
        "- **Reads/Writes Sensitive User Data?** TBD\n"
        "- **Opens Network/External Sockets?** TBD\n"
        "- *Note for Auditor: if any are Yes, requires mandatory Tier 3 "
        "execution sandboxing.*"
    )
    sec_meta = (
        "### 📊 Metadata Details\n"
        f"* **Type:** `type:{metadata['type']}`\n"
        f"* **Severity:** `severity:{metadata['severity']}`\n"
        f"* **Effort:** `effort:{metadata['effort']}`\n"
        f"* **Risk:** `risk:{metadata['risk']}`\n"
        f"* **Impact:** `impact:{metadata['impact']}`\n"
        f"* **Confidence:** `confidence:{metadata['confidence']}`"
    )

    body = "\n\n".join([
        "## 🎯 Objective & Business Value",
        objective,
        "## 📋 Requirements & Acceptance Criteria\n"
        "- [ ] _Define the concrete requirements and how to validate each._",
        "## ✅ Definition of Done (DoD)\n"
        "- [ ] Code meets architectural standards (preserves existing patterns).\n"
        "- [ ] Tests written and passing.\n"
        "- [ ] No new compiler or linter warnings introduced.\n"
        "- [ ] Verification steps executed successfully.",
        sec_security,
        technical,
        "---",
        sec_meta,
        _relations_block(metadata),
    ])
    return _strip_coauthor(body).strip()


# -- gh helpers --

def _existing_labels(repo: str) -> set:
    rc, out, _ = _run(["gh", "label", "list", "--limit", "200",
                       "--json", "name"], repo, timeout=30)
    if rc != 0:
        return set()
    try:
        return {x.get("name", "") for x in json.loads(out)}
    except json.JSONDecodeError:
        return set()


def _create_issue(repo: str, title: str, body: str, labels: list) -> tuple:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(body)
        tmp.close()
        args = ["gh", "issue", "create", "--title", title,
                "--body-file", tmp.name]
        for lab in labels:
            args += ["--label", lab]
        rc, out, err = _run(args, repo, timeout=120)
    finally:
        os.unlink(tmp.name)
    return rc, out, err


def _edit_issue(repo: str, number: int, body: str, labels: list,
                remove_labels: Optional[list] = None) -> tuple:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(body)
        tmp.close()
        args = ["gh", "issue", "edit", str(number), "--body-file", tmp.name]
        for lab in labels:
            args += ["--add-label", lab]
        for lab in (remove_labels or []):
            args += ["--remove-label", lab]
        rc, out, err = _run(args, repo, timeout=120)
    finally:
        os.unlink(tmp.name)
    return rc, out, err


def _add_labels(repo: str, number: int, labels: list) -> tuple:
    """Add labels to an issue without rewriting its body."""
    cmd = ["gh", "issue", "edit", str(number)]
    for lab in labels:
        cmd += ["--add-label", lab]
    return _run(cmd, repo, timeout=120)


def _issue_number_from_url(url: str) -> Optional[int]:
    m = re.search(r'/issues/(\d+)', url or "")
    return int(m.group(1)) if m else None


def _comment_issue(repo: str, number: int, text: str) -> tuple:
    """Post a humanized comment on an issue (never closes/merges)."""
    text = _humanize_text(text, "comment", repo)
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False,
                                      encoding="utf-8")
    try:
        tmp.write(_strip_coauthor(text).strip())
        tmp.close()
        rc, out, err = _run(["gh", "issue", "comment", str(number),
                             "--body-file", tmp.name], repo, timeout=120)
    finally:
        os.unlink(tmp.name)
    return rc, out, err


# -- shared enrichment core (enrich + triage) --

def _extract_objective(body: str) -> str:
    """Preserve a human-authored Objective section if one already exists."""
    m = re.search(r'##\s*(?:🎯\s*)?Objective[^\n]*\n+(.+?)(?:\n##|\Z)',
                  body or "", re.DOTALL)
    return m.group(1).strip() if m else ""


def _build_enrichment(title: str, task: str, objective: str, repo: str,
                      args, status_label: str) -> tuple:
    """Classify, draft the section-4 body, and compute labels for an enrichment.
    Returns (body, labels, metadata, mcode). Shared by enrich and triage so
    single-issue and batch enrichment stay identical."""
    metadata, mcode = classify_metadata(task, repo, args.engine)
    use_harness = (not args.no_harness) and (not args.dry_run)
    body = draft_issue_body(
        title, task, metadata, repo, args.engine,
        use_harness=use_harness, humanize=not args.no_humanize,
        existing_objective=objective,
    )
    labels = metadata_labels(metadata) + [status_label]
    return body, labels, metadata, mcode


def _list_untriaged(repo: str, limit: int) -> tuple:
    """Return (candidates, error). An open issue is a candidate when it lacks any
    `type:*` label OR carries `backlog:needs-triage`. Cap applied after filtering."""
    rc, out, e = _run(["gh", "issue", "list", "--state", "open", "--limit", "200",
                       "--json", "number,title,body,labels"], repo, timeout=60)
    if rc != 0:
        return [], f"gh issue list failed: {e or out}"
    try:
        issues = json.loads(out)
    except json.JSONDecodeError:
        return [], "could not parse gh issue list output"
    candidates = []
    for it in issues:
        names = [l.get("name", "") for l in it.get("labels", [])]
        has_type = any(n.startswith("type:") for n in names)
        needs_triage = "backlog:needs-triage" in names
        if (not has_type) or needs_triage:
            candidates.append({
                "number": it.get("number"),
                "title": it.get("title", ""),
                "body": it.get("body", "") or "",
                "labels": names,
            })
            if len(candidates) >= limit:
                break
    return candidates, ""


# -- grooming helpers (Phase 3) --

def _list_open_full(repo: str, limit: int) -> tuple:
    """Return (issues, error). One fetch feeds every grooming vector."""
    rc, out, e = _run(["gh", "issue", "list", "--state", "open", "--limit",
                       str(limit), "--json",
                       "number,title,body,labels,createdAt,updatedAt"],
                      repo, timeout=60)
    if rc != 0:
        return [], f"gh issue list failed: {e or out}"
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return [], "could not parse gh issue list output"


def _close_issue(repo: str, number: int, comment: str) -> tuple:
    """Close an issue as 'not planned' with a humanized explanatory comment.
    Never deletes, never merges."""
    text = _strip_coauthor(_humanize_text(comment, "comment", repo)).strip()
    rc, out, err = _run(["gh", "issue", "close", str(number),
                         "--reason", "not planned", "--comment", text],
                        repo, timeout=120)
    return rc, out, err


def _iso_days_ago(iso_str: str) -> int:
    """Whole days between an ISO8601 timestamp and now (UTC). -1 if unparseable."""
    if not iso_str:
        return -1
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return -1


def _label_names(issue: dict) -> list:
    return [l.get("name", "") for l in issue.get("labels", [])]


def _text_norm(title: str, body: str) -> str:
    return (f"{title or ''} {(_extract_objective(body) or (body or '')[:280])}"
            ).lower().strip()


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _llm_chat_json(system: str, user: str, engine: Optional[str] = None):
    """Run a harness-routed LLM chat and parse a JSON object. Returns the parsed
    object, or None when the LLM harness is unavailable (degraded)."""
    if harness_generate is None:
        return None
    try:
        content = harness_generate(user, engine=engine, system=system, timeout=120)
        return json.loads(strip_fences(content).strip())
    except HarnessUnavailable:
        return None
    except (json.JSONDecodeError, KeyError, ValueError):
        return {}


def _llm_confirm_duplicate(a_text: str, b_text: str, engine: Optional[str] = None):
    """Return True/False if the LLM judged the pair, or None when the harness is down."""
    sys_p = ("You judge whether two software backlog items describe the SAME "
             "underlying work. Respond ONLY with JSON: {\"duplicate\": true|false}.")
    user = f"Issue A:\n{a_text}\n\nIssue B:\n{b_text}"
    parsed = _llm_chat_json(sys_p, user, engine)
    if parsed is None:
        return None
    return bool(parsed.get("duplicate", False))


def _llm_decompose(title: str, objective: str, engine: Optional[str] = None):
    """Return a list of {title, scope} sub-issue proposals, or None when down."""
    sys_p = ("You split an oversized software task into 2-4 independent, "
             "bite-sized sub-tasks. Respond ONLY with JSON: "
             "{\"subissues\": [{\"title\": \"...\", \"scope\": \"one sentence\"}]}.")
    user = f"Task: {title}\n\nObjective: {objective}"
    parsed = _llm_chat_json(sys_p, user, engine)
    if parsed is None:
        return None
    subs = parsed.get("subissues", []) if isinstance(parsed, dict) else []
    out = []
    for s in subs[:4]:
        if isinstance(s, dict) and s.get("title"):
            out.append({"title": str(s["title"]).strip(),
                        "scope": str(s.get("scope", "")).strip()})
    return out


# -- subcommand handlers --

def cmd_init_labels(args, repo: str) -> tuple:
    err = _preflight(repo, need_gh=True)
    if err:
        return BacklogResult("error", "init-labels", error=err), 2

    autonomy = resolve_autonomy(repo, args.autonomy)
    schema = LABEL_SCHEMA
    preview = [
        f"gh label create '{name}' --color {color} "
        f"--description '{desc}' --force"
        for (name, color, desc) in schema
    ]

    if _gated(autonomy, args.confirm, args.dry_run):
        return BacklogResult(
            "awaiting_confirmation", "init-labels",
            labels=[n for n, _, _ in schema],
            command_preview=preview,
            details=f"Autonomy is 'gated' ({len(schema)} labels). Re-run with "
                    f"--confirm to sync labels.",
        ), 1

    if args.dry_run:
        return BacklogResult(
            "dry-run", "init-labels",
            labels=[n for n, _, _ in schema],
            command_preview=preview,
            details=f"Would sync {len(schema)} labels.",
        ), 0

    synced, failed = [], []
    for name, color, desc in schema:
        rc, _, e = _run(["gh", "label", "create", name, "--color", color,
                         "--description", desc, "--force"], repo, timeout=30)
        if rc == 0:
            synced.append(name)
        else:
            failed.append(f"{name}: {e}")
    if failed:
        return BacklogResult(
            "error", "init-labels", labels=synced,
            error="; ".join(failed[:5]),
            details=f"Synced {len(synced)}/{len(schema)} labels.",
        ), 2
    return BacklogResult(
        "labels-synced", "init-labels", labels=synced,
        details=f"Synced {len(synced)} labels.",
    ), 0


def cmd_create(args, repo: str) -> tuple:
    if not args.title:
        return BacklogResult("error", "create", error="--title is required"), 2
    task = args.task or args.body or args.title

    err = _preflight(repo, need_gh=True)
    if err:
        return BacklogResult("error", "create", error=err), 2

    autonomy = resolve_autonomy(repo, args.autonomy)
    metadata, mcode = classify_metadata(task, repo, args.engine)

    use_harness = (not args.no_harness) and (not args.dry_run)
    if args.body:
        body = _strip_coauthor(args.body).strip()
    else:
        body = draft_issue_body(
            args.title, task, metadata, repo, args.engine,
            use_harness=use_harness, humanize=not args.no_humanize,
        )
    labels = metadata_labels(metadata) + ["backlog:needs-triage"]
    preview = [
        f"gh issue create --title '{args.title}' --body-file <generated> "
        + " ".join(f"--label {lab}" for lab in labels)
    ]

    if _gated(autonomy, args.confirm, args.dry_run):
        return BacklogResult(
            "awaiting_confirmation", "create", labels=labels, metadata=metadata,
            command_preview=preview,
            details="Autonomy is 'gated'. Re-run with --confirm to create the issue.",
        ), 1

    if args.dry_run:
        return BacklogResult(
            "dry-run", "create", labels=labels, metadata=metadata,
            command_preview=preview,
            details=f"Would create issue '{args.title}' ({len(body)} char body).",
        ), 0 if mcode == 0 else 3

    rc, out, e = _create_issue(repo, args.title, body, labels)
    if rc != 0:
        return BacklogResult("error", "create", labels=labels, metadata=metadata,
                             error=f"gh issue create failed: {e or out}"), 2
    url = out.splitlines()[-1] if out else ""
    num = _issue_number_from_url(url)
    return BacklogResult(
        "created", "create", issue_number=num, issue_url=url,
        labels=labels, metadata=metadata,
        details=f"created issue {('#' + str(num)) if num else ''}: {url}",
    ), 0 if mcode == 0 else 3


def cmd_enrich(args, repo: str) -> tuple:
    if not args.issue:
        return BacklogResult("error", "enrich", error="--issue is required"), 2

    err = _preflight(repo, need_gh=True)
    if err:
        return BacklogResult("error", "enrich", error=err), 2

    rc, out, e = _run(["gh", "issue", "view", str(args.issue),
                       "--json", "title,body,labels"], repo, timeout=30)
    if rc != 0:
        return BacklogResult("error", "enrich",
                             error=f"gh issue view failed: {e or out}"), 2
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return BacklogResult("error", "enrich",
                             error="could not parse gh issue view output"), 2

    title = data.get("title", "")
    old_body = data.get("body", "") or ""
    objective = _extract_objective(old_body)
    task = args.task or objective or title

    current_labels = [l.get("name", "") for l in data.get("labels", [])]

    autonomy = resolve_autonomy(repo, args.autonomy)
    body, labels, metadata, mcode = _build_enrichment(
        title, task, objective, repo, args, "backlog:groomed")
    remove_labels = _conflicting_states(labels, current_labels)
    preview = [
        f"gh issue edit {args.issue} --body-file <generated> "
        + " ".join(f"--add-label {lab}" for lab in labels)
        + "".join(f" --remove-label {lab}" for lab in remove_labels)
    ]

    if _gated(autonomy, args.confirm, args.dry_run):
        return BacklogResult(
            "awaiting_confirmation", "enrich", issue_number=args.issue,
            labels=labels, metadata=metadata, command_preview=preview,
            details="Autonomy is 'gated'. Re-run with --confirm to enrich the issue.",
        ), 1

    if args.dry_run:
        return BacklogResult(
            "dry-run", "enrich", issue_number=args.issue, labels=labels,
            metadata=metadata, command_preview=preview,
            details=f"Would enrich issue #{args.issue} ({len(body)} char body).",
        ), 0 if mcode == 0 else 3

    rc, out, e = _edit_issue(repo, args.issue, body, labels, remove_labels)
    if rc != 0:
        return BacklogResult("error", "enrich", issue_number=args.issue,
                             labels=labels, metadata=metadata,
                             error=f"gh issue edit failed: {e or out}"), 2
    return BacklogResult(
        "enriched", "enrich", issue_number=args.issue, labels=labels,
        metadata=metadata, details=f"enriched issue #{args.issue}",
    ), 0 if mcode == 0 else 3


def _public_item(item: dict) -> dict:
    """Strip internal keys (the prebuilt body) before emitting an item."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def cmd_triage(args, repo: str) -> tuple:
    err = _preflight(repo, need_gh=True)
    if err:
        return TriageReport("error", error=err), 2

    autonomy = resolve_autonomy(repo, args.autonomy)
    candidates, lerr = _list_untriaged(repo, args.limit)
    if lerr:
        return TriageReport("error", error=lerr), 2
    if not candidates:
        return TriageReport(
            "ok", processed=0,
            details="Nothing to triage — no untriaged open issues.",
        ), 0

    items, degraded = [], False
    for c in candidates:
        objective = _extract_objective(c["body"])
        task = objective or c["title"]
        body, labels, metadata, mcode = _build_enrichment(
            c["title"], task, objective, repo, args, "backlog:groomed")
        if mcode == 3:
            degraded = True
        remove_labels = _conflicting_states(labels, c.get("labels", []))
        preview = [
            f"gh issue edit {c['number']} --body-file <generated> "
            + " ".join(f"--add-label {lab}" for lab in labels)
            + "".join(f" --remove-label {lab}" for lab in remove_labels),
            f"gh issue comment {c['number']} --body-file <groom-note>",
        ]
        items.append({
            "number": c["number"],
            "title": c["title"],
            "proposed_labels": labels,
            "remove_labels": remove_labels,
            "metadata": metadata,
            "command_preview": preview,
            "_body": body,
        })

    # Route by the autonomy gate (no writes when held back or dry-run).
    if _gated(autonomy, args.confirm, args.dry_run):
        return TriageReport(
            "awaiting_confirmation", processed=len(items), awaiting=len(items),
            items=[_public_item(i) for i in items],
            details=f"Autonomy is 'gated'. {len(items)} issue(s) ready to triage. "
                    f"Re-run with --confirm to apply.",
        ), 1

    if args.dry_run:
        return TriageReport(
            "dry-run", processed=len(items),
            items=[_public_item(i) for i in items],
            details=f"Would triage {len(items)} issue(s).",
        ), 0 if not degraded else 3

    comment_on = _triage_comment_enabled()
    groomed, results = 0, []
    for i in items:
        n = i["number"]
        rc, out, e = _edit_issue(repo, n, i["_body"], i["proposed_labels"],
                                 i.get("remove_labels"))
        if rc != 0:
            results.append({**_public_item(i), "result": "error",
                            "error": f"gh issue edit failed: {e or out}"})
            continue
        groomed += 1
        rec = {**_public_item(i), "result": "groomed"}
        if comment_on:
            note = ("Automatically groomed and research-enriched by the Backlog "
                    "Triage Engine. Status set to `backlog:groomed`.")
            crc, cout, ce = _comment_issue(repo, n, note)
            if crc != 0:
                rec["error"] = f"comment failed: {ce or cout}"
        results.append(rec)

    failed = len(items) - groomed
    return TriageReport(
        "ok", processed=len(items), groomed=groomed, skipped=failed,
        items=results,
        details=f"Triaged {groomed}/{len(items)} issue(s)"
                + (f" ({failed} failed)" if failed else "") + ".",
    ), 0 if not degraded else 3


def _find_cycles(graph: dict) -> list:
    """Return circular dependency chains in a directed graph (best-effort DFS)."""
    cycles, seen_sigs = [], set()
    color, stack = {}, []

    def dfs(u):
        color[u] = 1  # gray (on stack)
        stack.append(u)
        for v in graph.get(u, ()):  # u blocks v
            c = color.get(v, 0)
            if c == 1 and v in stack:
                chain = stack[stack.index(v):] + [v]
                sig = frozenset(chain)
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    cycles.append(chain)
            elif c == 0:
                dfs(v)
        stack.pop()
        color[u] = 2  # black (done)

    for n in list(graph):
        if color.get(n, 0) == 0:
            dfs(n)
    return cycles


def _vector_bottlenecks(issues: list, min_blocked: int) -> tuple:
    """Rebuild the dependency DAG from relations-metadata; flag heavy blockers
    and circular dependencies. Returns (bottlenecks, cycles)."""
    graph, titles, sev = {}, {}, {}
    for it in issues:
        n = it.get("number")
        titles[n] = it.get("title", "")
        names = _label_names(it)
        sev[n] = next((x.split(":", 1)[1] for x in names
                       if x.startswith("severity:")), "")
        graph.setdefault(n, set())
        rel = parse_relations_metadata(it.get("body", "")) or {}
        for b in rel.get("blocks", []) or []:
            graph[n].add(b)
        for d in rel.get("depends_on", []) or []:
            graph.setdefault(d, set()).add(n)

    bottlenecks = []
    for n, blocked in graph.items():
        if n is None or len(blocked) < min_blocked:
            continue
        needs = sev.get(n, "") not in ("high", "critical")
        bottlenecks.append({
            "number": n,
            "title": titles.get(n, ""),
            "blocks_count": len(blocked),
            "blocked_numbers": sorted(b for b in blocked if b is not None),
            "current_severity": sev.get(n, ""),
            "proposed_label": "severity:high" if needs else "",
            "command_preview": ([f"gh issue edit {n} --add-label severity:high"]
                                if needs else []),
        })
    bottlenecks.sort(key=lambda x: -x["blocks_count"])
    return bottlenecks, _find_cycles(graph)


def _vector_duplicates(issues: list, threshold: float, use_llm: bool,
                       engine: Optional[str] = None) -> tuple:
    """Lexical similarity over title+objective; optional LLM confirm. Returns
    (duplicates, degraded)."""
    norm = [(it.get("number"), it.get("title", ""),
             _text_norm(it.get("title", ""), it.get("body", "")))
            for it in issues]
    dups, degraded = [], False
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            na, ta, xa = norm[i]
            nb, tb, xb = norm[j]
            ratio = _similarity(xa, xb)
            if ratio < threshold:
                continue
            confirmed = None
            if use_llm:
                confirmed = _llm_confirm_duplicate(xa, xb, engine)
                if confirmed is None:
                    degraded = True
                elif confirmed is False:
                    continue  # LLM rejected the lexical candidate
            older, newer = ((na, nb) if (na or 0) <= (nb or 0) else (nb, na))
            older_t = ta if older == na else tb
            newer_t = tb if newer == nb else ta
            closable = bool(confirmed) or (not use_llm and ratio >= 0.95)
            dups.append({
                "older": older, "newer": newer,
                "older_title": older_t, "newer_title": newer_t,
                "similarity": round(ratio, 3),
                "llm_confirmed": confirmed,
                "closable": closable,
                "command_preview": [
                    f"gh issue close {newer} --reason 'not planned' "
                    f"--comment 'Duplicate of #{older}'"],
            })
    return dups, degraded


def _vector_decompose(issues: list, use_llm: bool, engine: Optional[str] = None) -> tuple:
    """Propose (never create) sub-issues for effort:L/XL issues. Returns
    (decompositions, degraded)."""
    out, degraded = [], False
    for it in issues:
        names = _label_names(it)
        eff = next((x.split(":", 1)[1] for x in names
                    if x.startswith("effort:")), "")
        if eff not in ("L", "XL"):
            continue
        n, title = it.get("number"), it.get("title", "")
        objective = _extract_objective(it.get("body", "")) or title
        subs = _llm_decompose(title, objective, engine) if use_llm else []
        if subs is None:
            degraded = True
            out.append({"number": n, "title": title, "effort": eff,
                        "proposed_subissues": [],
                        "note": "LLM harness down — manual decomposition recommended"})
        else:
            out.append({"number": n, "title": title, "effort": eff,
                        "proposed_subissues": subs,
                        "note": "" if subs else "No decomposition suggested"})
    return out, degraded


def _vector_stale(issues: list, stale_days: int, grace_days: int) -> list:
    """Idle-time audit. warn = add backlog:stale + warning (non-destructive);
    close = stale-past-grace (destructive, gated)."""
    out = []
    for it in issues:
        idle = _iso_days_ago(it.get("updatedAt", ""))
        if idle < 0:
            continue
        n, title = it.get("number"), it.get("title", "")
        has_stale = "backlog:stale" in _label_names(it)
        if has_stale and idle >= grace_days:
            out.append({
                "number": n, "title": title, "idle_days": idle, "action": "close",
                "command_preview": [
                    f"gh issue close {n} --reason 'not planned' "
                    f"--comment 'Closing — stale {idle}d past grace.'"],
            })
        elif (not has_stale) and idle >= stale_days:
            out.append({
                "number": n, "title": title, "idle_days": idle, "action": "warn",
                "command_preview": [
                    f"gh issue edit {n} --add-label backlog:stale",
                    f"gh issue comment {n} --body-file <warm-stale-warning>"],
            })
    return out


_WARM_STALE_WARNING = (
    "Heads up — this issue has been quiet for {idle} days, so I've flagged it as "
    "stale. If it's still worth doing, a quick comment or an updated plan will "
    "clear the flag; otherwise it may be closed after the grace window."
)


def cmd_groom(args, repo: str) -> tuple:
    """Weekly grooming sweep (Phase 3): four analysis vectors over open issues,
    one digest, maintenance changes applied through the autonomy ladder."""
    err = _preflight(repo, need_gh=True)
    if err:
        return GroomingReport("error", error=err, details="preflight failed"), 2

    autonomy = resolve_autonomy(repo, args.autonomy)
    issues, lerr = _list_open_full(repo, args.limit)
    if lerr:
        return GroomingReport("error", error=lerr), 2
    if not issues:
        return GroomingReport("ok", details="Nothing to groom — no open issues."), 0

    use_llm = (not args.no_llm_dup) and _groom_llm_confirm_default()
    bottlenecks, cycles, duplicates, decompositions, stale = [], [], [], [], []
    degraded = False
    if not args.skip_bottlenecks:
        bottlenecks, cycles = _vector_bottlenecks(issues, args.bottleneck_min)
    if not args.skip_dedup:
        duplicates, d = _vector_duplicates(issues, args.dup_threshold, use_llm,
                                           args.engine)
        degraded = degraded or d
    if not args.skip_decompose:
        decompositions, d = _vector_decompose(issues, use_llm, args.engine)
        degraded = degraded or d
    if not args.skip_stale:
        stale = _vector_stale(issues, args.stale_days, args.grace_days)

    elevations = [b for b in bottlenecks if b.get("proposed_label")]
    stale_warns = [s for s in stale if s.get("action") == "warn"]
    stale_closes = [s for s in stale if s.get("action") == "close"]
    closable_dups = [d for d in duplicates if d.get("closable")]

    actionable = len(elevations) + len(stale_warns)
    if not args.no_close:
        actionable += len(stale_closes) + len(closable_dups)

    summary = (
        f"{len(issues)} open · {len(bottlenecks)} bottleneck(s), {len(cycles)} "
        f"cycle(s), {len(duplicates)} dup pair(s), {len(decompositions)} "
        f"decomposable, {len(stale)} stale"
    )
    if degraded:
        summary += " · degraded (LLM harness down — lexical/heuristic only)"
    base = dict(bottlenecks=bottlenecks, cycles=cycles, duplicates=duplicates,
                decompositions=decompositions, stale=stale)
    deg_code = 3 if degraded else 0

    if args.dry_run:
        return GroomingReport("dry-run", details=summary, **base), deg_code

    if _gated(autonomy, args.confirm, args.dry_run):
        if actionable:
            return GroomingReport(
                "awaiting_confirmation",
                details=summary + f" · {actionable} change(s) awaiting --confirm",
                **base), 1
        return GroomingReport("ok", details=summary, **base), deg_code

    # -- apply path (--confirm, or push-draft/full autonomy) --
    applied = []

    for b in elevations:
        n = b["number"]
        rc, _o, e = _add_labels(repo, n, ["severity:high"])
        applied.append({"number": n, "action": "elevate-severity",
                        "result": "ok" if rc == 0 else "error",
                        "error": "" if rc == 0 else (e or "edit failed")})

    for s in stale_warns:
        n = s["number"]
        rc, _o, e = _add_labels(repo, n, ["backlog:stale"])
        if rc == 0:
            crc, _co, ce = _comment_issue(
                repo, n, _WARM_STALE_WARNING.format(idle=s["idle_days"]))
            ok = crc == 0
            applied.append({"number": n, "action": "warn-stale",
                            "result": "ok" if ok else "error",
                            "error": "" if ok else (ce or "comment failed")})
        else:
            applied.append({"number": n, "action": "warn-stale",
                            "result": "error", "error": e or "label failed"})

    if not args.no_close:
        for s in stale_closes:
            n = s["number"]
            rc, _o, e = _close_issue(
                repo, n,
                f"Closing this out — idle {s['idle_days']} days, past the stale "
                f"grace window. Reopen anytime if it's still relevant.")
            applied.append({"number": n, "action": "close-stale",
                            "result": "ok" if rc == 0 else "error",
                            "error": "" if rc == 0 else (e or "close failed")})
        for d in closable_dups:
            n = d["newer"]
            rc, _o, e = _close_issue(
                repo, n, f"Closing as a duplicate of #{d['older']}.")
            applied.append({"number": n, "action": "close-duplicate",
                            "result": "ok" if rc == 0 else "error",
                            "error": "" if rc == 0 else (e or "close failed")})

    applied_ok = sum(1 for a in applied if a["result"] == "ok")
    return GroomingReport(
        "ok", applied=applied,
        details=summary + f" · applied {applied_ok}/{len(applied)} change(s)",
        **base), deg_code


def cmd_list(args, repo: str) -> tuple:
    err = _preflight(repo, need_gh=True)
    if err:
        return BacklogResult("error", "list", error=err), 2
    rc, out, e = _run(["gh", "issue", "list", "--state", "open", "--limit", "200",
                       "--json", "number,title,labels"], repo, timeout=30)
    if rc != 0:
        return BacklogResult("error", "list", error=f"gh issue list failed: {e or out}"), 2
    try:
        issues = json.loads(out)
    except json.JSONDecodeError:
        return BacklogResult("error", "list", error="could not parse gh output"), 2
    backlog = []
    for it in issues:
        names = [l.get("name", "") for l in it.get("labels", [])]
        if any(n.startswith("backlog:") for n in names):
            backlog.append({"number": it.get("number"),
                            "title": it.get("title", ""),
                            "labels": names})
    return BacklogResult(
        "ok", "list", details=f"{len(backlog)} backlog issue(s)",
        metadata={"issues": backlog},
    ), 0


def cmd_status(args, repo: str) -> tuple:
    if not args.issue:
        return BacklogResult("error", "status", error="--issue is required"), 2
    err = _preflight(repo, need_gh=True)
    if err:
        return BacklogResult("error", "status", error=err), 2
    rc, out, e = _run(["gh", "issue", "view", str(args.issue),
                       "--json", "number,title,body,labels,url"], repo, timeout=30)
    if rc != 0:
        return BacklogResult("error", "status", error=f"gh issue view failed: {e or out}"), 2
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return BacklogResult("error", "status", error="could not parse gh output"), 2
    names = [l.get("name", "") for l in data.get("labels", [])]
    relations = parse_relations_metadata(data.get("body", "")) or {}
    return BacklogResult(
        "ok", "status", issue_number=data.get("number"),
        issue_url=data.get("url", ""), labels=names,
        metadata={"title": data.get("title", ""), "relations": relations},
        details=f"issue #{data.get('number')}",
    ), 0


# -- output + CLI --

def _emit_triage(report: TriageReport):
    line = f"{report.status.upper()}: triage"
    if report.details:
        line += f" — {report.details}"
    print(line)
    show_preview = report.status in ("awaiting_confirmation", "dry-run")
    for it in report.items:
        print(f"\n#{it.get('number')} {it.get('title', '')}")
        if it.get("proposed_labels"):
            print("  Proposed labels: " + ", ".join(it["proposed_labels"]))
        if it.get("result"):
            print(f"  Result: {it['result']}")
        if it.get("error"):
            print(f"  Error: {it['error']}")
        if show_preview and it.get("command_preview"):
            print("  Would run:")
            for c in it["command_preview"]:
                print(f"    {c}")
    if report.error:
        print(f"Error: {report.error}", file=sys.stderr)


def _emit_groom(report: GroomingReport):
    line = f"{report.status.upper()}: groom"
    if report.details:
        line += f" — {report.details}"
    print(line)
    show_preview = report.status in ("awaiting_confirmation", "dry-run")

    if report.bottlenecks:
        print("\nBottlenecks:")
        for b in report.bottlenecks:
            tail = (f" → propose {b['proposed_label']}"
                    if b.get("proposed_label") else " (already prioritized)")
            print(f"  #{b['number']} blocks {b['blocks_count']} "
                  f"({', '.join('#' + str(x) for x in b['blocked_numbers'])})"
                  f"{tail}")
            if show_preview:
                for c in b.get("command_preview", []):
                    print(f"    {c}")
    if report.cycles:
        print("\nCircular dependencies (flag-only):")
        for chain in report.cycles:
            print("  " + " → ".join("#" + str(x) for x in chain))
    if report.duplicates:
        print("\nDuplicate candidates:")
        for d in report.duplicates:
            conf = {True: "confirmed", False: "rejected",
                    None: "unconfirmed"}[d.get("llm_confirmed")]
            mark = "close" if d.get("closable") else "review"
            print(f"  #{d['newer']} ~ #{d['older']} "
                  f"(sim {d['similarity']}, {conf}) → {mark}")
            if show_preview and d.get("closable"):
                for c in d.get("command_preview", []):
                    print(f"    {c}")
    if report.decompositions:
        print("\nDecomposition proposals (propose-only, never created):")
        for dc in report.decompositions:
            print(f"  #{dc['number']} [{dc['effort']}] {dc['title']}")
            for sub in dc.get("proposed_subissues", []):
                print(f"    - {sub.get('title', '')}")
            if dc.get("note"):
                print(f"    ({dc['note']})")
    if report.stale:
        print("\nStale/decay:")
        for s in report.stale:
            print(f"  #{s['number']} idle {s['idle_days']}d → {s['action']}")
            if show_preview:
                for c in s.get("command_preview", []):
                    print(f"    {c}")
    if report.applied:
        print("\nApplied:")
        for a in report.applied:
            tail = f" ({a['error']})" if a.get("error") else ""
            print(f"  #{a['number']} {a['action']}: {a['result']}{tail}")
    if report.error:
        print(f"Error: {report.error}", file=sys.stderr)


def _emit(result, as_json: bool):
    if as_json:
        print(json.dumps(result.as_dict(), indent=2))
        return
    if isinstance(result, TriageReport):
        _emit_triage(result)
        return
    if isinstance(result, GroomingReport):
        _emit_groom(result)
        return
    line = f"{result.status.upper()}: {result.action}"
    if result.details:
        line += f" — {result.details}"
    print(line)
    if result.labels and result.action in ("create", "enrich", "init-labels"):
        print("Labels: " + ", ".join(result.labels))
    if result.command_preview:
        print("Would run:")
        for c in result.command_preview:
            print(f"  {c}")
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)


MUTATING = {"init-labels", "create", "enrich", "triage", "groom"}
HANDLERS = {
    "init-labels": cmd_init_labels,
    "create": cmd_create,
    "enrich": cmd_enrich,
    "triage": cmd_triage,
    "groom": cmd_groom,
    "list": cmd_list,
    "status": cmd_status,
}


def main():
    parser = argparse.ArgumentParser(
        description="GitHub-Integrated Backlog Management (Phase 1)")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", required=True, help="Project repository path")
    common.add_argument("--json", action="store_true", help="Output as JSON")

    mut = argparse.ArgumentParser(add_help=False)
    mut.add_argument("--autonomy", choices=AUTONOMY_LEVELS, default=None,
                     help="Override the project's autonomy level")
    mut.add_argument("--confirm", action="store_true",
                     help="Confirm the mutation when autonomy is gated")
    mut.add_argument("--dry-run", action="store_true",
                     help="Preview only; never touch the remote")
    mut.add_argument("--engine",
                     choices=["claude-code", "antigravity", "opencode"],
                     default=None,
                     help="Coding engine harness (default: config coding.default_engine)")
    mut.add_argument("--model", default=None,
                     help="Deprecated/ignored; LLM passes route through the coding harness")
    mut.add_argument("--no-harness", action="store_true",
                     help="Skip the read-only harness research pass")
    mut.add_argument("--no-humanize", action="store_true",
                     help="Skip the prose humanizer pass")

    p_il = sub.add_parser("init-labels", parents=[common, mut],
                          help="Create the namespaced label schema (idempotent)")
    p_il.set_defaults(_needs_engine=False)

    p_cr = sub.add_parser("create", parents=[common, mut],
                          help="Author and create a context-rich issue")
    p_cr.add_argument("--title", help="Issue title")
    p_cr.add_argument("--task", help="Raw task description to classify/document")
    p_cr.add_argument("--body", help="Use this raw body instead of drafting")
    p_cr.add_argument("--origin", help="Source/org hint (unused in Phase 1)")

    p_en = sub.add_parser("enrich", parents=[common, mut],
                          help="Re-document an existing thin issue")
    p_en.add_argument("--issue", type=int, help="Issue number to enrich")
    p_en.add_argument("--task", help="Override task description")

    p_tr = sub.add_parser("triage", parents=[common, mut],
                          help="Sweep & enrich untriaged open issues (batch)")
    p_tr.add_argument("--limit", type=int, default=_default_triage_limit(),
                      help="Max untriaged issues to process this run")

    p_gr = sub.add_parser("groom", parents=[common, mut],
                          help="Weekly grooming sweep (bottlenecks/dedup/"
                               "decompose/stale)")
    p_gr.add_argument("--limit", type=int,
                      default=_groom_int("groom_limit", 200),
                      help="Max open issues to scan this sweep")
    p_gr.add_argument("--stale-days", type=int,
                      default=_groom_int("groom_stale_days", 60),
                      help="Idle days before a warm-stale warning")
    p_gr.add_argument("--grace-days", type=int,
                      default=_groom_int("groom_stale_grace_days", 14),
                      help="Extra idle days after backlog:stale before close")
    p_gr.add_argument("--dup-threshold", type=float,
                      default=_groom_float("groom_dup_threshold", 0.85),
                      help="Lexical similarity threshold for dedup")
    p_gr.add_argument("--bottleneck-min", type=int,
                      default=_groom_int("groom_bottleneck_min", 3),
                      help="Min blocked-issue count to flag a bottleneck")
    p_gr.add_argument("--no-close", action="store_true",
                      help="Suppress all closes even when the gate is open")
    p_gr.add_argument("--no-llm-dup", action="store_true",
                      help="Skip the harness-LLM dedup/decompose confirm pass")
    p_gr.add_argument("--skip-bottlenecks", action="store_true",
                      help="Skip dependency bottleneck/cycle detection")
    p_gr.add_argument("--skip-dedup", action="store_true",
                      help="Skip semantic deduplication")
    p_gr.add_argument("--skip-decompose", action="store_true",
                      help="Skip XL/L decomposition proposals")
    p_gr.add_argument("--skip-stale", action="store_true",
                      help="Skip the stale/decay audit")

    p_ls = sub.add_parser("list", parents=[common],
                          help="List opted-in backlog issues (read-only)")

    p_st = sub.add_parser("status", parents=[common],
                          help="Show one issue's parsed metadata (read-only)")
    p_st.add_argument("--issue", type=int, help="Issue number")

    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"Error: repository path does not exist: {repo}", file=sys.stderr)
        sys.exit(2)

    if not is_opted_in(repo):
        result = BacklogResult(
            "not_opted_in", args.command,
            details="This repo is not opted in. Create a .hermes-backlog.yaml "
                    "with `enabled: true` in the repository root to activate "
                    "GitHub backlog management.",
        )
        _emit(result, args.json)
        sys.exit(4)

    if hasattr(args, "engine"):
        args.engine = resolve_engine(args.engine)

    result, code = HANDLERS[args.command](args, repo)
    _emit(result, args.json)
    sys.exit(code)


if __name__ == "__main__":
    main()
