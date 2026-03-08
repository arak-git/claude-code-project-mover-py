# claude-code-project-mover-py

**Cross-platform Python tool for moving a Claude Code project to a new folder.**

Fixes the *"Folder no longer exists. Please start a new session."* error that appears for all old sessions after you move or rename your Claude Code working directory.

Works on **Windows, macOS, and Linux**. TDD-verified: 23/23 tests pass.

---

## The Problem

When you move a Claude Code working directory, the app shows:

> Folder no longer exists. Please start a new session.

for every old session. The error persists even after restarting Claude Code.

## Why Naive Fixes Don't Work

Claude Code stores session data in **three separate locations**. Most tools and guides only patch one or two of them. The error comes from the third.

| Layer | Path | What it does |
|-------|------|--------------|
| **1 — UI metadata** ← *root cause* | `%APPDATA%\Claude\claude-code-sessions\...\local_*.json` (Win) `~/Library/Application Support/Claude/...` (macOS) `~/.config/Claude/...` (Linux) | Small JSON files the UI reads to render the session list. Contains `cwd` — the path that's checked for existence. |
| **2 — Project config** | `~/.claude.json` | Per-project settings keyed by path. Stale keys cause config errors. |
| **3 — Session transcripts** | `~/.claude/projects/<encoded>/` | Full conversation history (`.jsonl` files). Also needs patching for session resumption. |

**This tool patches all three layers.**

---

## Comparison with the Bash Alternative

The shell script at [skydiver/claude-code-project-mover](https://github.com/skydiver/claude-code-project-mover) was the inspiration for this tool. It handles Layer 3 (folder rename + `.jsonl` patching) on macOS, but:

| Gap | Impact |
|-----|--------|
| ❌ Never touches Layer 1 (`local_*.json`) | **"Folder no longer exists" error persists** after running it |
| ❌ Never touches Layer 2 (`~/.claude.json`) | Project config failures |
| ❌ `sed -i ''` is BSD sed (macOS only) | **Fails on Linux** with GNU sed |
| ❌ Shallow `for file in $folder/*` glob | Misses `<uuid>/subagents/*.jsonl` |
| ❌ Bash only | Doesn't run natively on Windows |

---

## Usage

```bash
# 1. Move your project folder first (Claude Code doesn't detect moves automatically)
mv /old/path /new/path

# 2. Edit OLD_PATH and NEW_PATH at the bottom of the script
#    Then run:
python move_claude_project.py
```

**Windows example** — edit the bottom of `move_claude_project.py`:
```python
OLD_PATH = r'C:\Users\You\Downloads\My Project'
NEW_PATH = r'C:\Users\You\Documents\My Project'
```

**macOS/Linux example:**
```python
OLD_PATH = '/Users/you/old-location'
NEW_PATH = '/Users/you/new-location'
```

Then restart Claude Code. The sessions should load normally.

---

## What It Does

```
=== Layer 1: session metadata ===
  PATCHED: local_0af09ce6-....json
  PATCHED: local_1067d0f2-....json
  ...
  Patched: 15, Skipped: 2, Errors: 0

=== Layer 2: ~/.claude.json ===
  PATCHED: 'C:/Users/You/Old' -> 'C:/Users/You/New'

=== Layer 3: ~/.claude/projects ===
  Renaming: C--Users-You-Old -> C--Users-You-New
  Patched 409 .jsonl files

=== Verification ===
  All session cwd paths exist.
  RESTART Claude Code to apply changes.
```

---

## Requirements

- Python 3.8+
- No third-party dependencies (stdlib only)

---

## Running the Tests

```bash
python test_move_claude_project.py -v
```

```
test_T01_basic_windows_path ... ok
test_T02_space_in_path_becomes_dash ... ok
...
Ran 23 tests in 0.142s
OK
```

The test suite covers all three layers, both platforms, edge cases including:
- Spaces in Windows paths (`Claude Code` → `Claude-Code`)
- Hidden directories on Unix (`/.config` → `--config`)
- Prefix collision protection (exact `cwd` match, not substring)
- Windows JSON double-backslash encoding
- Recursive `subagents/` patching
- Null `planPath` handling
- Verification of all `cwd` paths post-migration

---

## Bugs Fixed vs Simple Implementation

Three non-obvious bugs exist in the naive implementation. All confirmed by `prove_bugs.py`:

**B1 — Windows path encoding misses spaces**
```python
# Wrong: preserves space
p.replace(':', '-').replace('\\', '-')  # 'Claude Code' stays 'Claude Code'

# Fixed: all non-word chars become '-'
re.sub(r'[^\w]', '-', p)               # 'Claude Code' -> 'Claude-Code'
```
Effect: folder rename silently fails for any path with a space.

**B2 — Unix hidden directory encoding**
```python
# Wrong: '/.config' -> '-.config' (wrong folder name)
p.replace('/', '-')

# Fixed: '/.config' -> '--config'
p.replace('/.', '--').replace('/', '-')
```

**B3 — Substring match causes prefix collision**
```python
# Wrong: patches '/proj-backup' when OLD='/proj'
if old_path in cwd_value:

# Fixed: exact match only
if cwd_value == old_path:
```

---

## Multiple Path Changes

If you also need to update other paths (e.g. a backup drive rename), extend the migration:

```python
if __name__ == '__main__':
    substitutions = [
        (r'C:\Users\You\Downloads\My Project', r'C:\Users\You\Documents\My Project'),
        (r'F:\Backup\Old Name',                r'F:\Backup\New Name'),
    ]
    for old, new in substitutions:
        run_migration(old, new)
```

---

## Notes

- **Linux sessions path** follows XDG spec. Verify with:
  `find ~/.config -name 'local_*.json' 2>/dev/null | head -5`
- **Both old and new project folders exist**: this happens when you start using Claude Code from the new path before running this tool. The script detects this and warns — compare `.jsonl` record counts per UUID and keep the larger file.
- **Restart required**: Layer 1 metadata is read at startup. A full app restart is needed after patching.

---

## Files

| File | Purpose |
|------|---------|
| `move_claude_project.py` | Main script (also importable as a module) |
| `test_move_claude_project.py` | 23-test TDD suite |
| `prove_bugs.py` | Demonstrates the 3 bugs in naive implementations |

---

## Related

- [skydiver/claude-code-project-mover](https://github.com/skydiver/claude-code-project-mover) — the original bash script (macOS, Layer 3 only)
