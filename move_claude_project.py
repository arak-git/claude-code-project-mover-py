#!/usr/bin/env python3
"""
Claude Code Project Mover — cross-platform (Windows, macOS, Linux)

Usage:
  python move_claude_project.py OLD_PATH NEW_PATH [--dry-run]

Importable module: functions can be imported by test_move_claude_project.py
"""
import sys, os, json, pathlib, platform, re

__version__ = '2.3.0'

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


def _replace_path_variants(value, old_fwd, new_fwd, old_back, new_back):
    """Replace old_path in a string value, handling both forward-slash and backslash variants.

    Returns the updated string (unchanged if no match).
    """
    result = value
    if old_fwd in result:
        result = result.replace(old_fwd, new_fwd)
    if old_back in result:
        result = result.replace(old_back, new_back)
    return result


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
                    new_val = _replace_path_variants(
                        env_val, old_fwd, new_fwd, old_back, new_back)
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


def patch_mcp_json_files(project_root, old_path, new_path, dry_run=False):
    """
    Layer 2.5: patch .mcp.json files in the (already-moved) project tree.

    Finds all .mcp.json files under project_root via rglob.  For each file,
    patches absolute paths in MCP server config fields: command, args, env values.

    Handles two format variants:
      - Canonical: {"mcpServers": {"name": {command, args, env}}}
      - Flat:      {"name": {command, args, env}}  (no mcpServers wrapper)

    Returns (files_patched, fields_patched, errors: list[(filename, msg)]).
    """
    project_root = pathlib.Path(project_root)
    old_fwd = old_path.replace('\\', '/')
    new_fwd = new_path.replace('\\', '/')
    old_back = old_path.replace('/', '\\')
    new_back = new_path.replace('/', '\\')

    files_patched = 0
    fields_patched = 0
    errors = []

    for mcp_file in sorted(project_root.rglob('.mcp.json')):
        try:
            text = mcp_file.read_text(encoding='utf-8')
            data = json.loads(text)
        except json.JSONDecodeError as e:
            errors.append((str(mcp_file), f'Malformed JSON: {e}'))
            continue
        except Exception as e:
            errors.append((str(mcp_file), str(e)))
            continue

        if not isinstance(data, dict) or not data:
            continue

        # Detect format: canonical (has "mcpServers" key) vs flat
        if 'mcpServers' in data and isinstance(data['mcpServers'], dict):
            servers = data['mcpServers']
        else:
            # Flat format: each top-level key whose value is a dict is a server
            servers = {k: v for k, v in data.items() if isinstance(v, dict)}

        file_fields = 0
        for srv_cfg in servers.values():
            if not isinstance(srv_cfg, dict):
                continue

            # Patch "command" (string)
            cmd = srv_cfg.get('command')
            if isinstance(cmd, str):
                new_cmd = _replace_path_variants(
                    cmd, old_fwd, new_fwd, old_back, new_back)
                if new_cmd != cmd:
                    srv_cfg['command'] = new_cmd
                    file_fields += 1

            # Patch "args" (list of strings)
            args = srv_cfg.get('args')
            if isinstance(args, list):
                for i, arg in enumerate(args):
                    if isinstance(arg, str):
                        new_arg = _replace_path_variants(
                            arg, old_fwd, new_fwd, old_back, new_back)
                        if new_arg != arg:
                            args[i] = new_arg
                            file_fields += 1

            # Patch "env" (dict of string values)
            env = srv_cfg.get('env')
            if isinstance(env, dict):
                for env_key, env_val in list(env.items()):
                    if isinstance(env_val, str):
                        new_val = _replace_path_variants(
                            env_val, old_fwd, new_fwd, old_back, new_back)
                        if new_val != env_val:
                            env[env_key] = new_val
                            file_fields += 1

        if file_fields > 0:
            if not dry_run:
                mcp_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False),
                    encoding='utf-8')
            files_patched += 1
            fields_patched += file_fields

    return files_patched, fields_patched, errors


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


