#!/usr/bin/env python3
"""Tests for repo_onboarding: status detection + idempotent init writes.

Stdlib unittest only; no git/gh/network. Drives the cmd_* handlers directly
with a lightweight args namespace and asserts on returned dicts + file state.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import repo_onboarding as ro  # noqa: E402


class _Args:
    def __init__(self, **kw):
        # init defaults mirror the argparse defaults.
        self.autonomy = "gated"
        self.default_base = None
        self.backlog = None
        self.backlog_project = None
        self.skill_discovery = None
        self.force = False
        self.skip = False
        self.json = True
        self.__dict__.update(kw)


class TestStatus(unittest.TestCase):
    def test_bare_dir_not_onboarded(self):
        with tempfile.TemporaryDirectory() as d:
            out, code = ro.cmd_status(_Args(), d)
            self.assertEqual(code, 0)
            self.assertFalse(out["onboarded"])
            self.assertFalse(out["files"][ro.GITHUB_FILE])
            # defaults still resolve for display
            self.assertEqual(out["settings"]["autonomy"], "gated")
            self.assertEqual(out["settings"]["skill_discovery"], "external")
            self.assertFalse(out["settings"]["backlog_enabled"])

    def test_onboarded_after_init(self):
        with tempfile.TemporaryDirectory() as d:
            ro.cmd_init(_Args(autonomy="full", backlog="true",
                              backlog_project="Demo",
                              skill_discovery="local-only"), d)
            out, _ = ro.cmd_status(_Args(), d)
            self.assertTrue(out["onboarded"])
            s = out["settings"]
            self.assertEqual(s["autonomy"], "full")
            self.assertEqual(s["skill_discovery"], "local-only")
            self.assertTrue(s["backlog_enabled"])
            self.assertEqual(s["backlog_project"], "Demo")


class TestInitWrites(unittest.TestCase):
    def test_writes_both_files(self):
        with tempfile.TemporaryDirectory() as d:
            out, code = ro.cmd_init(_Args(autonomy="push-draft", backlog="true",
                                          backlog_project="P",
                                          skill_discovery="external"), d)
            self.assertEqual(code, 0)
            self.assertEqual(out["status"], "onboarded")
            self.assertTrue((Path(d) / ro.GITHUB_FILE).is_file())
            self.assertTrue((Path(d) / ro.BACKLOG_FILE).is_file())
            gh = ro._read_all_flat(Path(d) / ro.GITHUB_FILE)
            self.assertEqual(gh["autonomy"], "push-draft")
            self.assertEqual(gh["skill_discovery"], "external")
            bl = ro._read_all_flat(Path(d) / ro.BACKLOG_FILE)
            self.assertEqual(bl["enabled"], "true")
            self.assertEqual(bl["project_name"], "P")

    def test_backlog_false_writes_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            ro.cmd_init(_Args(backlog="false"), d)
            bl = ro._read_all_flat(Path(d) / ro.BACKLOG_FILE)
            self.assertEqual(bl["enabled"], "false")

    def test_no_backlog_flag_leaves_backlog_file_absent(self):
        with tempfile.TemporaryDirectory() as d:
            ro.cmd_init(_Args(autonomy="gated"), d)
            self.assertFalse((Path(d) / ro.BACKLOG_FILE).is_file())


class TestIdempotency(unittest.TestCase):
    def test_rerun_same_is_noop(self):
        with tempfile.TemporaryDirectory() as d:
            a = _Args(autonomy="gated", backlog="true", backlog_project="P",
                      skill_discovery="external")
            ro.cmd_init(a, d)
            out, code = ro.cmd_init(a, d)
            self.assertEqual(code, 0)
            self.assertEqual(out["wrote"], [])
            self.assertTrue(out["unchanged"])

    def test_conflict_refused_without_force(self):
        with tempfile.TemporaryDirectory() as d:
            ro.cmd_init(_Args(autonomy="gated"), d)
            out, code = ro.cmd_init(_Args(autonomy="full"), d)
            self.assertEqual(code, 1)
            self.assertEqual(out["status"], "refused")
            self.assertIn(ro.GITHUB_FILE, out["conflicts"])
            # file unchanged
            self.assertEqual(
                ro._read_all_flat(Path(d) / ro.GITHUB_FILE)["autonomy"], "gated")

    def test_force_rewrites_only_provided_keys(self):
        with tempfile.TemporaryDirectory() as d:
            ro.cmd_init(_Args(autonomy="gated", skill_discovery="local-only"), d)
            out, code = ro.cmd_init(_Args(autonomy="full", force=True), d)
            self.assertEqual(code, 0)
            gh = ro._read_all_flat(Path(d) / ro.GITHUB_FILE)
            self.assertEqual(gh["autonomy"], "full")          # changed
            self.assertEqual(gh["skill_discovery"], "local-only")  # preserved


class TestSkip(unittest.TestCase):
    def test_skip_writes_safe_defaults_and_onboards(self):
        with tempfile.TemporaryDirectory() as d:
            out, code = ro.cmd_init(_Args(skip=True), d)
            self.assertEqual(code, 0)
            self.assertTrue(out["skipped"])
            self.assertTrue(out["onboarded"])
            gh = ro._read_all_flat(Path(d) / ro.GITHUB_FILE)
            self.assertEqual(gh["autonomy"], "gated")
            self.assertEqual(gh["skill_discovery"], "local-only")
            bl = ro._read_all_flat(Path(d) / ro.BACKLOG_FILE)
            self.assertEqual(bl["enabled"], "false")
            # status agrees
            st, _ = ro.cmd_status(_Args(), d)
            self.assertTrue(st["onboarded"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
