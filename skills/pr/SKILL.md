---
name: pr
description: Put Mermaid copies of living-blueprint diagrams into a pull request description so they display on GitHub. Use whenever opening or updating a pull request on a branch that added or changed a living-blueprint design or architecture doc, whether it holds the design only or the implementation too.
argument-hint: "[pull request number]"
---

# Diagrams in the pull request

Request: $ARGUMENTS

Let `lb` mean `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py"`.

This skill does not decide to open or push anything. Open or edit a pull request only when the
user asked for that.

1. The diagrams come from **committed** files. If a design or doc has uncommitted changes, say so;
   commit only if asked.
2. Write the body to a temporary file, following the repository's pull request conventions. For an
   open pull request, start from its current body:
   `gh pr view <n> --json body -q .body > <file>`.
3. `lb pr-body --base <base branch> --into <file>`. Add `--head <pull request branch>` when that
   branch is not the one checked out. It adds the section between markers, or replaces the old one,
   and leaves the rest alone. `diagrams: false` means the branch changes no living-blueprint
   diagram, so add nothing.
4. Do not edit inside the markers; change the data file and generate again.
5. `gh pr create --base <base> --body-file <file>` or `gh pr edit <n> --body-file <file>`, in a
   separate command from the ones that wrote the file. **Never put the section directly in
   `--body` or in an unquoted heredoc:** the shell runs parts of it. A hook refuses `gh pr create`,
   and `gh pr edit` that sets a body, without the current section. For a number or address it asks
   `gh pr view` which branches the pull request compares. If it cannot tell, for example on a pull
   request from a fork or a branch this clone does not have, it allows the command, so there this
   step is yours to get right. If `pr-body` says a changed doc cannot be drawn, fix that doc and
   commit it first.
6. **After pushing commits that change a diagram, run this again.** Pushing does not update a
   body. A hook reminds you after a `git push` made through Claude, and for no other push.

Without a request to open a pull request, print the section (`lb pr-body --base <base>`) so the
user can paste it.
