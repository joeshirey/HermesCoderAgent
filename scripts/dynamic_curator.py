#!/usr/bin/env python3
"""Dynamic curator: T-shirt size tasks before dispatch.

Analyzes a task description, assigns S/M/L/XL complexity,
recommends local vs cloud routing, and matches relevant skills.

Usage:
    python3 dynamic_curator.py --task "fix typo in README.md"
    python3 dynamic_curator.py --task "add JWT auth" --repo /path/to/repo
    python3 dynamic_curator.py --task "refactor models" --heuristics-only
    python3 dynamic_curator.py --task "update CSS" --oneline

Exit codes:
    0  Success
    1  Error
    2  Invalid arguments
    3  LLM harness unavailable (heuristics-only result provided)
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from harness_llm import harness_generate, strip_fences, HarnessUnavailable


# -- Config defaults (overridable via ~/.hermes-coder/config.yaml) --

DEFAULT_SKILLS_DIR = str(Path.home() / ".hermes-coder" / "skills")
DEFAULT_MODEL = "gemma4:latest"
CLOUD_MODEL = "gemini-3.5-flash"
LOCAL_SIZES = {"S"}
ALWAYS_CLOUD_KEYWORDS = [
    "security", "authentication", "auth", "cryptography", "encrypt",
    "database migration", "schema change", "migrate", "race condition",
    "concurrent", "async", "deadlock", "csrf", "xss", "injection",
]

TOOL_BUDGETS = {
    "S":  {"max_skills": 0, "max_mcp_tools": 0, "max_turns": 10},
    "M":  {"max_skills": 1, "max_mcp_tools": 3, "max_turns": 15},
    "L":  {"max_skills": 3, "max_mcp_tools": 3, "max_turns": 25},
    "XL": {"max_skills": 3, "max_mcp_tools": 5, "max_turns": 40},
}


# -- Heuristic fast-path --

FILE_PATH_RE = re.compile(
    r'(?:^|[\s,])([a-zA-Z0-9_./\-]+\.[a-zA-Z]{1,5})(?=[\s,;:)]|$)'
)

TRIVIAL_PATTERNS = [
    re.compile(r'\b(fix\s+typo|typo)\b', re.I),
    re.compile(r'\b(rename|bump\s+version|version\s+bump)\b', re.I),
    re.compile(r'\b(fix\s+whitespace|remove\s+unused|add\s+comment)\b', re.I),
    re.compile(r'\b(update\s+import|fix\s+lint|lint\s+fix)\b', re.I),
    re.compile(r'\b(update\s+readme|fix\s+readme)\b', re.I),
]

CSS_PATTERNS = [
    re.compile(r'\b(css|style|tailwind|classname|color|font|margin|padding)\b', re.I),
    re.compile(r'\b(background|border|width|height|flex|grid)\b', re.I),
]

SINGLE_FILE_EDIT_VERBS = re.compile(
    r'\b(fix|update|change|modify|edit|tweak|adjust|correct)\b', re.I
)

COMPLEX_SIGNALS = [
    re.compile(r'\b(implement|build|create|design|architect)\b', re.I),
    re.compile(r'\b(refactor|rewrite|overhaul|redesign|migrate)\b', re.I),
    re.compile(r'\b(integrate|orchestrate|coordinate)\b', re.I),
    re.compile(r'\b(api|endpoint|database|schema|model)\b', re.I),
    re.compile(r'\b(test\s+suite|coverage|e2e|integration\s+test)\b', re.I),
]


def _count_files_mentioned(task: str) -> int:
    return len(FILE_PATH_RE.findall(task))


def _is_trivial(task: str) -> bool:
    return any(p.search(task) for p in TRIVIAL_PATTERNS)


def _is_css_only(task: str) -> bool:
    css_hits = sum(1 for p in CSS_PATTERNS if p.search(task))
    complex_hits = sum(1 for p in COMPLEX_SIGNALS if p.search(task))
    return css_hits >= 2 and complex_hits == 0


def _has_cloud_keywords(task: str) -> bool:
    lower = task.lower()
    return any(kw in lower for kw in ALWAYS_CLOUD_KEYWORDS)


def _count_complex_signals(task: str) -> int:
    return sum(1 for p in COMPLEX_SIGNALS if p.search(task))


def heuristic_analyze(task: str) -> Optional[dict]:
    """Fast-path heuristic analysis. Returns result if confident, None otherwise."""
    file_count = _count_files_mentioned(task)
    signals = []

    if _is_trivial(task):
        signals.append("trivial_verb")
        return {
            "size": "S",
            "confidence": "high",
            "method": "heuristic",
            "reasoning": f"Trivial task detected: {task[:80]}",
            "signals": signals,
        }

    if file_count == 1 and SINGLE_FILE_EDIT_VERBS.search(task):
        complex_count = _count_complex_signals(task)
        if complex_count == 0:
            signals.extend(["single_file", "simple_verb"])
            return {
                "size": "S",
                "confidence": "high",
                "method": "heuristic",
                "reasoning": f"Single-file edit with simple verb",
                "signals": signals,
            }

    if _is_css_only(task) and file_count <= 2:
        signals.append("css_only")
        return {
            "size": "S",
            "confidence": "high",
            "method": "heuristic",
            "reasoning": "CSS/style-only changes detected",
            "signals": signals,
        }

    complex_count = _count_complex_signals(task)
    if complex_count >= 3:
        size = "L" if complex_count >= 4 else "M"
        signals.append("multiple_complex_signals")
        return {
            "size": size,
            "confidence": "medium",
            "method": "heuristic",
            "reasoning": f"{complex_count} complexity signals detected",
            "signals": signals,
        }

    return None


# -- LLM analysis --

TRIAGE_SYSTEM_PROMPT = """You are a task complexity classifier for software development tasks.
Classify tasks as S (Small), M (Medium), L (Large), or XL (Extra Large).

