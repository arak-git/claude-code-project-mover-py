# claude-code-project-mover-py

Fixes the "Folder no longer exists" error after you move or rename a Claude Code project folder. Cross-platform (Windows, macOS, Linux), Python 3.8+, stdlib only.

## The problem

Move or rename your Claude Code working directory and every old session says:

> Folder no longer exists. Please start a new session.

Restarting doesn't fix it. The error persists because Claude Code stores paths in six separate places, and all six need updating.

| Layer | Where | What |
|-------|-------|------|
| 1 - Session metadata | `%APPDATA%\Claude\claude-code-sessions\` (Win), `~/Library/Application Support/Claude/` (macOS), `~/.config/Claude/` (Linux) | `local_*.json` files with `cwd` field. This is the actual source of the error. |
| 2 - Project config | `~/.claude.json` | Project keys and MCP server env vars with absolute paths. |
| 2.5 - MCP config | `.mcp.json` in project tree | MCP server command, args, and env values with absolute paths. |
| 3 - Transcripts | `~/.claude/projects/<encoded>/` | `.jsonl` conversation history. |
| 4 - Permissions | `.claude/settings.local.json` | Permission allow-list entries embedding absolute paths. |
| 5 - Memory & plans | `~/.claude/projects/<encoded>/memory/`, `~/.claude/plans/` | MEMORY.md, memory files, and plan files with absolute paths. |

Most other tools only patch Layer 3. The error comes from Layer 1. This tool patches all six.

## Usage

```bash
# Move your folder first, then run:
python move_claude_project.py /old/path /new/path

# Preview what would change (no files touched):
python move_claude_project.py /old/path /new/path --dry-run

# After migration, prune permission entries pointing to dead paths:
python move_claude_project.py /old/path /new/path --prune-stale
```

Windows paths need quotes:
```bash
python move_claude_project.py "C:\Users\You\Old Location" "C:\Users\You\New Location"
```

Restart Claude Code after running. Old sessions should load normally.

For multiple moves, run the script once per path:
```bash
python move_claude_project.py /first/old /first/new
python move_claude_project.py /second/old /second/new
```

## Output

```
=== Layer 1: session metadata ===
  Patched: 15, Skipped: 2, Errors: 0

=== Layer 2: ~/.claude.json ===
  Keys renamed: 3, MCP env vars patched: 2

=== Layer 2.5: .mcp.json in project tree ===
  Files patched: 1, Fields patched: 3, Errors: 0

=== Layer 3: ~/.claude/projects ===
  Renaming: C--Users-You-Old -> C--Users-You-New
  Patched 409 .jsonl files

=== Layer 4: .claude/settings.local.json ===
  Patched 12 of 47 permission entries

=== Layer 5: MEMORY.md + plan files ===
  Patched 3 of 8 files

=== Verification ===
  All session cwd paths exist.
  RESTART Claude Code to apply changes.
```

With `--dry-run`, you get the same report but nothing is written to disk.

## Stale permission pruning

The `--prune-stale` flag adds an optional Phase B after migration: it scans permission entries in `.claude/settings.local.json`, extracts embedded filesystem paths, and identifies entries where every path is dead on disk. Pattern-only entries (like `Bash(python:*)`) are never touched.

Pruning uses a two-confirmation gate:
1. First prompt shows the count of stale entries and asks to proceed.
2. Second prompt lists every entry to be removed and asks for final confirmation.

A timestamped backup file (`.claude/settings_pruned_YYYY-MM-DD_HHMMSS.json`) is written before any removal. It includes restore instructions and the full list of pruned entries.

## What it handles

The basic case is obvious: old path becomes new path, done. Where it gets interesting is the stuff you wouldn't think to check until it breaks:

- Claude Code encodes folder names by replacing all non-alphanumeric characters with dashes, so `Claude Code` becomes `Claude-Code`. Spaces trip up naive implementations.
- On Unix, `/.config` encodes to `--config` (double dash), not `-.config`. Easy to get wrong.
- `~/.claude.json` has keys for sub-projects too (`proj/submodule`), not just the root. An exact-match rename misses them.
- MCP server env vars embed absolute paths (`KB_ROOT=/old/path/data`). These need patching even in project entries you didn't move.
- `.mcp.json` files in your project tree also embed absolute paths in command, args, and env fields. Both canonical (`{"mcpServers": {...}}`) and flat formats are handled.
- Claude Code sometimes creates both `C:/path` and `C:\path` keys for the same project. When both rename to the same target, the second one would overwrite the first and you'd lose your MCP server config. The script detects this and merges instead.
- Permission entries use three path formats: quoted paths (`"C:\\Users\\..."`), Read paths (`Read(//c/Users/...)`), and JSON-escaped backslashes. All three are handled for both substitution and stale detection.
- A project at `/proj` shouldn't cause `/proj-backup` to get patched. Exact matching on `cwd`, substring matching on `planPath`.
- Windows `.jsonl` files store paths with escaped backslashes (`\\\\` on disk). Handled transparently.
- MEMORY.md files and plan files reference absolute paths that go stale after a move. Layer 5 patches these so Claude's persistent context stays accurate.

## Tests

```bash
python -m pytest test_move_claude_project.py -v
# 76 tests — all pass
```

The test suite covers all six layers on both platforms, including every edge case listed above, dry-run verification, path encoding, collision merging, stale permission pruning, and backup file structure.

## Notes

- On Linux, session paths follow the XDG spec. Check with: `find ~/.config -name 'local_*.json' 2>/dev/null | head -5`
- If both old and new project folders already exist under `~/.claude/projects/`, the script warns you. Compare `.jsonl` file sizes per UUID and keep the larger one.
- You must restart Claude Code after running. Layer 1 metadata is read at startup.

## Related

Inspired by [skydiver/claude-code-project-mover](https://github.com/skydiver/claude-code-project-mover) (bash, macOS, Layer 3 only).
