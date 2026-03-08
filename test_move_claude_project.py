"""
TDD suite for move_claude_project.py
Run: python test_move_claude_project.py -v

Tests are written against expected behavior BEFORE implementation is fixed.
Failures reveal bugs in the script.
"""
import sys, os, json, pathlib, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import move_claude_project as mcp


# ─────────────────────────────────────────────────────────────────────────────
# T1x: encode_path — Windows
# ─────────────────────────────────────────────────────────────────────────────

class TestEncodePathWindows(unittest.TestCase):
    """
    Empirically verified: Claude Code encodes ALL non-alphanumeric chars as '-'.
    Known truth: C:\\Users\\Yoda\\Downloads\\Claude Code -> C--Users-Yoda-Downloads-Claude-Code
                 (space in 'Claude Code' becomes '-')
    """

    def _enc(self, p):
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Windows'
            return mcp.encode_path(p)

    def test_T01_basic_windows_path(self):
        """Colon and backslashes become dashes"""
        self.assertEqual(self._enc(r'C:\Users\Yoda\Documents'), 'C--Users-Yoda-Documents')

    def test_T02_space_in_path_becomes_dash(self):
        """Space in path component must become dash (empirically observed)"""
        result = self._enc(r'C:\Users\Yoda\Downloads\Claude Code')
        self.assertEqual(result, 'C--Users-Yoda-Downloads-Claude-Code')

    def test_T03_existing_dash_preserved(self):
        """A hyphen already in the path stays as a hyphen"""
        result = self._enc(r'C:\Users\Yoda\Documents\Claude-Code')
        self.assertEqual(result, 'C--Users-Yoda-Documents-Claude-Code')

    def test_T04_forward_slashes_on_windows(self):
        """Forward slashes (less common on Windows) also become dashes"""
        result = self._enc('C:/Users/Yoda/Documents')
        self.assertEqual(result, 'C--Users-Yoda-Documents')


# ─────────────────────────────────────────────────────────────────────────────
# T2x: encode_path — Unix (macOS / Linux)
# ─────────────────────────────────────────────────────────────────────────────

class TestEncodePathUnix(unittest.TestCase):

    def _enc(self, p):
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            return mcp.encode_path(p)

    def test_T10_basic_unix_path(self):
        """Leading slash and separators become dashes"""
        self.assertEqual(self._enc('/Users/martin/myproject'), '-Users-martin-myproject')

    def test_T11_dotfile_directory(self):
        """Hidden directories (/.name) encoded as double-dash per community convention"""
        result = self._enc('/Users/martin/.config/myproject')
        self.assertEqual(result, '-Users-martin--config-myproject')


