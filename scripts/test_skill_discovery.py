#!/usr/bin/env python3
"""Unit tests for skill_discovery.py (Backlog #11).

Stdlib unittest only. Network + the #6 reuse points (skill_ingest.ingest,
container_runner.run_sandboxed, _fetch_skill) are monkeypatched so nothing is
fetched, audited, vaulted, or executed for real.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import skill_discovery as sd  # noqa: E402
from skill_discovery import IndexEntry, Candidate  # noqa: E402
from skill_ingest import IngestReport  # noqa: E402


def _entry(name="algorithmic-art", repo="anthropics/skills", path="skills/algorithmic-art",
           desc="creating algorithmic art using p5js flow fields", tags=None):
    return IndexEntry(name=name, description=desc, tags=tags or [], repo=repo,
                      identifier=f"{repo}/{path}", path=path, source_org=repo)


class TestNormalization(unittest.TestCase):
    def test_real_cached_indexes_adapt(self):
        anthropic = sd._index_files_for("anthropics")
        self.assertTrue(anthropic, "expected a cached anthropics index")
        entries = sd._load_index(anthropic[0], "anthropics")
        self.assertTrue(entries)
        self.assertTrue(all(isinstance(e, IndexEntry) for e in entries))
        self.assertTrue(any(e.name == "algorithmic-art" for e in entries))

    def test_empty_index_skipped(self):
        openai = sd._index_files_for("openai")
        if openai:  # the cached openai index is an empty "[]"
            self.assertEqual(sd._load_index(openai[0], "openai"), [])

    def test_lobehub_nested_adapter(self):
        raw = {"schemaVersion": 1, "agents": [
            {"author": "alice", "identifier": "x",
             "meta": {"title": "Turtle", "description": "d", "tags": ["puzzle"]}}]}
        out = sd._adapt_lobehub(raw, "lobehub")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].name, "Turtle")
        self.assertEqual(out[0].source_org, "alice")


class TestReputation(unittest.TestCase):
    def test_trusted_plural_org(self):
        rep = sd.reputation_for("anthropics/skills")
        self.assertEqual(rep["trust"], "trusted")
        self.assertFalse(rep["sandbox_code"])

    def test_known_huggingface(self):
        rep = sd.reputation_for("huggingface/skills")
        self.assertEqual(rep["trust"], "known")
        self.assertTrue(rep["sandbox_code"])

    def test_unknown_defaults_untrusted(self):
        rep = sd.reputation_for("lobehub/community-thing")
        self.assertEqual(rep["trust"], "untrusted")
        self.assertTrue(rep["sandbox_code"])

    def test_firebase_trusted(self):
        rep = sd.reputation_for("firebase/agent-skills")
        self.assertEqual(rep["trust"], "trusted")
        self.assertFalse(rep["sandbox_code"])


class TestFrontmatter(unittest.TestCase):
    def test_folded_scalar_description(self):
        text = ("---\n"
                "name: firebase-firestore\n"
                "description: >-\n"
                "  Sets up and queries Cloud Firestore database\n"
                "  instances for client SDK access.\n"
                "compatibility: best with the Firebase CLI\n"
                "---\n\n# body\n")
        fm = sd._parse_frontmatter(text)
        self.assertEqual(fm["name"], "firebase-firestore")
        self.assertIn("Firestore database instances", fm["description"])
        self.assertNotIn(">-", fm["description"])

    def test_inline_and_block_tags(self):
        inline = sd._parse_frontmatter(
            "---\nname: a\ndescription: x\ntags: [foo, bar]\n---\n")
        self.assertEqual(inline["tags"], ["foo", "bar"])
        block = sd._parse_frontmatter(
            "---\nname: b\ntags:\n  - foo\n  - bar\n---\n")
        self.assertEqual(block["tags"], ["foo", "bar"])

    def test_no_name_returns_none(self):
        self.assertIsNone(sd._parse_frontmatter("---\ndescription: x\n---\n"))


class TestDiscover(unittest.TestCase):
    def test_ranks_with_reputation(self):
        entries = [
            _entry(),
            _entry(name="hf-thing", repo="huggingface/skills", path="skills/hf-thing",
                   desc="machine learning models in javascript"),
            _entry(name="unrelated", repo="anthropics/skills", path="skills/unrelated",
                   desc="quarterly tax accounting spreadsheets"),
        ]
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: entries
        try:
            cands = sd.discover("algorithmic art p5js flow fields", top_k=3)
        finally:
            sd.load_allowlist_indexes = orig
        self.assertTrue(cands)
        self.assertEqual(cands[0].entry.name, "algorithmic-art")
        self.assertEqual(cands[0].reputation["trust"], "trusted")

    def test_fail_open_no_index(self):
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: []
        try:
            self.assertEqual(sd.discover("anything"), [])
        finally:
            sd.load_allowlist_indexes = orig

    def test_stopwords_let_distinctive_term_win(self):
        # A distinctive match (firestore) must outrank a skill that only matches
        # filler words, even when the filler skill shares more raw tokens.
        entries = [
            _entry(name="firebase-firestore", repo="firebase/agent-skills",
                   path="skills/firebase-firestore",
                   desc="queries against cloud firestore database instances"),
            _entry(name="xlsx", repo="anthropics/skills", path="skills/xlsx",
                   desc="use this skill for a spreadsheet in any application"),
        ]
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: entries
        try:
            cands = sd.discover(
                "integrate firestore database for a go application", top_k=2)
        finally:
            sd.load_allowlist_indexes = orig
        self.assertEqual(cands[0].entry.name, "firebase-firestore")

    def test_idf_beats_noise_word_inflation(self):
        # The real-world bug: many off-topic skills each share two *generic* words
        # with the task ("backend", "service", "deploy", "configure"), while the
        # one on-topic skill shares a single *distinctive* word ("firestore").
        # Flat overlap-ratio scoring ranks the noise skills above firestore and,
        # with top_k=3, the correct skill never surfaces. IDF weighting must put
        # firebase-firestore at rank 1.
        noise = [
            _entry(name=f"cloud-thing-{i}", repo="anthropics/skills",
                   path=f"skills/cloud-thing-{i}",
                   desc="backend service to deploy and configure cloud resources")
            for i in range(8)
        ]
        entries = noise + [
            _entry(name="firebase-firestore", repo="firebase/agent-skills",
                   path="skills/firebase-firestore",
                   desc="model firestore collections and documents"),
        ]
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: entries
        try:
            cands = sd.discover(
                "add firestore to the reservation backend service", top_k=3)
        finally:
            sd.load_allowlist_indexes = orig
        self.assertTrue(cands)
        self.assertEqual(cands[0].entry.name, "firebase-firestore")

    def _entries(self):
        # Two distinct entries so IDF is non-degenerate (a single entry makes
        # every word's IDF collapse to log(1)=0).
        return [
            _entry(desc="algorithmic art p5js flow fields generative"),
            _entry(name="xlsx", repo="anthropics/skills", path="skills/xlsx",
                   desc="quarterly tax accounting spreadsheets"),
        ]

    def test_repo_local_only_gates_out_external(self):
        # A repo whose .hermes-github.yaml sets skill_discovery: local-only must
        # get no external candidates (fail-open downstream to local skills).
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: self._entries()
        try:
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / ".hermes-github.yaml").write_text(
                    "skill_discovery: local-only\n")
                self.assertEqual(
                    sd.discover("algorithmic art flow fields", repo=d), [])
        finally:
            sd.load_allowlist_indexes = orig

    def test_repo_external_and_missing_allow_discovery(self):
        orig = sd.load_allowlist_indexes
        sd.load_allowlist_indexes = lambda allowlist=None: self._entries()
        try:
            with tempfile.TemporaryDirectory() as d:
                # Missing key -> default external -> candidates returned.
                self.assertTrue(sd.discover("algorithmic art flow fields", repo=d))
                (Path(d) / ".hermes-github.yaml").write_text(
                    "skill_discovery: external\n")
                self.assertTrue(sd.discover("algorithmic art flow fields", repo=d))
        finally:
            sd.load_allowlist_indexes = orig


class _VetBase(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "fetch": sd._fetch_skill,
            "ingest": sd.skill_ingest.ingest,
            "vaulted": sd._already_vaulted,
            "ships": sd._ships_code,
            "sandbox": sd.container_runner.run_sandboxed,
        }
        self._tmp = Path(tempfile.mkdtemp(prefix="hermes-test-"))
        sd._fetch_skill = lambda entry: (self._tmp, self._tmp, "")
        sd._already_vaulted = lambda name: False
        sd._ships_code = lambda path: False

    def tearDown(self):
        sd._fetch_skill = self._orig["fetch"]
        sd.skill_ingest.ingest = self._orig["ingest"]
        sd._already_vaulted = self._orig["vaulted"]
        sd._ships_code = self._orig["ships"]
        sd.container_runner.run_sandboxed = self._orig["sandbox"]
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _set_ingest(self, report, code):
        self.captured = {}
        def fake(source, name, origin, confirm, static_only=False, model=None,
                 engine=None, trusted_local=False):
            self.captured = {"confirm": confirm, "name": name, "engine": engine,
                             "trusted_local": trusted_local}
            return report, code
        sd.skill_ingest.ingest = fake


class TestVet(_VetBase):
    def test_audit_fail_hard_block(self):
        rep = IngestReport(name="x", source="s", tier=2, verdict="FAIL",
                           vaulted=False, vault_path="", status="blocked")
        self._set_ingest(rep, 1)
        cand = Candidate(_entry(), sd.reputation_for("anthropics/skills"), 0.9)
        res = sd.vet_candidate(cand)
        self.assertEqual(res.status, "blocked")
        self.assertFalse(res.vaulted)

    def test_trusted_auto_vaults(self):
        rep = IngestReport(name="algorithmic-art", source="s", tier=2, verdict="PASS",
                           vaulted=True, vault_path="/v/algorithmic-art", status="approved")
        self._set_ingest(rep, 0)
        cand = Candidate(_entry(), sd.reputation_for("anthropics/skills"), 0.9)
        res = sd.vet_candidate(cand, confirm=False)
        self.assertTrue(res.vaulted)
        self.assertTrue(self.captured["confirm"], "trusted source must auto-supply confirm")
        self.assertTrue(self.captured["trusted_local"],
                        "discovery clone must ingest with trusted_local")
        self.assertFalse(res.sandboxed)

    def test_known_requires_confirm(self):
        rep = IngestReport(name="hf", source="s", tier=3, verdict="PASS",
                           vaulted=False, vault_path="", status="awaiting_confirmation",
                           command_preview="... --confirm")
        self._set_ingest(rep, 1)
        cand = Candidate(_entry(repo="huggingface/skills"),
                         sd.reputation_for("huggingface/skills"), 0.8)
        res = sd.vet_candidate(cand, confirm=False)
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertFalse(self.captured["confirm"], "known source must not auto-confirm")
        self.assertFalse(res.vaulted)

    def test_known_with_confirm_vaults_and_sandboxes(self):
        rep = IngestReport(name="hf", source="s", tier=3, verdict="PASS",
                           vaulted=True, vault_path="/v/hf", status="approved")
        self._set_ingest(rep, 0)
        sd._ships_code = lambda path: True
        calls = {}
        def fake_sandbox(args):
            calls["from_vault"] = args.from_vault
            return sd.container_runner.RunResult(
                runner="docker", image="i", cmd=args.cmd, status="success"), 0
        sd.container_runner.run_sandboxed = fake_sandbox
        cand = Candidate(_entry(name="hf", repo="huggingface/skills"),
                         sd.reputation_for("huggingface/skills"), 0.8)
        res = sd.vet_candidate(cand, confirm=True)
        self.assertTrue(res.vaulted)
        self.assertTrue(self.captured["confirm"])
        self.assertTrue(res.sandboxed)
        self.assertEqual(calls["from_vault"], "hf")

    def test_untrusted_no_confirm_no_writes(self):
        rep = IngestReport(name="c", source="s", tier=3, verdict="WARN",
                           vaulted=False, vault_path="", status="awaiting_confirmation")
        self._set_ingest(rep, 1)
        cand = Candidate(_entry(repo="randomorg/thing"),
                         sd.reputation_for("randomorg/thing"), 0.7)
        res = sd.vet_candidate(cand, confirm=False)
        self.assertEqual(res.status, "awaiting_confirmation")
        self.assertFalse(res.vaulted)

    def test_dry_run_no_fetch(self):
        called = {"fetch": False}
        sd._fetch_skill = lambda entry: (called.__setitem__("fetch", True), (None, None, "x"))[1]
        cand = Candidate(_entry(), sd.reputation_for("anthropics/skills"), 0.9)
        res = sd.vet_candidate(cand, dry_run=True)
        self.assertEqual(res.status, "dry-run")
        self.assertFalse(called["fetch"])

    def test_already_vaulted_reused(self):
        sd._already_vaulted = lambda name: True
        cand = Candidate(_entry(), sd.reputation_for("anthropics/skills"), 0.9)
        res = sd.vet_candidate(cand)
        self.assertEqual(res.status, "reused")
        self.assertTrue(res.vaulted)

    def test_degraded_exit3(self):
        rep = IngestReport(name="algorithmic-art", source="s", tier=2, verdict="PASS",
                           vaulted=True, vault_path="/v/x", status="approved")
        self._set_ingest(rep, 3)  # harness down during audit
        cand = Candidate(_entry(), sd.reputation_for("anthropics/skills"), 0.9)
        res = sd.vet_candidate(cand)
        self.assertTrue(res.degraded)
        self.assertEqual(sd._vet_exit_code([res]), 3)


class TestInject(unittest.TestCase):
    def test_per_harness_mechanisms(self):
        orig = sd.injection_payload
        sd.injection_payload = lambda names: "## Skill: x\n\nbody"
        try:
            cc = sd.inject_for_harness("claude-code", sd.injection_payload(["x"]))
            agy = sd.inject_for_harness("antigravity", sd.injection_payload(["x"]))
            oc = sd.inject_for_harness("opencode", sd.injection_payload(["x"]))
        finally:
            sd.injection_payload = orig
        self.assertIn("--append-system-prompt", cc["args"])
        self.assertEqual(agy["mechanism"], "prompt-prepend")
        self.assertIn("-f", oc["args"])
        self.assertTrue(Path(oc["context_file"]).exists())

    def test_empty_payload_noop(self):
        spec = sd.inject_for_harness("claude-code", "")
        self.assertEqual(spec["args"], [])


class TestRefresh(unittest.TestCase):
    def test_dry_run_no_writes(self):
        args = sd.SimpleNamespace(dry_run=True, confirm=False, json=True, engine="claude-code")
        # capture stdout is unnecessary; just assert exit 0 and no exception
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = sd.cmd_refresh(args)
        self.assertEqual(code, 0)
        self.assertIn("refresh", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
