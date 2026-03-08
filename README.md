# claude-code-project-mover-py

Fixes the "Folder no longer exists" error after you move or rename a Claude Code project folder. Cross-platform (Windows, macOS, Linux), Python 3.8+, stdlib only.

## The problem

Move or rename your Claude Code working directory and every old session says:

> Folder no longer exists. Please start a new session.

Restarting doesn't fix it. The error persists because Claude Code stores paths in three separate places, and all three need updating.

| Layer | Where | What |
|-------|-------|------|
| 1 - Session metadata | `%APPDATA%\Claude\claude-code-sessions\` (Win), `~/Library/Application Support/Claude/` (macOS), `~/.config/Claude/` (Linux) | `local_*.json` files with `cwd` field. This is the actual source of the error. |
| 2 - Project config | `~/.claude.json` | Project keys and MCP server env vars with absolute paths. |
| 3 - Transcripts | `~/.claude/projects/<encoded>/` | `.jsonl` conversation history. |

Most other tools only patch Layer 3. The error comes from Layer 1. This tool patches all three.

## Usage

```bash
# Move your folder first, then run:
python move_claude_project.py /old/path /new/path

# Preview what would change (no files touched):
python move_claude_project.py /old/path /new/path --dry-run
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

=== Layer 3: ~/.claude/projects ===
  Renaming: C--Users-You-Old -> C--Users-You-New
  Patched 409 .jsonl files

=== Verification ===
  All session cwd paths exist.
  RESTART Claude Code to apply changes.
```

With `--dry-run`, you get the same report but nothing is written to disk.

## What it handles

The basic case is obvious: old path becomes new path, done. Where it gets interesting is the stuff you wouldn't think to check until it breaks:

- Claude Code encodes folder names by replacing all non-alphanumeric characters with dashes, so `Claude Code` becomes `Claude-Code`. Spaces trip up naive implementations.
- On Unix, `/.config` encodes to `--config` (double dash), not `-.config`. Easy to get wrong.
- `~/.claude.json` has keys for sub-projects too (`proj/submodule`), not just the root. An exact-match rename misses them.
- MCP server env vars embed absolute paths (`KB_ROOT=/old/path/data`). These need patching even in project entries you didn't move.
- Claude Code sometimes creates both `C:/path` and `C:\path` keys for the same project. When both rename to the same target, the second one would overwrite the first and you'd lose your MCP server config. The script detects this and merges instead.
- A project at `/proj` shouldn't cause `/proj-backup` to get patched. Exact matching on `cwd`, substring matching on `planPath`.
- Windows `.jsonl` files store paths with escaped backslashes (`\\\\` on disk). Handled transparently.

## Tests

```bash
python test_move_claude_project.py -v
# Ran 33 tests in 0.3s - OK
```

The test suite covers all three layers on both platforms, including every edge case listed above plus dry-run verification.

## Notes

- On Linux, session paths follow the XDG spec. Check with: `find ~/.config -name 'local_*.json' 2>/dev/null | head -5`
- If both old and new project folders already exist under `~/.claude/projects/`, the script warns you. Compare `.jsonl` file sizes per UUID and keep the larger one.
- You must restart Claude Code after running. Layer 1 metadata is read at startup.

## Related

Inspired by [skydiver/claude-code-project-mover](https://github.com/skydiver/claude-code-project-mover) (bash, macOS, Layer 3 only).
