#!/usr/bin/env python3
"""Tests for the anti-fabrication guard and vault removal.

Covers:
  - skill_ingest.fetch_to_quarantine rejects bare local paths outside the
    first-party roots unless trusted_local is set (the discovery clone case).
  - vetted_vault remove deletes the vault copy + registry record, gated by
    --confirm.

Stdlib unittest only; nothing is fetched, audited, or executed for real.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import skill_ingest  # noqa: E402
import vetted_vault  # noqa: E402


def _write_skill(dirpath: Path, name="fake"):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: x\n---\n# {name}\n"
    )


class TestFabricationGuard(unittest.TestCase):
    def test_rejects_local_path_outside_roots(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "hand-authored"
            _write_skill(src)
            path, err = skill_ingest.fetch_to_quarantine(str(src), "fake")
            self.assertIsNone(path)
            self.assertIn("first-party roots", err)

    def test_trusted_local_bypasses_guard(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "clone"
            _write_skill(src)
            path, err = skill_ingest.fetch_to_quarantine(
                str(src), "fake", trusted_local=True)
            self.assertEqual(err, "")
            self.assertIsNotNone(path)
            self.assertTrue((path / "SKILL.md").exists())
            import shutil
            shutil.rmtree(path, ignore_errors=True)

    def test_first_party_root_allowed(self):
        # A path under ~/.hermes-coder/skills is accepted without trusted_local.
        root = skill_ingest._LOCAL_SOURCE_ROOTS[0]
        src = root / "_test_fab_guard_tmp"
        _write_skill(src)
        try:
            path, err = skill_ingest.fetch_to_quarantine(str(src), "fab_guard_tmp")
            self.assertEqual(err, "")
            self.assertIsNotNone(path)
        finally:
            import shutil
            shutil.rmtree(src, ignore_errors=True)
            if path:
                shutil.rmtree(path, ignore_errors=True)

    def test_url_source_unaffected(self):
        # A URL is not a local path, so the guard never engages (we don't run the
        # clone here -- just confirm _is_url routes around the local-path branch).
        self.assertTrue(skill_ingest._is_url("https://example.com/x.git"))
        self.assertFalse(skill_ingest._is_url("/tmp/x"))


class _ArgsStub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class TestVaultRemove(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self._reg = base / "registry.json"
        self._vault = base / "vault"
        self._vault.mkdir()
        # Redirect module globals to the temp sandbox.
        self._orig_reg = vetted_vault.REGISTRY_PATH
        self._orig_vault = vetted_vault.VAULT_DIR
        vetted_vault.REGISTRY_PATH = self._reg
        vetted_vault.VAULT_DIR = self._vault

    def tearDown(self):
        vetted_vault.REGISTRY_PATH = self._orig_reg
        vetted_vault.VAULT_DIR = self._orig_vault
        self._tmp.cleanup()

    def _seed(self, name="dummy"):
        dest = self._vault / name
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("---\nname: dummy\n---\n")
        entry = vetted_vault.VaultEntry(
            sha256="abc123", name=name, tier=3, origin="community",
            status="approved", vaulted_path=str(dest),
            first_seen="t0", approved_at="t1", notes="seed",
        )
        reg = vetted_vault.load_registry(self._reg)
        reg[name] = entry
        vetted_vault.save_registry(reg, self._reg)
        return dest

    def test_remove_requires_confirm(self):
        dest = self._seed()
        code = vetted_vault.cmd_remove(_ArgsStub(name="dummy", confirm=False, json=True))
        self.assertEqual(code, 1)
        self.assertTrue(dest.exists())
        self.assertIn("dummy", vetted_vault.load_registry(self._reg))

    def test_remove_with_confirm(self):
        dest = self._seed()
        code = vetted_vault.cmd_remove(_ArgsStub(name="dummy", confirm=True, json=True))
        self.assertEqual(code, 0)
        self.assertFalse(dest.exists())
        self.assertNotIn("dummy", vetted_vault.load_registry(self._reg))

    def test_remove_missing_entry(self):
        code = vetted_vault.cmd_remove(_ArgsStub(name="nope", confirm=True, json=True))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