# ─────────────────────────────────────────────────────────────────────────────
# T3x: patch_metadata_files — Layer 1 correctness
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchMetadataFiles(unittest.TestCase):

    OLD = r'C:\Users\Yoda\Downloads\Claude Code'
    NEW = r'C:\Users\Yoda\Documents\Claude-Code'

    def _make_session(self, tmpdir, name, cwd, origin_cwd=None, plan_path=None):
        """Helper: write a local_*.json session file"""
        d = {
            "sessionId": f"local_{name}",
            "cwd": cwd,
            "originCwd": origin_cwd or cwd,
            "title": "Test session",
            "model": "claude-opus-4",
        }
        if plan_path is not None:
            d["planPath"] = plan_path
        p = pathlib.Path(tmpdir) / f"local_{name}.json"
        p.write_text(json.dumps(d), encoding='utf-8')
        return p

    def _read(self, path):
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

    def test_T20_exact_cwd_match_is_patched(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_session(tmp, 'aaa', self.OLD)
            mcp.patch_metadata_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['cwd'], self.NEW)
            self.assertEqual(data['originCwd'], self.NEW)

    def test_T21_prefix_collision_not_patched(self):
        """A cwd that merely CONTAINS OLD as a prefix must NOT be patched.
        Bug in current script: uses 'in' (substring) instead of '==' (exact).
        e.g. OLD='/proj', cwd='/proj-backup' should NOT be patched."""
        old = '/Users/you/proj'
        new = '/Users/you/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            # This cwd starts with OLD but is a different project
            f = self._make_session(tmp, 'bbb', '/Users/you/proj-backup')
            mcp.patch_metadata_files(pathlib.Path(tmp), old, new)
            data = self._read(f)
            # Should NOT have been patched
            self.assertEqual(data['cwd'], '/Users/you/proj-backup',
                             "PREFIX COLLISION BUG: cwd '/Users/you/proj-backup' was "
                             "incorrectly patched because OLD '/Users/you/proj' is a substring")

    def test_T22_already_correct_path_skipped(self):
        """Session already pointing at NEW must not be double-patched"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_session(tmp, 'ccc', self.NEW)
            mcp.patch_metadata_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['cwd'], self.NEW)

    def test_T23_plan_path_not_patched_when_unrelated(self):
        """planPath under ~/.claude/plans/ does NOT contain the project dir path"""
        plan = r'C:\Users\Yoda\.claude\plans\some-plan.md'
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_session(tmp, 'ddd', self.OLD, plan_path=plan)
            mcp.patch_metadata_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            # planPath should be unchanged (OLD is not in planPath)
            self.assertEqual(data.get('planPath'), plan)

    def test_T24_null_plan_path_handled(self):
        """planPath = null (JSON null) must not cause TypeError"""
        with tempfile.TemporaryDirectory() as tmp:
            raw = {"sessionId": "local_eee", "cwd": self.OLD, "originCwd": self.OLD,
                   "title": "t", "model": "m", "planPath": None}
            p = pathlib.Path(tmp) / 'local_eee.json'
            p.write_text(json.dumps(raw), encoding='utf-8')
            # Should not raise
            mcp.patch_metadata_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(p)
            self.assertEqual(data['cwd'], self.NEW)

    def test_T25_nested_subdirectory_found(self):
        """Files in <acct>/<org>/ subdirectory must be found via rglob"""
        with tempfile.TemporaryDirectory() as tmp:
            subdir = pathlib.Path(tmp) / 'acct-uuid' / 'org-uuid'
            subdir.mkdir(parents=True)
            f = subdir / 'local_fff.json'
            f.write_text(json.dumps({
                "sessionId": "local_fff", "cwd": self.OLD,
                "originCwd": self.OLD, "title": "t", "model": "m"
            }), encoding='utf-8')
            mcp.patch_metadata_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['cwd'], self.NEW)


# ─────────────────────────────────────────────────────────────────────────────
# T4x: patch_claude_json — Layer 2
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchClaudeJson(unittest.TestCase):

    def test_T30_unix_key_patched(self):
        old, new = '/Users/you/oldproj', '/Users/you/newproj'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / '.claude.json'
            cfg.write_text(json.dumps({
                "projects": {old: {"allowedTools": []}}
            }), encoding='utf-8')
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old, new)
            data = json.loads(cfg.read_text(encoding='utf-8'))
            self.assertIn(new, data['projects'])
            self.assertNotIn(old, data['projects'])
            self.assertEqual(keys, 1)

    def test_T31_windows_backslash_key_converted(self):
        """~/.claude.json always uses forward slashes; backslash OLD_PATH must be converted"""
        old_win = r'C:\Users\Yoda\Downloads\Claude Code'
        new_win = r'C:\Users\Yoda\Documents\Claude-Code'
        old_fwd = 'C:/Users/Yoda/Downloads/Claude Code'
        new_fwd = 'C:/Users/Yoda/Documents/Claude-Code'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / '.claude.json'
            cfg.write_text(json.dumps({
                "projects": {old_fwd: {"allowedTools": []}}
            }), encoding='utf-8')
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old_win, new_win)
            data = json.loads(cfg.read_text(encoding='utf-8'))
            self.assertIn(new_fwd, data['projects'])
            self.assertNotIn(old_fwd, data['projects'])

    def test_T32_missing_key_no_crash(self):
        """If old key not found, function should not crash or corrupt the file"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / '.claude.json'
            orig = {"projects": {"other/path": {}}}
            cfg.write_text(json.dumps(orig), encoding='utf-8')
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), '/old/path', '/new/path')
            data = json.loads(cfg.read_text(encoding='utf-8'))
            self.assertEqual(data, orig)  # unchanged
            self.assertEqual(keys, 0)

    def test_T33_missing_projects_key_no_crash(self):
        """~/.claude.json without 'projects' key should not crash"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / '.claude.json'
            cfg.write_text(json.dumps({"version": 1}), encoding='utf-8')
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), '/old', '/new')
            self.assertEqual(keys, 0)
            self.assertEqual(envs, 0)


# ─────────────────────────────────────────────────────────────────────────────
# T5x: patch_project_folder — Layer 3
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchProjectFolder(unittest.TestCase):

    def _make_jsonl(self, path, content_lines):
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(path).write_text('\n'.join(content_lines), encoding='utf-8')

    def test_T40_folder_renamed_when_old_exists_new_does_not(self):
        old = '/Users/you/oldproj'
        new = '/Users/you/newproj'
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                old_folder = projects_dir / '-Users-you-oldproj'
                old_folder.mkdir()
                (old_folder / 'session.jsonl').write_text('{}', encoding='utf-8')
                mcp.patch_project_folder(projects_dir, old, new)
                new_folder = projects_dir / '-Users-you-newproj'
                self.assertTrue(new_folder.exists(), "New folder should exist after rename")
                self.assertFalse(old_folder.exists(), "Old folder should be gone after rename")

    def test_T41_no_rename_when_both_exist(self):
        """If both old and new folders exist, no rename occurs (manual merge needed)"""
        old = '/Users/you/oldproj'
        new = '/Users/you/newproj'
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                (projects_dir / '-Users-you-oldproj').mkdir()
                (projects_dir / '-Users-you-newproj').mkdir()
                # Should not raise, and both should still exist
                mcp.patch_project_folder(projects_dir, old, new)
                self.assertTrue((projects_dir / '-Users-you-oldproj').exists())
                self.assertTrue((projects_dir / '-Users-you-newproj').exists())

    def test_T42_jsonl_patched_in_root(self):
        """Top-level .jsonl file in project folder is patched"""
        old, new = '/Users/you/oldproj', '/Users/you/newproj'
        line = json.dumps({"cwd": old, "type": "summary"})
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                new_folder = projects_dir / '-Users-you-newproj'
                new_folder.mkdir()
                f = new_folder / 'session.jsonl'
                f.write_text(line, encoding='utf-8')
                mcp.patch_project_folder(projects_dir, old, new)
                self.assertIn(new, f.read_text(encoding='utf-8'))
                self.assertNotIn(old, f.read_text(encoding='utf-8'))

    def test_T43_jsonl_patched_in_subagents(self):
        """Subagent .jsonl under <uuid>/subagents/ is patched recursively"""
        old, new = '/Users/you/oldproj', '/Users/you/newproj'
        line = json.dumps({"cwd": old, "type": "summary"})
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                subdir = projects_dir / '-Users-you-newproj' / 'abc123' / 'subagents'
                subdir.mkdir(parents=True)
                f = subdir / 'sub.jsonl'
                f.write_text(line, encoding='utf-8')
                mcp.patch_project_folder(projects_dir, old, new)
                self.assertIn(new, f.read_text(encoding='utf-8'))

    def test_T44_windows_double_backslash_encoding(self):
        """On Windows, paths in .jsonl are JSON-escaped (double backslash on disk)"""
        old_win = r'C:\Users\Yoda\Downloads\Claude Code'
        new_win = r'C:\Users\Yoda\Documents\Claude-Code'
        # As it appears on disk in a .jsonl (JSON-encoded)
        line_on_disk = r'{"cwd":"C:\\Users\\Yoda\\Downloads\\Claude Code"}'
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Windows'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                folder = projects_dir / 'C--Users-Yoda-Documents-Claude-Code'
                folder.mkdir()
                f = folder / 'session.jsonl'
                f.write_text(line_on_disk, encoding='utf-8')
                mcp.patch_project_folder(projects_dir, old_win, new_win)
                result = f.read_text(encoding='utf-8')
                self.assertIn(r'C:\\Users\\Yoda\\Documents\\Claude-Code', result)
                self.assertNotIn(r'C:\\Users\\Yoda\\Downloads\\Claude Code', result)


# ─────────────────────────────────────────────────────────────────────────────
# T6x: verify_sessions — verification step
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifySessions(unittest.TestCase):

    def test_T50_all_valid_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = pathlib.Path(tmp)
            sessions_dir = real_dir / 'sessions'
            sessions_dir.mkdir()
            f = sessions_dir / 'local_x.json'
            f.write_text(json.dumps({"cwd": str(real_dir), "originCwd": str(real_dir)}),
                         encoding='utf-8')
            ok, missing = mcp.verify_sessions(sessions_dir)
            self.assertTrue(ok)
            self.assertEqual(missing, [])

    def test_T51_missing_path_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = pathlib.Path(tmp) / 'sessions'
            sessions_dir.mkdir()
            f = sessions_dir / 'local_y.json'
            f.write_text(json.dumps({"cwd": "/nonexistent/path/xyz"}), encoding='utf-8')
            ok, missing = mcp.verify_sessions(sessions_dir)
            self.assertFalse(ok)
            self.assertEqual(len(missing), 1)
            self.assertIn('/nonexistent/path/xyz', missing[0])


# ─────────────────────────────────────────────────────────────────────────────
# T6x: B4/B5/B7 — sub-project keys, collision merge, MCP env vars
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchClaudeJsonAdvanced(unittest.TestCase):
    """Tests for B4 (prefix key matching), B5 (MCP env vars), B7 (collision merge)."""

    def _make_cfg(self, tmp, projects_dict):
        cfg = pathlib.Path(tmp) / '.claude.json'
        cfg.write_text(json.dumps({"projects": projects_dict}), encoding='utf-8')
        return cfg

    def _read(self, cfg):
        return json.loads(pathlib.Path(cfg).read_text(encoding='utf-8'))

    def test_T60_sub_project_key_renamed(self):
        """B4: A sub-project key old/path/sub must be renamed to new/path/sub"""
        old, new = '/Users/you/proj', '/Users/you/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                '/Users/you/proj': {"allowedTools": []},
                '/Users/you/proj/sub': {"allowedTools": ["bash"]},
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old, new)
            data = self._read(cfg)
            self.assertIn('/Users/you/proj-new', data['projects'])
            self.assertIn('/Users/you/proj-new/sub', data['projects'])
            self.assertNotIn('/Users/you/proj', data['projects'])
            self.assertNotIn('/Users/you/proj/sub', data['projects'])
            self.assertEqual(keys, 2)

    def test_T61_backslash_variant_key_renamed(self):
        r"""B4: A key using backslashes C:\old\path must also be renamed"""
        old_win = r'C:\Users\Yoda\Documents\Claude-Code'
        new_win = r'C:\Users\Yoda\claude-code-projects'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                'C:/Users/Yoda/Documents/Claude-Code': {"mcpServers": {"kb": {}}},
                'C:\\Users\\Yoda\\Documents\\Claude-Code': {"allowedTools": []},
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old_win, new_win)
            data = self._read(cfg)
            # Both old keys should be gone
            self.assertNotIn('C:/Users/Yoda/Documents/Claude-Code', data['projects'])
            self.assertNotIn('C:\\Users\\Yoda\\Documents\\Claude-Code', data['projects'])
            # New key should exist
            self.assertIn('C:/Users/Yoda/claude-code-projects', data['projects'])
            self.assertEqual(keys, 2)

    def test_T62_collision_merge_keeps_richer_config(self):
        """B7: When two keys normalize to same new key, the one with mcpServers survives"""
        old_win = r'C:\Users\Yoda\Documents\proj'
        new_win = r'C:\Users\Yoda\proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                # Key A: has MCP servers (richer)
                'C:/Users/Yoda/Documents/proj': {
                    "mcpServers": {"arun-kb": {"type": "stdio"}},
                    "hasTrustDialogAccepted": True,
                },
                # Key B: backslash variant, no MCP servers (sparser)
                'C:\\Users\\Yoda\\Documents\\proj': {
                    "mcpServers": {},
                    "hasTrustDialogAccepted": True,
                },
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old_win, new_win)
            data = self._read(cfg)
            new_key = 'C:/Users/Yoda/proj-new'
            self.assertIn(new_key, data['projects'])
            # The richer config (with mcpServers) must survive
            self.assertIn('arun-kb', data['projects'][new_key].get('mcpServers', {}))
            # Trust must be merged (True from either)
            self.assertTrue(data['projects'][new_key].get('hasTrustDialogAccepted'))

    def test_T63_mcp_env_var_same_project_patched(self):
        """B5: MCP env var value containing old_path is patched in the same project entry"""
        old, new = '/Users/you/proj', '/Users/you/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                '/Users/you/proj': {
                    "mcpServers": {
                        "kb": {
                            "type": "stdio",
                            "env": {"KB_ROOT": "/Users/you/proj/data"}
                        }
                    }
                }
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old, new)
            data = self._read(cfg)
            env_val = data['projects']['/Users/you/proj-new']['mcpServers']['kb']['env']['KB_ROOT']
            self.assertEqual(env_val, '/Users/you/proj-new/data')
            self.assertGreater(envs, 0)

    def test_T64_mcp_env_var_different_project_patched(self):
        """B5: MCP env var in a DIFFERENT project key (F: backup scenario) is also patched"""
        old, new = '/Users/you/proj', '/Users/you/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                '/Users/you/proj': {"allowedTools": []},
                'F:/backup/proj-copy': {
                    "mcpServers": {
                        "kb": {
                            "type": "stdio",
                            "env": {"KB_ROOT": "/Users/you/proj/data"}
                        }
                    }
                }
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old, new)
            data = self._read(cfg)
            # F: key should NOT be renamed (different prefix)
            self.assertIn('F:/backup/proj-copy', data['projects'])
            # But its env var should be patched
            env_val = data['projects']['F:/backup/proj-copy']['mcpServers']['kb']['env']['KB_ROOT']
            self.assertEqual(env_val, '/Users/you/proj-new/data')
            self.assertGreater(envs, 0)

    def test_T65_return_value_is_key_count(self):
        """B4: Return value first element is count of keys renamed"""
        old, new = '/Users/you/proj', '/Users/you/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                '/Users/you/proj': {},
                '/Users/you/proj/sub1': {},
                '/Users/you/proj/sub2': {},
                '/unrelated/path': {},
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old, new)
            self.assertEqual(keys, 3)  # main + 2 sub-projects
            data = self._read(cfg)
            self.assertIn('/unrelated/path', data['projects'])  # not renamed

    def test_T66_backslash_env_var_patched(self):
        r"""B5: Env var using backslash C:\old\path\sub is also patched"""
        old_win = r'C:\Users\Yoda\Documents\Claude-Code'
        new_win = r'C:\Users\Yoda\claude-code-projects'
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._make_cfg(tmp, {
                'F:/backup': {
                    "mcpServers": {
                        "kb": {
                            "type": "stdio",
                            "env": {
                                "KB_ROOT": r"C:\Users\Yoda\Documents\Claude-Code\data"
                            }
                        }
                    }
                }
            })
            keys, envs = mcp.patch_claude_json(pathlib.Path(tmp), old_win, new_win)
            data = self._read(cfg)
            env_val = data['projects']['F:/backup']['mcpServers']['kb']['env']['KB_ROOT']
            self.assertEqual(env_val, r'C:\Users\Yoda\claude-code-projects\data')
            self.assertEqual(keys, 0)  # F:/backup doesn't match old path
            self.assertGreater(envs, 0)


class TestDryRun(unittest.TestCase):
    """Verify --dry-run does not write to any files."""

    OLD = '/Users/you/oldproj'
    NEW = '/Users/you/newproj'

    def test_T70_dry_run_metadata_no_write(self):
        """Layer 1 dry run: file content must not change"""
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / 'local_aaa.json'
            original = json.dumps({"sessionId": "local_aaa", "cwd": self.OLD,
                                   "originCwd": self.OLD, "title": "t", "model": "m"})
            f.write_text(original, encoding='utf-8')
            patched, _, _ = mcp.patch_metadata_files(
                pathlib.Path(tmp), self.OLD, self.NEW, dry_run=True)
            self.assertEqual(patched, 1)  # reports what WOULD change
            self.assertEqual(f.read_text(encoding='utf-8'), original)  # file unchanged

    def test_T71_dry_run_claude_json_no_write(self):
        """Layer 2 dry run: .claude.json must not change"""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = pathlib.Path(tmp) / '.claude.json'
            original = json.dumps({"projects": {self.OLD: {"allowedTools": []}}})
            cfg.write_text(original, encoding='utf-8')
            keys, envs = mcp.patch_claude_json(
                pathlib.Path(tmp), self.OLD, self.NEW, dry_run=True)
            self.assertEqual(keys, 1)
            self.assertEqual(cfg.read_text(encoding='utf-8'), original)  # file unchanged

    def test_T72_dry_run_project_folder_no_rename(self):
        """Layer 3 dry run: folder must not be renamed, .jsonl must not change"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                old_folder = projects_dir / '-Users-you-oldproj'
                old_folder.mkdir()
                f = old_folder / 'session.jsonl'
                line = json.dumps({"cwd": self.OLD})
                f.write_text(line, encoding='utf-8')
                renamed, count = mcp.patch_project_folder(
                    projects_dir, self.OLD, self.NEW, dry_run=True)
                self.assertTrue(renamed)  # reports it WOULD rename
                self.assertTrue(old_folder.exists())  # but folder unchanged
                self.assertFalse((projects_dir / '-Users-you-newproj').exists())
                self.assertEqual(f.read_text(encoding='utf-8'), line)  # content unchanged


if __name__ == '__main__':
    unittest.main(verbosity=2)
