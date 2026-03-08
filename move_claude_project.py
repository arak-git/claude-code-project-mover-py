#!/usr/bin/env python3
"""
Claude Code Project Mover — cross-platform (Windows, macOS, Linux)

Usage:
  python move_claude_project.py OLD_PATH NEW_PATH [--dry-run]

Importable module: functions can be imported by test_move_claude_project.py
"""
import sys, os, json, pathlib, platform, re

__version__ = '2.0.0'

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ─────────────────────────────────────────────────────────────────────────────
# Core functions (importable)
# ─────────────────────────────────────────────────────────────────────────────

def get_sessions_dir():
    """Return the OS-native Claude Code session metadata directory."""
    home = pathlib.Path.home()
    system = platform.system()
    if system == 'Windows':
        return pathlib.Path(os.environ['APPDATA']) / 'Claude' / 'claude-code-sessions'
    elif system == 'Darwin':
        return home / 'Library' / 'Application Support' / 'Claude' / 'claude-code-sessions'
    else:  # Linux / XDG
        xdg = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', home / '.config'))
        return xdg / 'Claude' / 'claude-code-sessions'


def encode_path(p):
    """
    Encode an absolute path to the folder-name format used by
    ~/.claude/projects/<encoded>.

    Observed behavior:
      Windows: C:\\Users\\You\\Downloads\\Claude Code -> C--Users-You-Downloads-Claude-Code
      Unix:    /Users/martin/myproject                -> -Users-martin-myproject
               /Users/martin/.config/proj             -> -Users-martin--config-proj
    """
    system = platform.system()
    if system == 'Windows':
        # Replace : \ / with -.  Spaces also become - (empirically confirmed).
        return re.sub(r'[:\\/\s]', '-', p)
    else:
        # macOS / Linux: /. (hidden dir separator) -> -- ; / -> -
        return p.replace('/.', '--').replace('/', '-')


