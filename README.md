# living-blueprint

A Claude Code plugin for any tech stack: map an existing architecture, design a feature, component
or cross-cutting concern by interview (optionally from a photo of a sketch), build the approved
design, and keep the document true to the code.

## Table of Contents

- [Install](#install)
- [Commands](#commands)
- [How it works](#how-it-works)
- [Pull requests](#pull-requests)
- [Where docs live](#where-docs-live)
- [Safety](#safety)
- [Limits](#limits)
- [Developing](#developing)

## Install

```sh
claude plugin marketplace add connorhewick/living-blueprint   # or a local path to this checkout
claude plugin install living-blueprint@living-blueprint
```

Needs `git` and Python 3.9 or newer. No other packages.

## Commands

| Command | Does | Started by |
|---|---|---|
| `/living-blueprint:map [scope or folder]` | Creates an architecture doc | you or Claude |
| `/living-blueprint:design [idea, photos]` | Interviews you and writes a design, separate or merged into a doc | you or Claude |
| `/living-blueprint:build <design>` | Implements an approved design on a local branch. Never pushes | you only |
| `/living-blueprint:drift [doc] [full]` | Checks a doc against the code, reports, then updates what you approve | you only |
| `/living-blueprint:location [folder] [--move]` | Shows or changes where docs live | you or Claude |
| `/living-blueprint:pr [number]` | Puts Mermaid copies of the diagrams in a pull request body | you or Claude |

## How it works

A `.json` data file is the only hand-edited source ([format](reference/data-format.md)). A script
generates a self-contained interactive page, and a Markdown copy of a design for line comments in
a pull request. Every proposed, changed or removed item is marked, so a page never presents a plan
as built.

A design has six parts (problem and scope, new flow, data and contract changes, cross-cutting
effects, options, enforcement) plus acceptance criteria. Approval records a digest: editing the
design afterwards voids it, and `build` refuses.

`drift` finds changed and missing cited files and symbols, changed code nothing cites, and
differences in saved measurements and inventories. Claude then reads the code and sorts each
mismatch into: doc stale, possible defect, build differs from design, cannot verify, or still
true. A defect is not written into the doc as the new rule without your decision. The doc's commit
moves only when each flagged item is confirmed or visibly marked `unverified` or `open`.

## Pull requests

When a branch adds or changes a design, or changes diagrams in an architecture doc, the pull
request body carries them as Mermaid so GitHub draws them. This applies to a design on its own and
to a design with its implementation.

- A design contributes all its graphs and swimlanes, with `NEW`, `CHANGES` and `REMOVES` marks.
  An architecture doc contributes only the diagrams that differ from the base branch, folded.
- Graphs become flowcharts and swimlanes become sequence diagrams. They are not laid out like the
  page, and notes and tables stay in the files.
- A hook refuses to open a pull request, or to rewrite its body, unless the body holds the current
  section. It covers `gh pr create`, `gh pr edit` on the current or a named branch, and GitHub
  connector tools that create or update a pull request. **It does not check `gh pr edit <number>`
  or `<url>`**, because it cannot tell which branch that is. It also misses `gh` inside quotes,
  backticks, `gh api` or a script. Connector checks compare the branches of the folder the session
  is in. Connector tool names were not available to test against, so that path is matched
  by name and tested only with made-up calls.
- After a `git push` on such a branch, a hook reminds Claude to run `/living-blueprint:pr`.
  **Nothing checks a pull request made on the website or outside Claude**, and a push made there
  gives no reminder.
- If the hook cannot work out the branches, it allows the command. It writes a "check skipped"
  note to stderr, which you and Claude may never see after an allowed command, so **treat a skip
  as silent**. The same applies to `gh pr edit <number>`.
  A changed doc that cannot be drawn is different: the hook refuses and names the errors.
- A diagram that a branch removes is not shown. An architecture diagram counts as changed even
  when only its cites or evidence changed.
- Text outside the diagrams is defused so a doc cannot mention people, close issues or hide a link
  behind other words.

## Where docs live

An explicit path wins, then `.claude/living-blueprint.json` in the project, then
`docs/architecture/`. Change the project default with `/living-blueprint:location <folder>`
(`--move` takes existing docs along) and commit the config file. Docs are also found by a marker
in the data file, wherever they are. Designs go under `<folder>/designs/<id>/`.

## Safety

Docs and config come with whatever repository you open, so they are treated as untrusted:

- Paths read from a doc or the config must resolve inside the repository and outside `.git`.
- Nothing is written through a symlink. `--fragment` and `--into` may point anywhere you name,
  but not at a link.
- Docs that are symlinks are ignored, and the script's own `git` calls will not run a program
  named by a bare repository hidden in a subfolder.
- Page text is inserted as text, never as markup, and cannot close the script element carrying it.
- **A doc's check commands run in your shell.** The script will not run them without an approval
  code tied to their exact text, and the `drift` skill must show them to you and get a yes first.
  **The code is printed in the same report, so the "show you first" step is an instruction to the
  model, not something the script can enforce.** Keep permission prompts on for Bash, and read the
  commands in a repository you do not trust.
- **Approving a check command means trusting the repository.** A command that starts an
  interpreter or build tool runs the repository's code, whatever its text says. The code covers
  the command text, not the files it loads. Checks run with your environment, including any tokens
  in it; `PYTHONSAFEPATH` stops only one route, on Python 3.11 and newer. Commands with hidden or
  control characters are rejected.
- `build` treats the design as input and stops before anything leaves your machine. That stop is
  also an instruction to the model, not a sandbox.

## Limits

- **Drift can miss things.** A behaviour change in a file nothing cites, or in uncommented meaning
  rather than names, may not be flagged. `drift <doc> full` re-verifies every claim.
- **Confirming drift items** with `pin --confirmed` cannot name an item whose id or bar label
  holds a comma.
- **Cites check that a name exists, not that the claim about it is true.** The fact-check step and
  you cover that.
- **The Mermaid output has not been run through a Mermaid renderer** or viewed on GitHub. Tests
  check its text only, so a diagram could fail to draw.
- **Photo intake is unproven** on real handwriting
  ([issue #1](https://github.com/connorhewick/living-blueprint/issues/1)).
- **Page checks** need Chrome, Chromium or Edge (set `LB_CHROME` if unusual), or macOS with
  `swiftc`. Otherwise the result is "unchecked", never a pass. The Chromium path has not been run
  yet. Headless browsers may not go as narrow as a phone, which is reported as unchecked.
- **Diagrams** are laid out from grid cells you give. Arrows cannot cross boxes. In a stress test
  with 12 boxes and 16 arrows, 5 of 30 diagrams had a label crossed by another arrow; smaller ones
  (up to 7 and 7) had none in 60. Split dense diagrams.

## Developing

```sh
python3 -m unittest discover -s tests
claude plugin validate --strict .
python3 tests/make_eval_fixtures.py    # after changing tests/fixtures/shop
claude plugin eval . --runs 1 --ablation none --scaffold --no-publish \
  --allow-tools Bash Write Edit --max-cost-usd 8
```

`--no-publish` matters: by default the eval report is uploaded to claude.ai. `--scaffold` runs the
cases' setup scripts as you. Try a change without installing with `claude --plugin-dir .`.

The sample under `tests/fixtures/shop` is made up. Do not add content from a private project.

Cases for `map`, `design`, `build` and `drift` are under `evals/`. They are smoke tests: one run
each is not a reliability figure. On macOS the eval sandbox blocked the `git` shim in shell
commands, even with the Xcode `git` directory first on `PATH`, so the runs did not exercise a
working shell `git`. `AskUserQuestion` was not available inside them either.
