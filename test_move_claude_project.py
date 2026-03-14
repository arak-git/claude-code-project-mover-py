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


# ─────────────────────────────────────────────────────────────────────────────
# T7x-T8x: patch_mcp_json_files — Layer 2.5
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchMcpJsonFiles(unittest.TestCase):
    """Tests for Layer 2.5: .mcp.json patching in the project tree."""

    OLD = '/Users/you/oldproj'
    NEW = '/Users/you/newproj'

    def _make_mcp(self, tmpdir, data, subpath='.mcp.json'):
        """Helper: write a .mcp.json file (subpath relative to tmpdir)."""
        p = pathlib.Path(tmpdir) / subpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return p

    def _read(self, path):
        return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))

    def test_T73_env_value_patched_canonical_format(self):
        """Core path: env values patched in canonical mcpServers wrapper"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "type": "stdio",
                        "command": "python",
                        "args": ["-m", "kb.server"],
                        "env": {"KB_ROOT": "/Users/you/oldproj/data"}
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['KB_ROOT'],
                             '/Users/you/newproj/data')
            self.assertEqual(files, 1)
            self.assertGreater(fields, 0)
            self.assertEqual(len(errs), 0)

    def test_T74_env_value_patched_flat_format(self):
        """Flat format: no mcpServers wrapper, server configs at top level"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "memory": {
                    "command": "python",
                    "args": ["-m", "agent_recall.mcp_server"],
                    "env": {"RECALL_ROOT": "/Users/you/oldproj/recall"}
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['memory']['env']['RECALL_ROOT'],
                             '/Users/you/newproj/recall')
            self.assertEqual(files, 1)

    def test_T75_command_field_patched(self):
        """Absolute path in 'command' field is patched"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "custom": {
                        "command": "/Users/you/oldproj/venv/bin/python",
                        "args": ["-m", "my_server"]
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['custom']['command'],
                             '/Users/you/newproj/venv/bin/python')

    def test_T76_args_elements_patched(self):
        """Absolute paths in 'args' array elements are patched"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "command": "python",
                        "args": ["-m", "kb.server",
                                 "--config", "/Users/you/oldproj/config.yaml"]
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['args'][3],
                             '/Users/you/newproj/config.yaml')

    def test_T77_forward_slash_variant_patched(self):
        r"""Forward-slash C:/ matched when old_path uses backslash"""
        old_win = r'C:\Users\Yoda\Documents\proj'
        new_win = r'C:\Users\Yoda\proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "command": "python",
                        "env": {"ROOT": "C:/Users/Yoda/Documents/proj/data"}
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), old_win, new_win)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT'],
                             'C:/Users/Yoda/proj-new/data')

    def test_T78_backslash_variant_patched(self):
        r"""Backslash C:\ matched when old_path uses forward slash"""
        old_fwd = 'C:/Users/Yoda/Documents/proj'
        new_fwd = 'C:/Users/Yoda/proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "command": "python",
                        "env": {"ROOT": r"C:\Users\Yoda\Documents\proj\data"}
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), old_fwd, new_fwd)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT'],
                             r'C:\Users\Yoda\proj-new\data')

    def test_T79_no_match_file_unchanged(self):
        """File with no matching paths is not rewritten on disk"""
        with tempfile.TemporaryDirectory() as tmp:
            original_text = json.dumps({
                "mcpServers": {
                    "kb": {
                        "command": "python",
                        "env": {"ROOT": "/completely/different/path"}
                    }
                }
            }, indent=2)
            f = pathlib.Path(tmp) / '.mcp.json'
            f.write_text(original_text, encoding='utf-8')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(files, 0)
            self.assertEqual(fields, 0)
            self.assertEqual(f.read_text(encoding='utf-8'), original_text)

    def test_T80_subdirectory_mcp_json_found(self):
        """Nested sub/nested/.mcp.json discovered via rglob"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {"command": "python",
                           "env": {"ROOT": "/Users/you/oldproj/sub"}}
                }
            }, subpath='sub/nested/.mcp.json')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT'],
                             '/Users/you/newproj/sub')
            self.assertEqual(files, 1)

    def test_T81_multiple_servers_all_patched(self):
        """More than one server entry in the same file — all are patched"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {"command": "python",
                           "env": {"ROOT": "/Users/you/oldproj/kb"}},
                    "recall": {"command": "python",
                               "env": {"DATA": "/Users/you/oldproj/recall"}}
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT'],
                             '/Users/you/newproj/kb')
            self.assertEqual(data['mcpServers']['recall']['env']['DATA'],
                             '/Users/you/newproj/recall')
            self.assertEqual(files, 1)   # one file
            self.assertEqual(fields, 2)  # two env vars

    def test_T82_non_path_fields_untouched(self):
        """Fields like type, disabled, headers are preserved unchanged"""
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "type": "stdio",
                        "disabled": False,
                        "command": "python",
                        "env": {"ROOT": "/Users/you/oldproj/data"}
                    }
                }
            })
            mcp.patch_mcp_json_files(pathlib.Path(tmp), self.OLD, self.NEW)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['type'], 'stdio')
            self.assertFalse(data['mcpServers']['kb']['disabled'])

    def test_T83_empty_mcp_json_no_crash(self):
        """Empty {} .mcp.json file does not crash"""
        with tempfile.TemporaryDirectory() as tmp:
            self._make_mcp(tmp, {})
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(files, 0)
            self.assertEqual(fields, 0)
            self.assertEqual(len(errs), 0)

    def test_T84_no_mcp_json_returns_zero(self):
        """Directory without any .mcp.json returns (0, 0, [])"""
        with tempfile.TemporaryDirectory() as tmp:
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(files, 0)
            self.assertEqual(fields, 0)
            self.assertEqual(len(errs), 0)

    def test_T85_return_counts_correct(self):
        """Accurate files + fields counts with multiple files"""
        with tempfile.TemporaryDirectory() as tmp:
            # File 1: 2 patched fields (env + command)
            self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "command": "/Users/you/oldproj/bin/python",
                        "env": {"ROOT": "/Users/you/oldproj/data"}
                    }
                }
            }, subpath='.mcp.json')
            # File 2: 1 patched field (args element)
            self._make_mcp(tmp, {
                "mcpServers": {
                    "svc": {
                        "command": "python",
                        "args": ["/Users/you/oldproj/server.py"]
                    }
                }
            }, subpath='sub/.mcp.json')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(files, 2)
            self.assertEqual(fields, 3)

    def test_T86_malformed_json_in_errors(self):
        """Bad JSON is captured in errors list, not raised"""
        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / '.mcp.json'
            f.write_text('{ broken json !!!', encoding='utf-8')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(files, 0)
            self.assertEqual(len(errs), 1)
            self.assertIn('Malformed JSON', errs[0][1])

    def test_T87_mixed_slashes_same_file(self):
        r"""Both C:/ and C:\ paths in one file are both patched"""
        old_win = r'C:\Users\Yoda\Documents\proj'
        new_win = r'C:\Users\Yoda\proj-new'
        with tempfile.TemporaryDirectory() as tmp:
            f = self._make_mcp(tmp, {
                "mcpServers": {
                    "kb": {
                        "command": "python",
                        "env": {
                            "ROOT_FWD": "C:/Users/Yoda/Documents/proj/data",
                            "ROOT_BACK": r"C:\Users\Yoda\Documents\proj\data"
                        }
                    }
                }
            })
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), old_win, new_win)
            data = self._read(f)
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT_FWD'],
                             'C:/Users/Yoda/proj-new/data')
            self.assertEqual(data['mcpServers']['kb']['env']['ROOT_BACK'],
                             r'C:\Users\Yoda\proj-new\data')
            self.assertEqual(fields, 2)

    def test_T88_dry_run_no_write(self):
        """Dry run: counts reported but file content unchanged"""
        with tempfile.TemporaryDirectory() as tmp:
            original_text = json.dumps({
                "mcpServers": {
                    "kb": {"command": "python",
                           "env": {"ROOT": "/Users/you/oldproj/data"}}
                }
            }, indent=2)
            f = pathlib.Path(tmp) / '.mcp.json'
            f.write_text(original_text, encoding='utf-8')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW, dry_run=True)
            self.assertEqual(files, 1)   # reports what WOULD change
            self.assertEqual(fields, 1)
            self.assertEqual(f.read_text(encoding='utf-8'), original_text)  # unchanged