def patch_settings_local(project_root, old_path, new_path, dry_run=False):
    """
    Layer 4: patch .claude/settings.local.json in the project tree.

    Permission allow-list entries embed absolute paths (e.g., Bash commands
    referencing the project directory).  After a move, these become stale
    cruft — they won't match anything and new permissions accumulate, but
    patching them keeps the file clean.

    Patches old_path occurrences inside string values in permissions.allow[].
    Handles both forward-slash and backslash variants, plus JSON-escaped
    backslashes (\\\\) which appear in Bash permission strings on Windows.

    Returns (patched_count: int, total_entries: int).
    """
    project_root = pathlib.Path(project_root)
    settings_file = project_root / '.claude' / 'settings.local.json'
    if not settings_file.exists():
        return 0, 0

    try:
        data = json.loads(settings_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, Exception):
        return 0, 0

    allow = data.get('permissions', {}).get('allow')
    if not isinstance(allow, list):
        return 0, 0

    old_fwd = old_path.replace('\\', '/')
    new_fwd = new_path.replace('\\', '/')
    old_back = old_path.replace('/', '\\')
    new_back = new_path.replace('/', '\\')
    # JSON-escaped backslash variant (\\Users\\... on disk)
    old_esc = old_path.replace('\\', '\\\\').replace('/', '\\\\')
    new_esc = new_path.replace('\\', '\\\\').replace('/', '\\\\')

    patched = 0
    for i, entry in enumerate(allow):
        if not isinstance(entry, str):
            continue
        new_entry = entry
        if old_fwd in new_entry:
            new_entry = new_entry.replace(old_fwd, new_fwd)
        if old_back in new_entry:
            new_entry = new_entry.replace(old_back, new_back)
        if old_esc in new_entry:
            new_entry = new_entry.replace(old_esc, new_esc)
        if new_entry != entry:
            allow[i] = new_entry
            patched += 1

    if patched > 0 and not dry_run:
        settings_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    return patched, len(allow)


def patch_memory_md(projects_dir, old_path, new_path, dry_run=False):
    """
    Layer 5: patch MEMORY.md and memory/*.md files under
    ~/.claude/projects/<encoded>/memory/.

    These files are read by future sessions for project context.  Stale
    paths cause Claude to look in wrong locations.

    Also patches plan files under ~/.claude/plans/ that reference old_path.

    Returns (files_patched: int, total_scanned: int).
    """
    projects_dir = pathlib.Path(projects_dir)
    new_encoded = encode_path(new_path)
    memory_dir = projects_dir / new_encoded / 'memory'

    old_fwd = old_path.replace('\\', '/')
    new_fwd = new_path.replace('\\', '/')
    old_back = old_path.replace('/', '\\')
    new_back = new_path.replace('/', '\\')

    files_patched = 0
    total_scanned = 0

    # Patch memory files
    if memory_dir.exists():
        for f in sorted(memory_dir.rglob('*.md')):
            total_scanned += 1
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
                new_text = text
                if old_fwd in new_text:
                    new_text = new_text.replace(old_fwd, new_fwd)
                if old_back in new_text:
                    new_text = new_text.replace(old_back, new_back)
                if new_text != text:
                    if not dry_run:
                        f.write_text(new_text, encoding='utf-8')
                    files_patched += 1
            except Exception:
                pass

    # Patch plan files that reference old_path
    plans_dir = projects_dir.parent / 'plans'
    if plans_dir.exists():
        for f in sorted(plans_dir.glob('*.md')):
            total_scanned += 1
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
                new_text = text
                if old_fwd in new_text:
                    new_text = new_text.replace(old_fwd, new_fwd)
                if old_back in new_text:
                    new_text = new_text.replace(old_back, new_back)
                if new_text != text:
                    if not dry_run:
                        f.write_text(new_text, encoding='utf-8')
                    files_patched += 1
            except Exception:
                pass

    return files_patched, total_scanned


