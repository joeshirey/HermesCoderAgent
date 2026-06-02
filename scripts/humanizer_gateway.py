#!/usr/bin/env python3
"""Humanizer gateway: strip AI slop from draft text before external writes.

Compiles the 29 patterns from skills/creative/humanizer/SKILL.md into regex
rules, applies voice calibration from git log, and optionally runs an LLM
anti-AI pass through the default coding harness (`claude -p`).

Usage:
    python3 humanizer_gateway.py --text "draft text" --type commit
    python3 humanizer_gateway.py --text "draft text" --type pr --repo /path
    python3 humanizer_gateway.py --text "long doc" --type doc --repo /path
    python3 humanizer_gateway.py --text "anything" --bypass
    echo "text" | python3 humanizer_gateway.py - --type doc
    python3 humanizer_gateway.py --file /path/to/draft.txt --type doc --json

Exit codes:
    0  Success, filtered text to stdout
    1  Error (missing input, read failure)
    2  Invalid arguments
    3  LLM harness unavailable (rule-filtered text still on stdout)
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from harness_llm import (
    harness_generate, strip_fences, resolve_engine, HarnessUnavailable,
)

# The LLM anti-AI pass runs through the user-selected coding harness (resolved
# from --engine / config coding.default_engine), not a local model. See SOUL.md.
HARNESS_TIMEOUT = 180
VOICE_CACHE_DIR = Path.home() / ".hermes-coder" / "cache" / "voice_samples"
VOICE_CACHE_TTL_HOURS = 24
WRITING_SAMPLE_PATH = Path.home() / ".hermes-coder" / "writing_sample.txt"


# ── Pattern 1: Significance inflation ──

_SIGNIFICANCE_WORDS = (
    r'stands?\s+as\b|serves?\s+as\s+a\s+testament|is\s+a\s+testament|'
    r'a\s+(?:vital|significant|crucial|pivotal|key)\s+(?:role|moment)|'
    r'underscores?\s+(?:its\s+)?(?:importance|significance)|'
    r'highlights?\s+(?:its\s+)?(?:importance|significance)|'
    r'reflects?\s+broader|symbolizing\s+its\s+(?:ongoing|enduring|lasting)|'
    r'contributing\s+to\s+the|setting\s+the\s+stage\s+for|'
    r'marking\s+a|shaping\s+the|represents?\s+a\s+(?:shift|milestone)|'
    r'key\s+turning\s+point|evolving\s+landscape|focal\s+point|'
    r'indelible\s+mark|deeply\s+rooted|transformative\s+potential'
)

# ── Pattern 3: Trailing -ing clauses ──

_ING_TRAILING = (
    r',\s*(?:ensuring|highlighting|underscoring|emphasizing|reflecting|'
    r'symbolizing|contributing\s+to|cultivating|fostering|encompassing|'
    r'showcasing|demonstrating|illustrating|reinforcing|solidifying|'
    r'underscoring|signaling)\s+[^.;!?\n]{5,}[.;!?]?'
)

# ── Pattern 4: Promotional language ──

_PROMO_WORDS = (
    r'\b(?:boasts?\s+a|nestled\s+(?:in|within|among)|in\s+the\s+heart\s+of|'
    r'groundbreaking|renowned\s+for|breathtaking|must-visit|stunning)\b'
)

# ── Pattern 7: AI vocabulary words ──

_AI_VOCAB = (
    r'\b(?:delve[sd]?|tapestry|foster(?:s|ed|ing)?|cultivat(?:e[sd]?|ing)|'
    r'garner(?:s|ed|ing)?|interplay|intricac(?:y|ies)|'
    r'vibrant|testament|(?:evolving\s+)?landscape|pivotal|'
    r'underscore[sd]?|enduring|showcase[sd]?|'
    r'additionally|crucial|enhance[sd]?|enhancing|'
    r'align(?:s|ed|ing)?\s+with|valuable|key(?=\s+(?:role|moment|factor)))\b'
)

# ── Pattern 8: Copula avoidance ──

_COPULA_AVOIDANCE = [
    (re.compile(r'\bserves?\s+as\s+(?:a\s+|an\s+|the\s+)?', re.I), 'is '),
    (re.compile(r'\bstands?\s+as\s+(?:a\s+|an\s+|the\s+)?', re.I), 'is '),
    (re.compile(r'\bfunctions?\s+as\s+(?:a\s+|an\s+|the\s+)?', re.I), 'is '),
    (re.compile(r'\bboasts?\s+(?:over\s+)?', re.I), 'has '),
    # Verb-sense "features" only: require a trailing article so the *noun*
    # "feature"/"features" (e.g. "a missing feature", "its features are") is left alone.
    (re.compile(r'\bfeatures\s+(a|an|the)\s+', re.I), r'has \1 '),
]

# ── Pattern 9: Negative parallelisms ──

_NEG_PARALLEL = re.compile(
    r"(?:It'?s\s+)?[Nn]ot\s+(?:only|just|merely|simply)\s+(?:about\s+)?[^.;!?\n]+[;,]\s*"
    r"(?:it'?s|but)\s+(?:also\s+)?(?:about\s+)?[^.;!?\n]+[.;!?]?",
    re.I,
)

# ── Pattern 18: Emoji stripping ──

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F9FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001FA00-\U0001FA6F"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50"
    "]+",
    re.UNICODE,
)

# ── Pattern 19: Curly quotes ──

_CURLY_QUOTES = [
    ("“", '"'), ("”", '"'),
    ("‘", "'"), ("’", "'"),
]

# ── Pattern 20: Collaborative artifacts ──

_COLLAB_ARTIFACTS = re.compile(
    r'(?:I\s+hope\s+this\s+helps[.!]?\s*|Of\s+course!\s*|Certainly!\s*|'
    r'You\'?re\s+absolutely\s+right[.!]?\s*|Would\s+you\s+like[^.?!]*[.?!]\s*|'
    r'[Ll]et\s+me\s+know[^.!?]*[.!?]\s*|[Hh]ere\s+is\s+(?:a|an)\s+)',
    re.I,
)

# ── Pattern 21: Knowledge cutoff disclaimers ──

_CUTOFF_DISCLAIMERS = re.compile(
    r'(?:[Aa]s\s+of\s+(?:my|the)\s+(?:last\s+)?(?:training|knowledge)\s+[^.]+\.\s*|'
    r'[Uu]p\s+to\s+my\s+last\s+training\s+[^.]+\.\s*|'
    r'[Ww]hile\s+specific\s+details\s+are\s+(?:limited|scarce)[^.]*\.\s*|'
    r'[Bb]ased\s+on\s+available\s+information[^.]*[.,]\s*)',
    re.I,
)

# ── Pattern 22: Sycophantic tone ──

_SYCOPHANTIC = re.compile(
    r'(?:Great\s+question!?\s*|That\'?s\s+an\s+excellent\s+point[^.]*\.\s*|'
    r'Absolutely!\s*|What\s+a\s+great\s+(?:question|point)!?\s*)',
    re.I,
)

# ── Pattern 23: Filler phrases ──

_FILLER_PHRASES = [
    (re.compile(r'\b[Ii]n\s+order\s+to\b'), 'to'),
    (re.compile(r'\b[Dd]ue\s+to\s+the\s+fact\s+that\b'), 'because'),
    (re.compile(r'\b[Aa]t\s+this\s+point\s+in\s+time\b'), 'now'),
    (re.compile(r'\b[Ii]n\s+the\s+event\s+that\b'), 'if'),
    (re.compile(r'\bhas\s+the\s+ability\s+to\b'), 'can'),
    (re.compile(r'\b[Ii]t\s+is\s+important\s+to\s+note\s+that\b'), ''),
    (re.compile(r'\b[Ii]t\s+is\s+worth\s+noting\s+that\b'), ''),
    (re.compile(r'\b[Ii]t\s+should\s+be\s+noted\s+that\b'), ''),
]

# ── Pattern 25: Generic positive conclusions ──

_GENERIC_CONCLUSIONS = re.compile(
    r'(?:[Tt]he\s+future\s+looks\s+bright[^.]*\.\s*|'
    r'[Ee]xciting\s+times\s+lie\s+ahead[^.]*\.\s*|'
    r'(?:This|It)\s+represents\s+a\s+major\s+step[^.]*\.\s*|'
    r'(?:As\s+we|[Ww]e)\s+continue\s+(?:this|our)\s+journey[^.]*\.\s*)',
    re.I,
)

# ── Pattern 27: Persuasive authority tropes ──

_AUTHORITY_TROPES = re.compile(
    r'\b(?:[Tt]he\s+real\s+question\s+is|[Aa]t\s+its\s+core|'
    r'[Ii]n\s+reality|[Ww]hat\s+really\s+matters|'
    r'[Ff]undamentally|[Tt]he\s+deeper\s+issue|'
    r'[Tt]he\s+heart\s+of\s+the\s+matter)\b[,:]?\s*',
    re.I,
)

# ── Pattern 28: Signposting ──

_SIGNPOSTING = re.compile(
    r'(?:[Ll]et\'?s\s+(?:dive\s+in(?:to)?|explore|break\s+this\s+down)[.!]?\s*|'
    r'[Hh]ere\'?s\s+what\s+you\s+need\s+to\s+know[.!:]?\s*|'
    r'[Nn]ow\s+let\'?s\s+(?:look\s+at|turn\s+to)[.!]?\s*|'
    r'[Ww]ithout\s+further\s+ado[.!,:]?\s*)',
    re.I,
)


# ── Combined rule-based filter ──

def rule_based_filter(text: str) -> str:
    """Apply all regex-based slop removal. No LLM needed."""

    # Pattern 19: Curly quotes → straight
    for curly, straight in _CURLY_QUOTES:
        text = text.replace(curly, straight)

    # Pattern 18: Strip emojis
    text = _EMOJI_RE.sub('', text)

    # Pattern 20: Collaborative artifacts
    text = _COLLAB_ARTIFACTS.sub('', text)

    # Pattern 21: Knowledge cutoff disclaimers
    text = _CUTOFF_DISCLAIMERS.sub('', text)

    # Pattern 22: Sycophantic tone
    text = _SYCOPHANTIC.sub('', text)

    # Pattern 28: Signposting
    text = _SIGNPOSTING.sub('', text)

    # Pattern 27: Authority tropes
    text = _AUTHORITY_TROPES.sub('', text)

    # Pattern 25: Generic positive conclusions
    text = _GENERIC_CONCLUSIONS.sub('', text)

    # Pattern 1: Significance inflation phrases
    text = re.sub(_SIGNIFICANCE_WORDS, '', text, flags=re.I)

    # Pattern 3: Trailing -ing clauses
    text = re.sub(_ING_TRAILING, '.', text, flags=re.I)

    # Pattern 4: Promotional language
    text = re.sub(_PROMO_WORDS, '', text, flags=re.I)

    # Pattern 7: AI vocabulary
    text = re.sub(_AI_VOCAB, '', text, flags=re.I)

    # Pattern 8: Copula avoidance
    for pattern, replacement in _COPULA_AVOIDANCE:
        text = pattern.sub(replacement, text)

    # Pattern 23: Filler phrases
    for pattern, replacement in _FILLER_PHRASES:
        text = pattern.sub(replacement, text)

    # Cleanup: double spaces, orphaned punctuation, excess newlines
    text = re.sub(r'  +', ' ', text)
    text = re.sub(r' +([.,;:!?])', r'\1', text)
    text = re.sub(r'([.,;:!?])\s*([.,;:!?])', r'\1', text)
    text = re.sub(r'^\s*[.,;:]\s*', '', text, flags=re.M)
    text = re.sub(r'[ \t]+\n', '\n', text)   # drop trailing spaces on each line
    text = re.sub(r'\n{3,}', '\n\n', text)   # collapse 3+ newlines, keep para breaks

    return text.strip()


# ── Commit-specific aggressive filter ──

def _commit_filter(text: str) -> str:
    """Light commit formatting: tidy the subject, preserve the body and casing.

    Keeps the conventional shape (subject, blank line, body). Casing is left as
    written -- we no longer force all-lowercase, collapse to the first sentence,
    or hard-truncate, so the drafter's natural style and any explanatory body
    survive.
    """
    text = text.strip()
    if not text:
        return text

    lines = text.split("\n")
    subject = lines[0].strip()
    body = "\n".join(lines[1:]).strip("\n")

    # Strip a trailing period from the subject (convention); leave casing alone.
    subject = subject.rstrip().rstrip('.')

    if body:
        return f"{subject}\n\n{body}"
    return subject


# ── Voice calibration ──

def get_voice_sample(repo_dir: Optional[str] = None) -> Optional[str]:
    """Get cached voice sample from git log or writing sample file."""
    # Check writing sample file first
    if WRITING_SAMPLE_PATH.exists():
        return WRITING_SAMPLE_PATH.read_text(encoding="utf-8").strip()

    if not repo_dir:
        return None

    # Check cache
    VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.md5(repo_dir.encode()).hexdigest()
    cache_file = VOICE_CACHE_DIR / f"{cache_key}.txt"

    if cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < VOICE_CACHE_TTL_HOURS:
            return cache_file.read_text(encoding="utf-8").strip()

    # Harvest git log
    try:
        result = subprocess.run(
            ["git", "log", "-n", "20", "--format=%s"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            sample = result.stdout.strip()
            cache_file.write_text(sample, encoding="utf-8")
            return sample
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return None


# ── LLM anti-AI pass (active coding harness) ──

def llm_anti_ai_pass(
    text: str,
    voice_sample: Optional[str] = None,
    engine: Optional[str] = None,
    artifact_type: str = "doc",
    repo_dir: Optional[str] = None,
) -> Optional[str]:
    """Single-pass LLM polishing via the user-selected coding harness.
    Returns None if the harness is unavailable (caller maps that to exit 3)."""
    type_guidance = {
        "commit": "The output should be a clear commit message: a concise subject line in normal sentence case starting with an active verb, followed by an optional body that explains the why. Keep the subject reasonably short (aim for ~72 chars) but do not truncate meaning, force all-lowercase, or drop the body. No fluff.",
        "pr": "The output should be a concise PR description. Preserve any template structure (## headers, checkboxes). Strip marketing fluff from the body.",
        "doc": "The output should be clear technical documentation. Vary sentence lengths. Use active voice. Preserve markdown structure, code blocks, and any front matter exactly.",
        "chat": "The output should be natural conversational text. Light touch — preserve the casual tone.",
    }

    prompt = (
        "You are a writing editor. Rewrite the text below to remove the tells "
        "that make it sound AI-generated: significance inflation, formulaic "
        "transitions, trailing -ing clauses, rule-of-three padding, promotional "
        "adjectives, and hedging filler. Preserve all meaning and facts. Do not "
        "add or remove sections.\n\n"
        f"Guidelines: {type_guidance.get(artifact_type, type_guidance['doc'])}\n"
    )
    if voice_sample:
        prompt += (
            "\nUse these examples only as a loose reference for tone and "
            "vocabulary. Do NOT copy their casing, length, or terseness -- in "
            "particular, do not force all-lowercase or extreme brevity just "
            f"because the samples are written that way:\n{voice_sample}\n"
        )
    prompt += (
        "\nOutput ONLY the rewritten text -- no commentary, no preamble, no "
        "explanation, and do not wrap the whole reply in a code fence.\n\n"
        "--- TEXT TO REWRITE ---\n"
        f"{text}"
    )

    try:
        out = harness_generate(
            prompt, engine=engine, repo=repo_dir, timeout=HARNESS_TIMEOUT
        )
    except HarnessUnavailable:
        return None
    return strip_fences(out)


# ── Main pipeline ──

def humanize(
    text: str,
    artifact_type: str = "doc",
    repo_dir: Optional[str] = None,
    engine: Optional[str] = None,
    rules_only: bool = False,
    bypass: bool = False,
) -> tuple[str, list[str], int]:
    """Run the full humanizer pipeline.

    Returns: (filtered_text, passes_applied, exit_code)
    """
    if bypass:
        return text, ["bypass"], 0

    passes = []
    exit_code = 0

    # Step 1: Rule-based filtering (always runs)
    filtered = rule_based_filter(text)
    passes.append("rules")

    # Step 2: Commit-specific aggressive formatting
    if artifact_type == "commit":
        filtered = _commit_filter(filtered)
        passes.append("commit-format")

    # Step 3: LLM anti-AI pass (optional) — runs through the default harness
    if not rules_only:
        voice_sample = get_voice_sample(repo_dir)
        llm_result = llm_anti_ai_pass(
            filtered, voice_sample, engine, artifact_type, repo_dir
        )
        if llm_result is not None:
            filtered = llm_result
            passes.append("llm")
            # Re-apply commit formatting after LLM (LLM may have expanded)
            if artifact_type == "commit":
                filtered = _commit_filter(filtered)
                passes.append("commit-format-post-llm")
        else:
            exit_code = 3

    return filtered, passes, exit_code


def main():
    parser = argparse.ArgumentParser(
        description="Humanize draft text before external writes"
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", help="Inline draft text")
    input_group.add_argument("--file", help="Read draft from file")
    input_group.add_argument(
        "stdin_flag",
        nargs="?",
        default=None,
        help="Pass '-' to read from stdin",
    )

    parser.add_argument(
        "--type",
        default="doc",
        choices=["commit", "pr", "doc", "chat"],
        help="Artifact type (default: doc)",
    )
    parser.add_argument("--repo", default=None, help="Git repo for voice calibration")
    parser.add_argument(
        "--engine", default=None,
        choices=["claude-code", "antigravity", "opencode"],
        help="Coding harness for the LLM pass (default: config coding.default_engine)",
    )
    parser.add_argument(
        "--rules-only", action="store_true", help="Skip LLM pass"
    )
    parser.add_argument(
        "--bypass", action="store_true", help="Pass-through mode"
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output", help="JSON output"
    )

    args = parser.parse_args()

    # Read input
    if args.text:
        draft = args.text
    elif args.file:
        try:
            draft = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.stdin_flag == "-":
        draft = sys.stdin.read()
    else:
        parser.print_help()
        sys.exit(2)

    if not draft.strip():
        print("", end="")
        sys.exit(0)

    result, passes, exit_code = humanize(
        draft,
        artifact_type=args.type,
        repo_dir=args.repo,
        engine=args.engine,
        rules_only=args.rules_only,
        bypass=args.bypass,
    )

    if args.json_output:
        output = {
            "original": draft,
            "filtered": result,
            "passes": passes,
            "harness_used": resolve_engine(args.engine) if "llm" in passes else None,
            "artifact_type": args.type,
            "harness_available": exit_code != 3,
        }
        print(json.dumps(output, indent=2))
    else:
        print(result, end="")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
