---
name: location
description: Show or change where living-blueprint keeps this project's architecture docs and designs, optionally moving existing ones. Use for "change where architecture docs go", "put the docs in a different folder".
argument-hint: "[new folder] [--move]"
---

# Docs location

Request: $ARGUMENTS

Let `lb` mean `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py"`.

- No folder given: run `lb where` and report the folder, whether it came from an argument, the
  config or the default, and any docs outside it.
- Folder given: if docs already exist elsewhere and `--move` was not said, ask whether to move
  them. Then `lb set-dir <folder>` (add `--move` to move). It writes
  `.claude/living-blueprint.json`, which should be committed so the whole team shares it.
- After a move, search the repository for links to the old paths and offer to update them.

The folder is relative to the repository root and may not leave it. In a monorepo that needs docs
beside each service, name the folder per run instead of changing the default.
