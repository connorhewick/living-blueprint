---
name: map
description: Create an architecture document for a codebase of any stack, as a data file and an interactive page. Use for "map this architecture", "document how this system works", "create an architecture doc". Not for checking an existing doc against the code (drift) or designing something new (design).
argument-hint: "[scope or output folder]"
---

# Map an existing architecture

Read these first: `${CLAUDE_PLUGIN_ROOT}/reference/data-format.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/writing-rules.md`.

Request: $ARGUMENTS

Let `lb` mean `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py"`.

1. **Locate.** Run `lb where`. A folder the user named wins over the config and the default; offer
   to save it as the project's default with `lb set-dir`. If a doc for this scope exists, stop and
   suggest `/living-blueprint:drift` instead of overwriting it.
2. **Settle the inputs** with one `AskUserQuestion` call, only for what the code cannot tell you:
   scope (whole repository, one service, one concern), the reader's stack, which user stories, and
   whether to add an Assessment. Put what you found in the options. State what you chose for
   anything left blank.
3. **Check the tree.** Note uncommitted changes: the doc can only be pinned to committed code.
4. **Inspect and measure.** Read the project's docs as claims, then the code. Choose measuring
   tools that suit this stack, preferring ones already installed. Never install anything without
   asking. Keep each command that backs a figure for `checks.measures`, and add inventories of the
   things the doc claims to cover (services, routes, tables, topics, jobs, packages).
5. **Write the data file** with `cites` and `evidence` on claims.
6. **Validate and render**: `lb validate <doc>`, then `lb render <doc>`. Fix every error. Read the
   warning about uncited items: add cites, or accept that drift cannot watch them.
7. **Check the page**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_page.py" <page.html>`.
   Fix failures by changing the data (move grid cells, shorten labels, split a diagram). Exit 2
   means **unchecked**: report it that way, never as a pass.
8. **Fact-check** per `${CLAUDE_PLUGIN_ROOT}/reference/fact-check.md`, apply what you confirm, and
   render and check again.
9. **Pin**: `lb pin <doc>`, then render again. If it refuses because of uncommitted code, say so
   and leave the doc unpinned; do not commit unless asked.
10. **Reply** with what kind of system it is in one or two sentences, one line per section, then
    findings that change how a reader should treat the system, then what was not verified. Publish
    the page only if asked (`lb render <doc> --fragment <file>`).
