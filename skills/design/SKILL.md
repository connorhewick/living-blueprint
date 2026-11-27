---
name: design
description: Design a new feature, component or cross-cutting concern by interviewing the user, optionally starting from a photo of a whiteboard or paper sketch, and produce a design document that can stand alone or be merged into an architecture doc. Use for "design a feature", "plan a new component", "turn this sketch into a design". Writes documents only, never application code.
argument-hint: "[idea, sketch photo paths, or existing design id]"
---

# Design by interview

Read `${CLAUDE_PLUGIN_ROOT}/reference/data-format.md` first, and the "Where claims go wrong" part
of `${CLAUDE_PLUGIN_ROOT}/reference/writing-rules.md`.

Request: $ARGUMENTS

Let `lb` mean `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py"`.

**This skill writes design documents only. Do not edit application code, tests or config.**

## 1. Ground yourself before asking anything

- `lb where`. Read the architecture doc that covers this area, if there is one. If its commit is
  old, say that it may be stale.
- Read the code the idea touches. Find this repository's own cross-cutting concerns (for example
  authentication, authorisation, tenancy, transactions, migrations, caching, queues, undo, sync,
  backup, privacy, logging, flags, localisation, accessibility, deployment). Only list ones you
  found evidence for.
- Photos given: follow `${CLAUDE_PLUGIN_ROOT}/reference/photo-intake.md` first.

## 2. Interview

Use `AskUserQuestion`, a few questions at a time, most consequential first.

- **Ground each question in evidence**: name the files, show counts, put real choices in the
  options with your recommendation first. Do not ask what the code answers.
- Each question stands alone; the user may see only the dialog.
- Offer failure modes and concerns the user did not name.
- If an answer is "I don't know", the question was badly cut: split it and recommend.
- Cover, in this order: problem and who has it; what is out of scope; the new flow including
  failure paths; data and contract changes with their migration or deploy step; the effect on each
  concern you found; real options with the trade-off; the rules the design adds and what will
  enforce each; acceptance criteria someone can check.
- Never fill an unanswered point with an assumption silently. Put it in `openQuestions`.
- Stop when the next answer would not change the design.

## 3. Write the design

Write `<docsDir>/designs/<slug>/design.json` with the seven required sections. Cite real code for
context; mark everything new `proposed`, everything altered `changed`. Prefer a rule a tool can
enforce to one left to review. Then `lb validate`, `lb render <design> --markdown`, and
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_page.py" <page.html>`
on the page (exit 2 means unchecked). `lb gaps <design>` shows what still blocks
approval; resolve it with the user.

The `.md` copy is for line comments in a pull request. When the user brings comments back, change
the data file and render again.

## 4. Separate or integrated

Ask which the user wants:

- **Separate**: the design stays on its own.
- **Integrated**: `lb integrate <architecture doc> <design>`, then render and check that doc. Its
  proposed parts stay visibly marked. The design file remains the record of why.

Either can happen now or later. To take an integrated design out, `lb resolve <doc> <slug> --drop`
(also use `resolve <design> <slug> --drop` to mark an abandoned design).

## 5. Approval

Show the pick, the acceptance criteria and the enforcement table, and ask the user to approve.
Only on an explicit yes run `lb approve <design>`, then `lb render <design> --markdown` so the
copies show the new state. Any later edit voids the approval. Tell the
user that `/living-blueprint:build <design>` starts implementation.

## A pull request for the design

When the user asks for a pull request (the design alone, or with code), follow
`/living-blueprint:pr` so the diagrams show on GitHub. This skill does not open one unasked.

## Decisions that outlive the design

If the design settles a lasting rule, propose recording it where this repository keeps rules that
tools or agents load (lint config, rule files, contributor guide). Do not create a new
convention for it.