Size definitions:
- S: Single-file modifications, CSS tweaks, typos, regex updates, simple bug fixes
- M: Adding component logic, creating helpers, implementing simple endpoints, 2-3 files
- L: New features, major refactors, multi-file integrations, 4+ files
- XL: Architecture changes, system redesigns, major migrations, 10+ files

Respond ONLY with valid JSON, no markdown fencing:
{"size": "S|M|L|XL", "reasoning": "one sentence", "file_count_estimate": N, "complexity_signals": ["list"]}"""


def llm_analyze(task: str, engine: Optional[str] = None) -> Optional[dict]:
    """LLM-based classification via the active coding harness.
    Returns None if the harness is unavailable."""
    try:
        content = harness_generate(
            task, engine=engine, system=TRIAGE_SYSTEM_PROMPT, timeout=120,
            tier="fast",
        )
    except HarnessUnavailable:
        return None
    try:
        parsed = json.loads(strip_fences(content))
        return {
            "size": parsed.get("size", "M"),
            "confidence": "medium",
            "method": "llm",
            "reasoning": parsed.get("reasoning", ""),
            "signals": parsed.get("complexity_signals", []),
        }
    except (json.JSONDecodeError, KeyError, AttributeError):
        return {"size": "M", "confidence": "low", "method": "llm",
                "reasoning": "LLM response unparseable, defaulting to M", "signals": []}


# -- Skill matching --

def _parse_skill_frontmatter(path: Path) -> Optional[dict]:
    """Extract YAML frontmatter from a SKILL.md file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if not text.startswith("---"):
        return None

    end = text.find("---", 3)
    if end == -1:
        return None

    yaml_block = text[3:end].strip()
    result = {}
    for line in yaml_block.split("\n"):
        line = line.strip()
        if line.startswith("name:"):
            result["name"] = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            result["description"] = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("tags:"):
            tags_str = line.split(":", 1)[1].strip()
            if tags_str.startswith("["):
                tags_str = tags_str.strip("[]")
                result["tags"] = [t.strip().strip('"').strip("'")
                                  for t in tags_str.split(",") if t.strip()]

    if "name" in result:
        result["path"] = str(path.parent.relative_to(Path(DEFAULT_SKILLS_DIR)))
    return result if "name" in result else None