def extract_paths_from_permission(entry):
    """
    Extract filesystem paths from a permission allow-list entry.

    Recognizes these patterns:
      - Quoted paths:  Bash(find "C:\\Users\\...\\data")
      - Read paths:    Read(//c/Users/...) or Read(C:/Users/...)
      - Parenthesized paths containing / or \\

    Returns a list of candidate path strings (may be empty for
    pattern-only entries like 'Bash(python:*)' or 'WebFetch(domain:...)').
    """
    paths = []

    # 1. Quoted strings containing path separators
    #    Matches both "C:\\Users\\..." and "/Users/..." inside quotes
    for m in re.finditer(r'"([^"]*[/\\][^"]*)"', entry):
        candidate = m.group(1)
        # Unescape JSON-escaped backslashes for disk check
        paths.append(candidate.replace('\\\\', '\\'))

    # 2. Read(//path) or Read(/path) — no quotes
    m = re.match(r'Read\((/[^)]+)\)', entry)
    if m:
        candidate = m.group(1)
        # //c/Users/... → C:/Users/... for Windows disk check
        # Format: //X/... where X is a single drive letter
        if candidate.startswith('//') and len(candidate) > 3 and candidate[3] == '/':
            candidate = candidate[2].upper() + ':' + candidate[3:]
        paths.append(candidate)

    # 3. Bash entries with unquoted absolute paths after known commands
    #    e.g., Bash(CLAIM_REVIEW_ROOT="/path/..." ...) — already caught by #1
    #    e.g., Bash(test -d "/path") — already caught by #1

    return paths


def prune_stale_permissions(project_root, dry_run=False, confirmed=False):
    """
    Layer 4 Phase B: remove permission entries whose embedded paths
    no longer exist on disk.

    Pattern-only entries (no extractable path) are never pruned.
    Entries with paths that DO exist are never pruned.
    Only entries with extractable paths confirmed dead are candidates.

    Args:
        project_root: path to the project directory
        dry_run: if True, report but don't modify
        confirmed: if True, skip interactive prompts (for tests).
                   In CLI flow, run_migration handles the two-confirmation gate.

    Returns:
        (pruned_count: int, backup_path: str or None, stale_entries: list[str])
        stale_entries is the list of entries identified as stale (returned even
        if not confirmed, so caller can display them for the confirmation gate).
    """
    from datetime import datetime

    project_root = pathlib.Path(project_root)
    settings_file = project_root / '.claude' / 'settings.local.json'
    if not settings_file.exists():
        return 0, None, []

    try:
        data = json.loads(settings_file.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, Exception):
        return 0, None, []

    allow = data.get('permissions', {}).get('allow')
    if not isinstance(allow, list):
        return 0, None, []

    # Identify stale entries
    stale_entries = []
    stale_indices = []
    for i, entry in enumerate(allow):
        if not isinstance(entry, str):
            continue
        paths = extract_paths_from_permission(entry)
        if not paths:
            # Pattern-only entry (no extractable path) — skip
            continue
        # Entry is stale if ALL extracted paths are dead
        all_dead = all(not pathlib.Path(p).exists() for p in paths)
        if all_dead:
            stale_entries.append(entry)
            stale_indices.append(i)

    if not stale_entries:
        return 0, None, []

    if not confirmed:
        # Return stale list for caller to display in confirmation gate
        return 0, None, stale_entries

    if dry_run:
        return len(stale_entries), None, stale_entries

    # Write backup file before modifying
    now = datetime.now()
    backup_name = f'settings_pruned_{now.strftime("%Y-%m-%d_%H%M%S")}.json'
    backup_path = project_root / '.claude' / backup_name
    backup_data = {
        "pruned_at": now.isoformat(timespec='seconds'),
        "source_file": ".claude/settings.local.json",
        "reason": "Stale path pruning — extracted paths do not exist on disk",
        "restore_instructions": (
            "To restore: copy entries from the 'pruned_entries' array back into "
            ".claude/settings.local.json → permissions.allow"
        ),
        "entry_count": len(stale_entries),
        "pruned_entries": stale_entries,
    }
    backup_path.write_text(
        json.dumps(backup_data, indent=2, ensure_ascii=False), encoding='utf-8')

    # Remove stale entries (reverse order to preserve indices)
    for i in reversed(stale_indices):
        allow.pop(i)

    settings_file.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

    return len(stale_entries), str(backup_path), stale_entries


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

