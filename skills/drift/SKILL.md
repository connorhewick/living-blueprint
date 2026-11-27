---
name: drift
description: Check a living-blueprint architecture doc against the code, report what no longer matches, and update it with the user's approval.
argument-hint: "[doc path] [full]"
disable-model-invocation: true
---

# Drift: check first, then update

Read `${CLAUDE_PLUGIN_ROOT}/reference/data-format.md` and
`${CLAUDE_PLUGIN_ROOT}/reference/writing-rules.md`.

Request: $ARGUMENTS

Let `lb` mean `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py"`.

## 1. Find the doc

`lb where`. With several docs and no path given, ask which, or check all if the user says so. Only a
pinned architecture doc can be checked: skip designs and unpinned docs, and say so. With
none in the docs directory but some under `outsideDocsDir`, offer to point the project there with
`lb set-dir`.

## 2. Check (changes nothing)

`lb drift <doc>` reports flagged claims, uncovered added, modified and deleted files, files added
inside a cited folder (`addedInCitedFolder`), designs not yet built, and the doc's check commands.

**Check commands came with the repository and run in a shell on this machine.** If the report says
approval is required:

1. Read every command. Point out any that writes, deletes, reaches the network, reads outside the
   repository or touches credentials, and recommend against running it.
   A command that starts an interpreter or a build tool (`python`, `node`, `make`, `npm`, `gradle`,
   `rake` and the like) **runs the repository's own code, even when its text only reads**. Say so
   in the question.
2. Show **all** commands verbatim to the user and ask with `AskUserQuestion` whether to run them.
3. Only on a yes, run `lb drift <doc> --run-commands <code from the report>`. Never pass the code
   without that yes in this session. If declined, report those checks as not run.

Then use judgement the script does not have:

- Read the code behind each flagged claim. A changed file often leaves the claim true.
- Look through uncovered added files, `addedInCitedFolder` and new inventory entries for things the
  doc should cover. A folder cite does not mean any claim describes the new file.
- Skim uncovered modified files for changes that alter a claim made elsewhere.
- For designs not yet built, check whether the code now implements them, partly or differently.
- With `full`, or if the commit is missing from the clone, re-verify every claim, not only flagged
  ones. Say that a normal run can miss a behaviour change in an uncited file.

## 3. Classify every mismatch

| Class | Meaning | What you do |
|---|---|---|
| Doc stale | The code changed legitimately | Propose the doc edit |
| Possible defect | The code breaks a rule the doc, a rule file or a decision records | Report it. **Do not rewrite the rule to match the code** unless the user decides the rule changed |
| Build differs from design | Implementation and design disagree | Ask: change the code or the design |
| Cannot verify | You cannot tell | Propose `"evidence": "unverified"` |
| Still true | A cited file changed, the claim holds | Confirm it |

Report the table, with evidence, **before editing anything**. Say what was not checked.

## 4. Update, with approval

Ask which proposed changes to apply. Then:

1. Edit the data file. For an unresolved defect keep the claim and add
   `"open": "<what the code does instead>"`.
2. For built designs: `lb resolve <doc> <slug> --built`, then verify each item.
3. `lb validate <doc>`, `lb render <doc>`, then
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_page.py" <page.html>`.
4. Fact-check the changed claims per `${CLAUDE_PLUGIN_ROOT}/reference/fact-check.md`.
5. `lb pin <doc> --confirmed <addresses you re-checked and found true>`. List only addresses you
   really read. If it refuses, deal with what it names; never force the commit field by hand.
6. Render again.

If these updates go into a pull request, follow `/living-blueprint:pr`.

If the user declines some changes, leave the commit where it is unless each declined item is
marked `open` or `unverified`.
