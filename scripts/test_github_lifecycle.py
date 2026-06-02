#!/usr/bin/env python3
"""Tests for github_lifecycle issue-linking (Closes #N on PR merge).

Covers branch-name -> issue-number inference (conservative, no false positives)
and the closing-keyword append/dedup. Stdlib unittest only; no git/gh calls.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import github_lifecycle as gl  # noqa: E402


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TestBranchInference(unittest.TestCase):
    def test_explicit_issue_prefixes(self):
        for branch, exp in {
            "issue-42-add-login": 42, "issue/42": 42, "fix/issue-9": 9,
            "gh-7-fix": 7,
        }.items():
            self.assertEqual(gl._infer_issue_from_branch(branch), exp, branch)

    def test_leading_numeric_segment(self):
        for branch, exp in {
            "42-add-foo": 42, "feature/123-thing": 123, "7": 7,
        }.items():
            self.assertEqual(gl._infer_issue_from_branch(branch), exp, branch)

    def test_no_false_positives_on_embedded_digits(self):
        for branch in ("add-oauth2-login", "v2-refactor", "release-2024",
                       "main", "", "migrate-to-python3"):
            self.assertIsNone(gl._infer_issue_from_branch(branch), branch)


class TestResolveIssueNumber(unittest.TestCase):
    def test_explicit_wins(self):
        # Explicit --issue is used without touching the branch.
        self.assertEqual(gl._resolve_issue_number(_Args(issue=99), "/nope"), 99)

    def test_nonpositive_explicit_ignored(self):
        self.assertIsNone(gl._resolve_issue_number(_Args(issue=0), "/nope"))
        self.assertIsNone(gl._resolve_issue_number(_Args(issue=-3), "/nope"))


class TestClosingKeyword(unittest.TestCase):
    def test_appends_closes(self):
        out = gl._append_closing_keyword("## Summary\n- x", 42)
        self.assertTrue(out.rstrip().endswith("Closes #42"))

    def test_dedup_existing_reference(self):
        for body in ("Fixes #42 already", "this closes #42", "Resolves #42"):
            self.assertEqual(gl._append_closing_keyword(body, 42), body)

    def test_dedup_is_issue_specific(self):
        # An existing close of a *different* issue must not suppress ours.
        out = gl._append_closing_keyword("Closes #7", 42)
        self.assertIn("Closes #42", out)
        self.assertIn("Closes #7", out)

    def test_no_issue_is_noop(self):
        body = "## Summary\n- x"
        self.assertEqual(gl._append_closing_keyword(body, None), body)

    def test_empty_body(self):
        self.assertEqual(gl._append_closing_keyword("", 5), "Closes #5")


class TestHygieneClassify(unittest.TestCase):
    def test_secrets_block(self):
        for p in (".env", "config/.env.production", "app.key", "certs/server.pem",
                  "id_rsa", "credentials.json"):
            v = gl._classify_path(p)
            self.assertIsNotNone(v, p)
            self.assertEqual(v[0], "block", p)

    def test_secret_allowlist_and_public_keys(self):
        for p in (".env.example", ".env.sample", "deploy.pub", "src/main.go",
                  "README.md"):
            self.assertIsNone(gl._classify_path(p), p)

    def test_junk_warns(self):
        for p in ("node_modules/x/i.js", "dist/b.js", "vendor/pkg/x.go",
                  ".DS_Store", "app.log", "x.pyc"):
            v = gl._classify_path(p)
            self.assertIsNotNone(v, p)
            self.assertEqual(v[0], "warn", p)


class TestHygieneCheck(unittest.TestCase):
    def test_block_and_suggestions(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            res = gl._hygiene_check(d, [".env", "node_modules/a.js", "main.go"])
            self.assertTrue(res["has_block"])
            self.assertIn(".env", res["suggested_gitignore"])
            self.assertIn("node_modules/", res["suggested_gitignore"])
            # no .gitignore in the temp dir -> a warn issue is added
            self.assertFalse(res["gitignore_present"])
            self.assertTrue(any(i["path"] == ".gitignore" for i in res["issues"]))

    def test_clean_repo_with_gitignore(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            (_P(d) / ".gitignore").write_text("node_modules/\n")
            res = gl._hygiene_check(d, ["main.go", "README.md"])
            self.assertFalse(res["has_block"])
            self.assertEqual(res["issues"], [])
            self.assertTrue(res["gitignore_present"])


class TestContentScan(unittest.TestCase):
    def _scan_one(self, name, content):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            (_P(d) / name).write_text(content)
            return gl._scan_content(d, [name])

    def test_flags_macos_home_path(self):
        issues = self._scan_one("Makefile", "build:\n\t/Users/you/go/bin/templ generate\n")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warn")
        self.assertTrue(issues[0]["path"].endswith(":2"))
        self.assertIn("/Users/you/go/bin/templ", issues[0]["reason"])

    def test_flags_linux_and_windows_home_paths(self):
        self.assertEqual(len(self._scan_one("run.sh", "BIN=/home/alice/go/bin/air\n")), 1)
        self.assertEqual(
            len(self._scan_one("build.bat", "set T=C:\\Users\\bob\\go\\bin\\templ.exe\n")), 1)

    def test_portable_paths_not_flagged(self):
        for content in ("TOOL=~/go/bin/templ\n", "TOOL=$HOME/go/bin/templ\n",
                        'r.GET("/home", h)\n', "x := \"./relative/path\"\n"):
            self.assertEqual(self._scan_one("f.txt", content), [], content)

    def test_dedup_same_path_in_file(self):
        issues = self._scan_one(
            "Makefile", "a:\n\t/Users/alice/bin/x\nb:\n\t/Users/alice/bin/x\n")
        self.assertEqual(len(issues), 1)

    def test_skips_binary_and_lockfiles(self):
        self.assertEqual(self._scan_one("a.bin", "/Users/alice/x\x00more"), [])
        self.assertEqual(self._scan_one("package-lock.json", "/Users/alice/cache/x\n"), [])

    def test_skips_vendored_dirs(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            sub = _P(d) / "node_modules" / "pkg"
            sub.mkdir(parents=True)
            (sub / "i.js").write_text("p='/Users/alice/x/y'\n")
            self.assertEqual(gl._scan_content(d, ["node_modules/pkg/i.js"]), [])

    def test_machine_path_is_warn_not_block(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            (_P(d) / ".gitignore").write_text("node_modules/\n")
            (_P(d) / "Makefile").write_text("\t/Users/alice/go/bin/templ\n")
            res = gl._hygiene_check(d, ["Makefile"])
            self.assertFalse(res["has_block"])
            self.assertTrue(any("machine path" in i["reason"] for i in res["issues"]))


class TestProtectedBranch(unittest.TestCase):
    def test_main_and_master_are_protected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(gl._is_protected_branch(d, "main"))
            self.assertTrue(gl._is_protected_branch(d, "master"))

    def test_feature_branch_not_protected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(gl._is_protected_branch(d, "issue-42-add-login"))
            self.assertFalse(gl._is_protected_branch(d, "feat/firestore"))


def _mkrepo(tmp, branch="main"):
    """Build a temp git repo with one commit, a feature/main branch, and a fake
    local 'origin' (a bare repo) so _preflight's remote check passes. The push
    guards return before any real push, so origin is never actually written."""
    import subprocess
    from pathlib import Path as _P

    def git(*a):
        subprocess.run(["git", "-C", tmp, *a], check=True,
                       capture_output=True, text=True)

    subprocess.run(["git", "init", "-q", tmp], check=True,
                   capture_output=True, text=True)
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "T")
    git("checkout", "-q", "-b", "main")
    (_P(tmp) / "f.txt").write_text("x\n")
    git("add", "f.txt")
    git("commit", "-q", "-m", "init")
    bare = tmp + "_origin.git"
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True,
                   capture_output=True, text=True)
    git("remote", "add", "origin", bare)
    if branch != "main":
        git("checkout", "-q", "-b", branch)
    return tmp


class TestPushGuards(unittest.TestCase):
    def test_push_blocks_on_protected_branch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = _mkrepo(d, branch="main")
            res, code = gl.cmd_push(
                _Args(repo=repo, autonomy=None, confirm=False,
                      allow_protected=False, json=False), repo)
            self.assertEqual(res.status, "blocked")
            self.assertEqual(code, 1)
            self.assertIn("protected branch", res.error)

    def test_allow_protected_clears_branch_guard_but_gate_still_applies(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = _mkrepo(d, branch="main")
            res, code = gl.cmd_push(
                _Args(repo=repo, autonomy="gated", confirm=False,
                      allow_protected=True, json=False), repo)
            # Branch guard cleared by --allow-protected, but gated autonomy with no
            # --confirm still stops the push.
            self.assertEqual(res.status, "awaiting_confirmation")

    def test_push_blocks_on_dirty_tree(self):
        import tempfile
        from pathlib import Path as _P
        with tempfile.TemporaryDirectory() as d:
            repo = _mkrepo(d, branch="feat/x")
            (_P(repo) / "untracked.txt").write_text("leak\n")
            res, code = gl.cmd_push(
                _Args(repo=repo, autonomy=None, confirm=False,
                      allow_protected=False, json=False), repo)
            self.assertEqual(res.status, "blocked")
            self.assertEqual(code, 1)
            self.assertIn("not clean", res.error)

    def test_clean_feature_branch_reaches_gate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            repo = _mkrepo(d, branch="feat/x")
            res, code = gl.cmd_push(
                _Args(repo=repo, autonomy="gated", confirm=False,
                      allow_protected=False, json=False), repo)
            # No protected/dirty block — lands on the normal gated confirmation.
            self.assertEqual(res.status, "awaiting_confirmation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