def patch_metadata_files(sessions_dir, old_path, new_path, dry_run=False):
    """
    Layer 1: patch cwd, originCwd, planPath in all local_*.json metadata files.

    Returns (patched_count, skipped_count, errors).
    """
    sessions_dir = pathlib.Path(sessions_dir)
    patched = skipped = 0
    errors = []

    for f in sorted(sessions_dir.rglob('local_*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            changed = False

            # cwd and originCwd: EXACT match only (avoid prefix collisions)
            for field in ('cwd', 'originCwd'):
                val = data.get(field)
                if val == old_path:
                    data[field] = new_path
                    changed = True

            # planPath: substring match (plan path may embed project dir)
            val = data.get('planPath')
            if isinstance(val, str) and old_path in val:
                data['planPath'] = val.replace(old_path, new_path)
                changed = True

            if changed:
                if not dry_run:
                    f.write_text(json.dumps(data, indent=2), encoding='utf-8')
                patched += 1
            else:
                skipped += 1

        except Exception as e:
            errors.append((f.name, str(e)))

    return patched, skipped, errors


def patch_mcp_env_vars(data, old_path, new_path):
    """
    Patch MCP server env var VALUES containing old_path across ALL project entries.

    Handles both forward-slash and backslash variants of the old path.
    Operates on the in-memory dict (caller writes to disk).

    Returns count of env vars patched.
    """
    old_fwd = old_path.replace('\\', '/')
    new_fwd = new_path.replace('\\', '/')
    old_back = old_path.replace('/', '\\')
    new_back = new_path.replace('/', '\\')
    count = 0
    for proj_val in data.get('projects', {}).values():
        for srv_cfg in proj_val.get('mcpServers', {}).values():
            env = srv_cfg.get('env', {})
            for env_key, env_val in list(env.items()):
                if isinstance(env_val, str):
                    new_val = env_val
                    if old_fwd in new_val:
                        new_val = new_val.replace(old_fwd, new_fwd)
                    if old_back in new_val:
                        new_val = new_val.replace(old_back, new_back)
                    if new_val != env_val:
                        env[env_key] = new_val
                        count += 1
    return count


def patch_claude_json(home, old_path, new_path, dry_run=False):
    """
    Layer 2: rename project keys in ~/.claude.json + patch MCP env vars.

    Handles:
      B4 — sub-project keys (prefix + '/' match) and backslash variants
      B5 — MCP env var values containing old_path (all project entries)
      B7 — collision merging when backslash and forward-slash keys normalize
           to the same new key (keeps entry with most mcpServers)

    Returns (keys_renamed: int, env_vars_patched: int).
    """
    home = pathlib.Path(home)
    claude_json = home / '.claude.json'
    if not claude_json.exists():
        return 0, 0

    data = json.loads(claude_json.read_text(encoding='utf-8'))
    projects = data.get('projects')
    if not isinstance(projects, dict):
        return 0, 0

    old_fwd = old_path.replace('\\', '/')
    new_fwd = new_path.replace('\\', '/')

    # Find ALL keys that match: exact, prefix+/, or backslash variant
    keys_to_rename = {}
    for key in list(projects.keys()):
        key_fwd = key.replace('\\', '/')
        if key_fwd == old_fwd or key_fwd.startswith(old_fwd + '/'):
            new_key = new_fwd + key_fwd[len(old_fwd):]   # preserve suffix
            keys_to_rename[key] = new_key

    keys_count = len(keys_to_rename)

    if keys_to_rename:
        # Group by new_key to detect collisions (B7)
        rename_groups = {}
        for old_k, new_k in keys_to_rename.items():
            rename_groups.setdefault(new_k, []).append((old_k, projects.pop(old_k)))

        for new_k, candidates in rename_groups.items():
            if len(candidates) == 1:
                projects[new_k] = candidates[0][1]
            else:
                # Collision: keep the entry with the most mcpServers (richest config)
                best_val = max(
                    (c[1] for c in candidates),
                    key=lambda v: len(v.get('mcpServers', {}))
                )
                # Merge hasTrustDialogAccepted: True if ANY had True
                trust = any(c[1].get('hasTrustDialogAccepted', False) for c in candidates)
                best_val['hasTrustDialogAccepted'] = trust
                projects[new_k] = best_val

    # B5: patch MCP env vars across ALL project entries (including unrelated ones)
    env_count = patch_mcp_env_vars(data, old_path, new_path)

    if keys_count > 0 or env_count > 0:
        if not dry_run:
            claude_json.write_text(json.dumps(data, indent=2), encoding='utf-8')

    return keys_count, env_count


def patch_project_folder(projects_dir, old_path, new_path, dry_run=False):
    """
    Layer 3: rename the ~/.claude/projects/<encoded> folder (if needed),
    then patch all .jsonl files inside it recursively.

    Returns (renamed: bool, jsonl_patched: int).
    """
    projects_dir = pathlib.Path(projects_dir)
    old_encoded = encode_path(old_path)
    new_encoded = encode_path(new_path)

    old_folder = projects_dir / old_encoded
    new_folder = projects_dir / new_encoded

    renamed = False
    if old_folder.exists() and not new_folder.exists():
        if not dry_run:
            old_folder.rename(new_folder)
        renamed = True
    # (if both exist or neither: no rename; handled by caller reporting)

    target = new_folder if new_folder.exists() else old_folder
    if not target.exists():
        return renamed, 0

    # Windows: paths in .jsonl are JSON-escaped (backslashes doubled on disk)
    if platform.system() == 'Windows':
        old_str = old_path.replace('\\', '\\\\')
        new_str = new_path.replace('\\', '\\\\')
    else:
        old_str = old_path
        new_str = new_path

    count = 0
    for f in target.rglob('*.jsonl'):
        try:
            text = f.read_text(encoding='utf-8', errors='replace')
            if old_str in text:
                if not dry_run:
                    f.write_text(text.replace(old_str, new_str), encoding='utf-8')
                count += 1
        except Exception:
            pass

    return renamed, count


def verify_sessions(sessions_dir):
    """
    Check that all cwd paths in local_*.json files exist on disk.
    Returns (all_ok: bool, missing: list[str]).
    """
    sessions_dir = pathlib.Path(sessions_dir)
    missing = []
    for f in sorted(sessions_dir.rglob('local_*.json')):
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
            cwd = data.get('cwd', '')
            if cwd and not pathlib.Path(cwd).exists():
                missing.append(f'{cwd}  ({f.name})')
        except Exception as e:
            missing.append(f'ERROR reading {f.name}: {e}')
    return (len(missing) == 0), missing


# ─────────────────────────────────────────────────────────────────────────────
# Full migration runner
# ─────────────────────────────────────────────────────────────────────────────

def run_migration(old_path, new_path, dry_run=False):
    home = pathlib.Path.home()

    if dry_run:
        print('*** DRY RUN MODE — no files will be modified ***\n')

    print('=== Layer 1: session metadata ===')
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        print(f'  WARNING: sessions dir not found: {sessions_dir}')
        print('  On Linux, try: find ~/.config -name "local_*.json" | head -5')
    else:
        patched, skipped, errors = patch_metadata_files(
            sessions_dir, old_path, new_path, dry_run=dry_run)
        print(f'  Patched: {patched}, Skipped: {skipped}, Errors: {len(errors)}')
        for name, err in errors:
            print(f'  ERROR {name}: {err}')

    print('\n=== Layer 2: ~/.claude.json ===')
    keys_renamed, env_vars_patched = patch_claude_json(
        home, old_path, new_path, dry_run=dry_run)
    if keys_renamed > 0 or env_vars_patched > 0:
        print(f'  Keys renamed: {keys_renamed}, MCP env vars patched: {env_vars_patched}')
    else:
        print('  No matching key found (or file absent)')

    print('\n=== Layer 3: ~/.claude/projects ===')
    projects_dir = home / '.claude' / 'projects'
    old_encoded = encode_path(old_path)
    new_encoded = encode_path(new_path)
    old_folder = projects_dir / old_encoded
    new_folder = projects_dir / new_encoded

    if old_folder.exists() and not new_folder.exists():
        print(f'  Renaming: {old_encoded} -> {new_encoded}')
    elif old_folder.exists() and new_folder.exists():
        print('  WARNING: both old and new folders exist — manual merge may be needed')
        print('  Compare .jsonl record counts; keep the larger file per UUID')
    elif not old_folder.exists() and new_folder.exists():
        print(f'  Folder already at new location: {new_encoded}')
    else:
        print(f'  WARNING: project folder not found at either old or new encoded path')
        print(f'    old: {old_encoded}')
        print(f'    new: {new_encoded}')

    renamed, jsonl_count = patch_project_folder(
        projects_dir, old_path, new_path, dry_run=dry_run)
    print(f'  Patched {jsonl_count} .jsonl files')

    if dry_run:
        print('\n=== Dry run complete — no files were modified ===')
    else:
        print('\n=== Verification ===')
        if sessions_dir.exists():
            ok, missing = verify_sessions(sessions_dir)
            if ok:
                print('  All session cwd paths exist.')
                print('  RESTART Claude Code to apply changes.')
            else:
                for m in missing:
                    print(f'  MISSING: {m}')


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='Fix Claude Code sessions after moving a project folder.',
        epilog='Example: python move_claude_project.py /old/path /new/path --dry-run',
    )
    parser.add_argument('old_path', help='Original absolute path of the project folder')
    parser.add_argument('new_path', help='New absolute path where the folder now lives')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without writing any files')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {__version__}')
    args = parser.parse_args()
    run_migration(args.old_path, args.new_path, dry_run=args.dry_run)