# ─────────────────────────────────────────────────────────────────────────────
# T9x: Dry run (integration)
# ─────────────────────────────────────────────────────────────────────────────

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

    def test_T89_dry_run_mcp_json_no_write(self):
        """Layer 2.5 dry run: .mcp.json must not change"""
        with tempfile.TemporaryDirectory() as tmp:
            original = json.dumps({
                "mcpServers": {
                    "kb": {"command": "python",
                           "env": {"ROOT": "/Users/you/oldproj/data"}}
                }
            }, indent=2)
            f = pathlib.Path(tmp) / '.mcp.json'
            f.write_text(original, encoding='utf-8')
            files, fields, errs = mcp.patch_mcp_json_files(
                pathlib.Path(tmp), self.OLD, self.NEW, dry_run=True)
            self.assertEqual(files, 1)  # reports what WOULD change
            self.assertEqual(f.read_text(encoding='utf-8'), original)  # file unchanged


# ─────────────────────────────────────────────────────────────────────────────
# T90x: Layer 4 — settings.local.json permission patching
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchSettingsLocal(unittest.TestCase):
    OLD = '/Users/you/oldproj'
    NEW = '/Users/you/newproj'

    def test_T90_forward_slash_permission_patched(self):
        """Layer 4: forward-slash path in permission string patched"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)',
                'Bash(ls "/Users/you/oldproj/docs")',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(patched, 1)
            self.assertEqual(total, 2)
            result = json.loads(f.read_text(encoding='utf-8'))
            self.assertIn('/Users/you/newproj/docs', result['permissions']['allow'][1])

    def test_T91_backslash_permission_patched(self):
        """Layer 4: backslash path in permission string patched"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(find "C:\\\\Users\\\\you\\\\oldproj\\\\data")',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp),
                'C:\\Users\\you\\oldproj', 'C:\\Users\\you\\newproj')
            self.assertEqual(patched, 1)
            result = json.loads(f.read_text(encoding='utf-8'))
            self.assertIn('newproj', result['permissions']['allow'][0])

    def test_T92_no_match_unchanged(self):
        """Layer 4: permissions without old path not modified"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": ['Bash(git:*)']}}
            f = claude_dir / 'settings.local.json'
            original = json.dumps(data, indent=2)
            f.write_text(original, encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(patched, 0)
            self.assertEqual(total, 1)

    def test_T93_missing_file_returns_zero(self):
        """Layer 4: missing settings.local.json returns (0, 0)"""
        with tempfile.TemporaryDirectory() as tmp:
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(patched, 0)
            self.assertEqual(total, 0)

    def test_T94_no_permissions_key_returns_zero(self):
        """Layer 4: JSON without permissions key returns (0, 0)"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            f = claude_dir / 'settings.local.json'
            f.write_text('{"other": "stuff"}', encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(patched, 0)
            self.assertEqual(total, 0)

    def test_T95_dry_run_no_write(self):
        """Layer 4 dry run: file unchanged, count still reports"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(ls "/Users/you/oldproj")',
            ]}}
            f = claude_dir / 'settings.local.json'
            original = json.dumps(data)
            f.write_text(original, encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW, dry_run=True)
            self.assertEqual(patched, 1)
            self.assertEqual(f.read_text(encoding='utf-8'), original)

    def test_T96_multiple_entries_patched(self):
        """Layer 4: multiple permission entries with old path all patched"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)',
                'Bash(ls "/Users/you/oldproj/a")',
                'Bash(cat "/Users/you/oldproj/b")',
                'Bash(git:*)',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            patched, total = mcp.patch_settings_local(
                pathlib.Path(tmp), self.OLD, self.NEW)
            self.assertEqual(patched, 2)
            self.assertEqual(total, 4)


# ─────────────────────────────────────────────────────────────────────────────
# T100x: Layer 5 — MEMORY.md + plan file patching
# ─────────────────────────────────────────────────────────────────────────────

class TestPatchMemoryMd(unittest.TestCase):
    OLD = '/Users/you/oldproj'
    NEW = '/Users/you/newproj'

    def test_T100_memory_md_patched(self):
        """Layer 5: MEMORY.md with old path is patched"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                encoded = mcp.encode_path(self.NEW)
                mem_dir = projects_dir / encoded / 'memory'
                mem_dir.mkdir(parents=True)
                f = mem_dir / 'MEMORY.md'
                f.write_text('Location: /Users/you/oldproj/data\n', encoding='utf-8')
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW)
                self.assertEqual(patched, 1)
                self.assertIn('/Users/you/newproj/data', f.read_text(encoding='utf-8'))

    def test_T101_memory_subfile_patched(self):
        """Layer 5: memory/*.md subfiles also patched"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                encoded = mcp.encode_path(self.NEW)
                mem_dir = projects_dir / encoded / 'memory'
                mem_dir.mkdir(parents=True)
                f1 = mem_dir / 'MEMORY.md'
                f1.write_text('clean content\n', encoding='utf-8')
                f2 = mem_dir / 'project_layout.md'
                f2.write_text('Root: /Users/you/oldproj\n', encoding='utf-8')
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW)
                self.assertEqual(patched, 1)
                self.assertEqual(total, 2)

    def test_T102_plan_files_patched(self):
        """Layer 5: plan files under ~/.claude/plans/ patched"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp) / 'projects'
                projects_dir.mkdir()
                encoded = mcp.encode_path(self.NEW)
                (projects_dir / encoded / 'memory').mkdir(parents=True)
                plans_dir = pathlib.Path(tmp) / 'plans'
                plans_dir.mkdir()
                f = plans_dir / 'golden-plan.md'
                f.write_text('Working dir: /Users/you/oldproj\n', encoding='utf-8')
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW)
                self.assertEqual(patched, 1)
                self.assertIn('/Users/you/newproj', f.read_text(encoding='utf-8'))

    def test_T103_no_memory_dir_returns_zero(self):
        """Layer 5: missing memory dir returns (0, 0) or just plan count"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW)
                self.assertEqual(patched, 0)

    def test_T104_dry_run_no_write(self):
        """Layer 5 dry run: files unchanged, count still reports"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                encoded = mcp.encode_path(self.NEW)
                mem_dir = projects_dir / encoded / 'memory'
                mem_dir.mkdir(parents=True)
                f = mem_dir / 'MEMORY.md'
                original = 'Location: /Users/you/oldproj\n'
                f.write_text(original, encoding='utf-8')
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW, dry_run=True)
                self.assertEqual(patched, 1)
                self.assertEqual(f.read_text(encoding='utf-8'), original)

    def test_T105_clean_files_not_patched(self):
        """Layer 5: files without old path not modified"""
        with patch('move_claude_project.platform') as mock_plat:
            mock_plat.system.return_value = 'Darwin'
            with tempfile.TemporaryDirectory() as tmp:
                projects_dir = pathlib.Path(tmp)
                encoded = mcp.encode_path(self.NEW)
                mem_dir = projects_dir / encoded / 'memory'
                mem_dir.mkdir(parents=True)
                f = mem_dir / 'MEMORY.md'
                f.write_text('No paths here\n', encoding='utf-8')
                patched, total = mcp.patch_memory_md(
                    projects_dir, self.OLD, self.NEW)
                self.assertEqual(patched, 0)
                self.assertEqual(total, 1)


# ─────────────────────────────────────────────────────────────────────────────
# T110x: Layer 4B — Phase B stale permission pruning
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractPathsFromPermission(unittest.TestCase):
    """Test the path extraction helper used by Phase B."""

    def test_T110_quoted_forward_slash_path(self):
        """Extracts quoted path with forward slashes"""
        paths = mcp.extract_paths_from_permission('Bash(ls "/Users/you/oldproj/docs")')
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], '/Users/you/oldproj/docs')

    def test_T111_quoted_escaped_backslash_path(self):
        """Extracts quoted path with escaped backslashes, unescapes for disk check"""
        paths = mcp.extract_paths_from_permission(
            'Bash(find "C:\\\\Users\\\\Yoda\\\\Downloads\\\\Claude Code")')
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], 'C:\\Users\\Yoda\\Downloads\\Claude Code')

    def test_T112_pattern_only_no_path(self):
        """Pattern-only entries return empty list"""
        for entry in ['Bash(python:*)', 'Bash(git add:*)',
                       'WebFetch(domain:github.com)', 'mcp__arun-kb__list_subsystems']:
            paths = mcp.extract_paths_from_permission(entry)
            self.assertEqual(paths, [], f'Expected no paths for: {entry}')

    def test_T113_read_path_extracted(self):
        """Read(//c/Users/...) extracts with drive letter conversion"""
        paths = mcp.extract_paths_from_permission('Read(//c/Users/Yoda/proj)')
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], 'C:/Users/Yoda/proj')

    def test_T114_multiple_quoted_paths(self):
        """Entry with two quoted paths extracts both"""
        entry = 'Bash(cp "/Users/you/a" "/Users/you/b")'
        paths = mcp.extract_paths_from_permission(entry)
        self.assertEqual(len(paths), 2)


class TestPruneStalePermissions(unittest.TestCase):

    def test_T115_stale_entries_identified(self):
        """Phase B: entries with non-existent paths identified as stale"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)',                          # pattern-only, skip
                'Bash(ls "/nonexistent/path/abc/xyz")',    # dead path
                'Bash(git:*)',                             # pattern-only, skip
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            pruned, backup, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=False)
            self.assertEqual(pruned, 0)  # not confirmed yet
            self.assertIsNone(backup)
            self.assertEqual(len(stale), 1)
            self.assertIn('/nonexistent/path/abc/xyz', stale[0])

    def test_T116_pattern_only_never_pruned(self):
        """Phase B: pattern-only entries are never candidates for pruning"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)', 'Bash(git add:*)',
                'WebFetch(domain:github.com)', 'mcp__arun-kb__list_subsystems',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            _, _, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=False)
            self.assertEqual(len(stale), 0)

    def test_T117_backup_file_written(self):
        """Phase B: backup file created with correct structure"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)',
                'Bash(ls "/nonexistent/path/abc/xyz")',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            pruned, backup, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=True)
            self.assertEqual(pruned, 1)
            self.assertIsNotNone(backup)
            backup_data = json.loads(pathlib.Path(backup).read_text(encoding='utf-8'))
            self.assertEqual(backup_data['entry_count'], 1)
            self.assertIn('pruned_entries', backup_data)
            self.assertIn('restore_instructions', backup_data)
            self.assertIn('pruned_at', backup_data)
            # Verify the stale entry was actually removed from settings
            result = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(len(result['permissions']['allow']), 1)
            self.assertEqual(result['permissions']['allow'][0], 'Bash(python:*)')

    def test_T118_dry_run_no_modification(self):
        """Phase B dry run: reports count but doesn't modify or create backup"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(ls "/nonexistent/dead/path/xyz")',
            ]}}
            f = claude_dir / 'settings.local.json'
            original = json.dumps(data)
            f.write_text(original, encoding='utf-8')
            pruned, backup, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), dry_run=True, confirmed=True)
            self.assertEqual(pruned, 1)
            self.assertIsNone(backup)  # no backup in dry run
            self.assertEqual(f.read_text(encoding='utf-8'), original)  # file unchanged

    def test_T119_not_confirmed_no_changes(self):
        """Phase B: unconfirmed returns stale list but makes no changes"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(ls "/nonexistent/dead/path/xyz")',
            ]}}
            f = claude_dir / 'settings.local.json'
            original = json.dumps(data)
            f.write_text(original, encoding='utf-8')
            pruned, backup, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=False)
            self.assertEqual(pruned, 0)
            self.assertIsNone(backup)
            self.assertEqual(len(stale), 1)
            self.assertEqual(f.read_text(encoding='utf-8'), original)

    def test_T120_existing_path_not_pruned(self):
        """Phase B: entries whose paths exist on disk are kept"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            # Create a real path that exists
            real_dir = pathlib.Path(tmp) / 'real_dir'
            real_dir.mkdir()
            real_path = str(real_dir).replace('\\', '/')
            data = {"permissions": {"allow": [
                f'Bash(ls "{real_path}")',                     # exists — keep
                'Bash(ls "/nonexistent/dead/path/xyz")',       # dead — prune
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            _, _, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=False)
            self.assertEqual(len(stale), 1)
            self.assertIn('/nonexistent/', stale[0])

    def test_T121_missing_settings_file(self):
        """Phase B: missing settings file returns zeros"""
        with tempfile.TemporaryDirectory() as tmp:
            pruned, backup, stale = mcp.prune_stale_permissions(pathlib.Path(tmp))
            self.assertEqual(pruned, 0)
            self.assertIsNone(backup)
            self.assertEqual(stale, [])

    def test_T122_multiple_stale_entries_all_pruned(self):
        """Phase B: multiple stale entries all removed, all in backup"""
        with tempfile.TemporaryDirectory() as tmp:
            claude_dir = pathlib.Path(tmp) / '.claude'
            claude_dir.mkdir()
            data = {"permissions": {"allow": [
                'Bash(python:*)',
                'Bash(ls "/nonexistent/aaa")',
                'Bash(cat "/nonexistent/bbb")',
                'Bash(find "/nonexistent/ccc")',
                'Bash(git:*)',
            ]}}
            f = claude_dir / 'settings.local.json'
            f.write_text(json.dumps(data), encoding='utf-8')
            pruned, backup, stale = mcp.prune_stale_permissions(
                pathlib.Path(tmp), confirmed=True)
            self.assertEqual(pruned, 3)
            result = json.loads(f.read_text(encoding='utf-8'))
            self.assertEqual(len(result['permissions']['allow']), 2)
            self.assertEqual(result['permissions']['allow'][0], 'Bash(python:*)')
            self.assertEqual(result['permissions']['allow'][1], 'Bash(git:*)')
            backup_data = json.loads(pathlib.Path(backup).read_text(encoding='utf-8'))
            self.assertEqual(backup_data['entry_count'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