def run_migration(old_path, new_path, dry_run=False, prune_stale=False):
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

    print('\n=== Layer 2.5: .mcp.json in project tree ===')
    new_root = pathlib.Path(new_path)
    if new_root.exists():
        files_p, fields_p, mcp_errs = patch_mcp_json_files(
            new_root, old_path, new_path, dry_run=dry_run)
        if files_p > 0 or mcp_errs:
            print(f'  Files patched: {files_p}, Fields patched: {fields_p}, Errors: {len(mcp_errs)}')
            for epath, emsg in mcp_errs:
                print(f'  ERROR {epath}: {emsg}')
        else:
            print('  No .mcp.json files found (or none contained old paths)')
    else:
        print(f'  WARNING: new project root not found: {new_root}')

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

    print('\n=== Layer 4: .claude/settings.local.json ===')
    new_root = pathlib.Path(new_path)
    if new_root.exists():
        settings_patched, settings_total = patch_settings_local(
            new_root, old_path, new_path, dry_run=dry_run)
        if settings_patched > 0:
            print(f'  Patched {settings_patched} of {settings_total} permission entries')
        else:
            print(f'  No stale paths in permissions ({settings_total} entries scanned)')
    else:
        print(f'  WARNING: project root not found: {new_root}')

    print('\n=== Layer 5: MEMORY.md + plan files ===')
    mem_patched, mem_total = patch_memory_md(
        projects_dir, old_path, new_path, dry_run=dry_run)
    if mem_patched > 0:
        print(f'  Patched {mem_patched} of {mem_total} files')
    else:
        print(f'  No stale paths ({mem_total} files scanned)')

    # Phase B: prune stale permissions (opt-in)
    if prune_stale:
        print('\n=== Layer 4B: prune stale permissions ===')
        new_root = pathlib.Path(new_path)
        if new_root.exists():
            # First pass: identify stale entries (confirmed=False)
            _, _, stale = prune_stale_permissions(new_root, dry_run=dry_run)
            if not stale:
                print('  No stale permission entries found.')
            else:
                print(f'\n  WARNING: Found {len(stale)} permission entries with dead paths.')
                print('  These entries reference filesystem paths that no longer exist.')
                print('  Pruning is REVERSIBLE — a backup file will be created.\n')
                resp1 = input(f'  Show all {len(stale)} stale entries and proceed? (y/N): ').strip().lower()
                if resp1 != 'y':
                    print('  Pruning aborted.')
                else:
                    print()
                    for i, entry in enumerate(stale, 1):
                        # Truncate long entries for display
                        display = entry if len(entry) <= 120 else entry[:117] + '...'
                        print(f'  [{i:3d}] {display}')
                    print()
                    resp2 = input(
                        f'  Confirm REMOVAL of these {len(stale)} entries from '
                        f'settings.local.json? (y/N): '
                    ).strip().lower()
                    if resp2 != 'y':
                        print('  Pruning aborted.')
                    else:
                        pruned, backup, _ = prune_stale_permissions(
                            new_root, dry_run=dry_run, confirmed=True)
                        if dry_run:
                            print(f'  [DRY RUN] Would prune {pruned} entries.')
                        else:
                            print(f'  Pruned {pruned} entries.')
                            print(f'  Backup saved: {backup}')
                            print(f'  To restore: copy entries from backup → permissions.allow')
        else:
            print(f'  WARNING: project root not found: {new_root}')

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
    parser.add_argument('--prune-stale', action='store_true',
                        help='After migration, interactively prune permission entries '
                             'whose embedded paths no longer exist on disk')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {__version__}')
    args = parser.parse_args()
    run_migration(args.old_path, args.new_path,
                  dry_run=args.dry_run, prune_stale=args.prune_stale)