def match_skills(task: str, skills_dir: str = DEFAULT_SKILLS_DIR) -> list[dict]:
    """Match task against skill metadata. Returns top 3 by keyword overlap."""
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        return []

    task_words = set(re.findall(r'[a-z]+', task.lower()))
    matches = []

    for skill_file in skills_path.rglob("SKILL.md"):
        meta = _parse_skill_frontmatter(skill_file)
        if not meta:
            continue

        # Skip harness skills and coordinator skills
        rel = str(skill_file.relative_to(skills_path))
        if rel.startswith("harness/") or rel.startswith("coordinator/"):
            continue

        skill_words = set()
        if "tags" in meta:
            for tag in meta["tags"]:
                skill_words.update(tag.lower().split("-"))
                skill_words.add(tag.lower())
        if "description" in meta:
            skill_words.update(re.findall(r'[a-z]+', meta["description"].lower()))

        overlap = task_words & skill_words
        if overlap:
            score = len(overlap) / max(len(task_words), 1)
            matches.append({
                "name": meta["name"],
                "path": meta.get("path", ""),
                "score": round(score, 2),
            })

    matches.sort(key=lambda x: x["score"], reverse=True)
    return matches[:3]


# -- Routing --

def recommend_routing(size: str, task: str) -> dict:
    if _has_cloud_keywords(task):
        return {
            "engine": "cloud",
            "model": CLOUD_MODEL,
            "reason": "Task contains security/migration keywords requiring cloud-level reasoning",
        }
    if size in LOCAL_SIZES:
        return {
            "engine": "local",
            "model": DEFAULT_MODEL,
            "reason": f"8B model sufficient for {size}-sized task",
        }
    return {
        "engine": "cloud",
        "model": CLOUD_MODEL,
        "reason": f"{size}-sized task requires cloud model for multi-file reasoning",
    }


# -- Main --

def triage(task: str, repo: Optional[str] = None, engine: Optional[str] = None,
           heuristics_only: bool = False, skills_dir: str = DEFAULT_SKILLS_DIR,
           model: Optional[str] = None) -> tuple[dict, int]:
    """Run full triage pipeline. Returns (result_dict, exit_code).

    `model` is accepted for backward compatibility and ignored; the LLM pass
    runs through the active coding harness (`engine`)."""
    exit_code = 0

    # Step 1: Heuristic fast-path
    result = heuristic_analyze(task)

    # Step 2: LLM if heuristics inconclusive
    if result is None and not heuristics_only:
        result = llm_analyze(task, engine)
        if result is None:
            # Harness unavailable — default to M with cloud routing
            result = {
                "size": "M",
                "confidence": "low",
                "method": "fallback",
                "reasoning": "LLM harness unavailable, defaulting to M",
                "signals": [],
            }
            exit_code = 3
    elif result is None:
        result = {
            "size": "M",
            "confidence": "low",
            "method": "heuristic",
            "reasoning": "Heuristics inconclusive, defaulting to M",
            "signals": [],
        }

    # Step 3: Routing
    result["routing"] = recommend_routing(result["size"], task)

    # Step 4: Skill matching
    result["skill_matches"] = match_skills(task, skills_dir)

    # Step 5: Tool budget
    result["tool_budget"] = TOOL_BUDGETS.get(result["size"], TOOL_BUDGETS["M"])

    return result, exit_code


def main():
    parser = argparse.ArgumentParser(description="T-shirt size a coding task")
    parser.add_argument("--task", required=True, help="Task description to analyze")
    parser.add_argument("--repo", default=None, help="Repository path for context")
    parser.add_argument("--engine", default=None,
                        choices=["claude-code", "antigravity", "opencode"],
                        help="Coding harness for the LLM pass (default: config coding.default_engine)")
    parser.add_argument("--model", default=None,
                        help="Deprecated/ignored; the LLM pass uses the coding harness")
    parser.add_argument("--skills-dir", default=DEFAULT_SKILLS_DIR, help="Skills directory")
    parser.add_argument("--heuristics-only", action="store_true", help="Skip LLM analysis")
    parser.add_argument("--oneline", action="store_true", help="Compact output: SIZE ENGINE MODEL")
    args = parser.parse_args()

    result, exit_code = triage(
        args.task,
        repo=args.repo,
        engine=args.engine,
        heuristics_only=args.heuristics_only,
        skills_dir=args.skills_dir,
    )

    if args.oneline:
        r = result["routing"]
        print(f"{result['size']} {r['engine']} {r['model']}")
    else:
        print(json.dumps(result, indent=2))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
