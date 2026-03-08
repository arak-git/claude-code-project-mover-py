#!/usr/bin/env python3
"""
Claude Code Project Mover — cross-platform (Windows, macOS, Linux)

Usage:
  1. Edit OLD_PATH and NEW_PATH at the bottom of this file
  2. Run: python move_claude_project.py

Importable module: functions can be imported by test_move_claude_project.py
"""
import sys, os, json, pathlib, platform

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
      Windows: C:\\Users\\Yoda\\Downloads\\Claude Code -> C--Users-Yoda-Downloads-Claude-Code
      Unix:    /Users/martin/myproject                -> -Users-martin-myproject
               /Users/martin/.config/proj             -> -Users-martin--config-proj
    """
    system = platform.system()
    if system == 'Windows':
        # Replace : \ / with -.  Spaces also become - (empirically confirmed).
        import re
        return re.sub(r'[:\\/\s]', '-', p)
    else:
        # macOS / Linux: /. (hidden dir separator) -> -- ; / -> -
        return p.replace('/.', '--').replace('/', '-')


def patch_metadata_files(sessions_dir, old_path, new_path):
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
                f.write_text(json.dumps(data, indent=2), encoding='utf-8')
                patched += 1
            else:
                skipped += 1

        except Exception as e:
            errors.append((f.name, str(e)))

    return patched, skipped, errors


def patch_claude_json(home, old_path, new_path):
    """
    Layer 2: update stale project key in ~/.claude.json.
    Keys in that file always use forward slashes on all platforms.

    Returns True if a key was patched, False otherwise.
    """
    home = pathlib.Path(home)
    claude_json = home / '.claude.json'
    if not claude_json.exists():
        return False

    data = json.loads(claude_json.read_text(encoding='utf-8'))
    projects = data.get('projects')
    if not isinstance(projects, dict):
        return False

    # Normalise to forward slashes for key lookup
    old_key = old_path.replace('\\', '/')
    new_key = new_path.replace('\\', '/')

    if old_key not in projects:
        return False

    projects[new_key] = projects.pop(old_key)
    claude_json.write_text(json.dumps(data, indent=2), encoding='utf-8')
    return True


def patch_project_folder(projects_dir, old_path, new_path):
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

def run_migration(old_path, new_path):
    home = pathlib.Path.home()

    print('=== Layer 1: session metadata ===')
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        print(f'  WARNING: sessions dir not found: {sessions_dir}')
        print('  On Linux, try: find ~/.config -name "local_*.json" | head -5')
    else:
        patched, skipped, errors = patch_metadata_files(sessions_dir, old_path, new_path)
        print(f'  Patched: {patched}, Skipped: {skipped}, Errors: {len(errors)}')
        for name, err in errors:
            print(f'  ERROR {name}: {err}')

    print('\n=== Layer 2: ~/.claude.json ===')
    if patch_claude_json(home, old_path, new_path):
        print(f'  PATCHED: {old_path!r} -> {new_path!r}')
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

    renamed, jsonl_count = patch_project_folder(projects_dir, old_path, new_path)
    print(f'  Patched {jsonl_count} .jsonl files')

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
# Entry point — edit these two lines
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    OLD_PATH = '/old/project/path'   # <-- edit this
    NEW_PATH = '/new/project/path'   # <-- edit this
    run_migration(OLD_PATH, NEW_PATH)
