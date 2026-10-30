"""Filesystem behavior checks; these do not grade agent reasoning."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('kit_install', ROOT / 'install.py')
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class InstallBehavior(unittest.TestCase):
    def setUp(self):
        self.temp_root = (ROOT / '.test-runs').resolve()
        self.temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.project = Path(self.temp.name).resolve() / 'project with spaces'
        self.project.mkdir()

    def tearDown(self):
        # Check the absolute cleanup target before recursive temp cleanup.
        if not Path(self.temp.name).resolve().is_relative_to(self.temp_root):
            raise AssertionError('Unexpected temporary cleanup path')
        self.temp.cleanup()

    def run_install(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / 'install.py'), '--target', str(self.project), *args],
            text=True, capture_output=True, encoding='utf-8',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
        )

    def test_dry_run_then_preserve_instructions_and_repeat(self):
        original = b'\xef\xbb\xbf# Project rules\r\n\r\nKeep this exact text.\r\n'
        agents = self.project / 'AGENTS.md'
        agents.write_bytes(original)
        preview = self.run_install('--with-agents', '--dry-run')
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(agents.read_bytes(), original)
        self.assertFalse((self.project / '.agents').exists())
        applied = self.run_install('--with-agents')
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(agents.read_bytes().startswith(original))
        after = agents.read_bytes()
        repeated = self.run_install('--with-agents')
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(agents.read_bytes(), after)
        for name in INSTALL.SKILLS:
            installed = self.project / '.agents' / 'skills' / name / 'SKILL.md'
            self.assertEqual(installed.read_bytes(), (ROOT / '.agents' / 'skills' / name / 'SKILL.md').read_bytes())

    def test_conflicting_skill_stops_before_other_writes(self):
        collision = self.project / '.agents' / 'skills' / 'explain-implementation' / 'SKILL.md'
        collision.parent.mkdir(parents=True)
        collision.write_text('Existing private skill', encoding='utf-8')
        result = self.run_install('--with-agents')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.project / 'AGENTS.md').exists())
        self.assertFalse((self.project / '.agents' / 'skills' / 'decision-brief').exists())
        self.assertEqual(collision.read_text(encoding='utf-8'), 'Existing private skill')

    def test_default_preserves_agents_without_appending(self):
        agents = self.project / 'AGENTS.md'
        agents.write_bytes(b'# Existing rules\n')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(agents.read_bytes(), b'# Existing rules\n')

    def test_override_is_preserved_and_no_files_added(self):
        override = self.project / 'AGENTS.override.md'
        override.write_text('Official task rules', encoding='utf-8')
        result = self.run_install('--with-agents')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(override.read_text(encoding='utf-8'), 'Official task rules')
        self.assertFalse((self.project / '.agents').exists())

    def test_broken_markers_stop_before_writes(self):
        agents = self.project / 'AGENTS.md'
        agents.write_text(INSTALL.BEGIN, encoding='utf-8')
        result = self.run_install('--with-agents')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(agents.read_text(encoding='utf-8'), INSTALL.BEGIN)
        self.assertFalse((self.project / '.agents').exists())

    def test_resolved_path_escape_is_refused(self):
        outside = self.project.parent / 'outside'
        with self.assertRaises(ValueError):
            INSTALL.inside(self.project, outside / 'SKILL.md')

    def test_global_configuration_target_is_refused(self):
        for name in ('.codex', '.agents'):
            target = self.project / name
            target.mkdir()
            with patch.object(INSTALL.Path, 'home', return_value=self.project):
                with self.assertRaisesRegex(ValueError, 'Global agent configuration'):
                    INSTALL.plan_install(target, True)
            self.assertEqual(list(target.iterdir()), [])

    def test_symlinked_parent_escape_if_supported(self):
        outside = self.project.parent / 'outside'
        outside.mkdir()
        try:
            os.symlink(outside, self.project / '.agents', target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlink unavailable on this host')
        result = self.run_install('--with-agents')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.project / 'AGENTS.md').exists())


if __name__ == '__main__':
    unittest.main()
