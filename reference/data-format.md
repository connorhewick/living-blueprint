# Data format

The `.json` file is the only thing anyone edits. `.html` and `.md` are generated from it.

## Where files go

| Kind | Path |
|---|---|
| Architecture doc | `<docsDir>/<id>.json` |
| Design | `<docsDir>/designs/<id>/design.json` |

`<docsDir>` comes from `blueprint.py where`: an explicit path from the user, else
`.claude/living-blueprint.json` (`{"docsDir": "..."}`), else `docs/architecture`. When the user
names a different place for one run, pass `--docs-dir` or use their path. `set-dir` changes the
project's default. All paths are relative to the repository root and may not leave it.

## Document

```json
{
  "livingBlueprint": 1,
  "id": "billing",
  "kind": "architecture",
  "title": "Billing architecture",
  "summary": "What kind of system this is and its shape, in one or two sentences.",
  "commit": "",
  "sources": ["services/billing"],
  "layers": [{"id": "api", "label": "API"}],
  "sections": [{"id": "overview", "title": "1. Overview", "level": 2, "blocks": []}],
  "checks": {"measures": [], "inventory": []}
}
```

- `commit` is set by `blueprint.py pin`, never by hand.
- `sources` limits what drift treats as this doc's code. In a monorepo, name the folders.
- A layer is any grouping: a tier, service, package or team boundary. `color` (`#rrggbb`) is optional.
- Ids are lowercase slugs, unique across sections and blocks. A section's `level` is 1 to 6.
- Every graph node, lane and step needs a `title`; every table needs `columns`.
- In any text, `` `code` `` and `**bold**` are formatted. Nothing else is.

## Blocks

Every block but `text` needs `caption: {"takeaway": "...", "text": "..."}`. The takeaway is one
sentence, is shown in bold and labels the block in the contents.

| `type` | Holds | Notes |
|---|---|---|
| `graph` | `nodes: [{id, title, lines, layer, col, row}]`, `edges: [{from, to, label, id?}]` | Layers, ER, topology, internal maps. |
| `swimlane` | `lanes: [{id, title, layer}]`, `steps: [{id, lane, title, note, effect, from?}]`, `story?` | `from` lists earlier step ids; the default is the previous step. A `story` label puts it in the matrix. |
| `table` | `columns: []`, `rows: [{id, cells: []}]` | Rules, contracts, states, translations. |
| `list` | `items: [{id, text}]` | Gaps, acceptance criteria. |
| `bars` | `unit`, `bars: [{label, value, detail?, layer}]` | Measured figures only. |
| `code` | `code` | Verbatim from the source. |
| `text` | `text` | Use sparingly: sections open with a diagram or table. |
| `matrix` | nothing | Built from every swimlane that has a `story`. |

### Graph layout

You place nodes on a grid with `col` (0 to 4) and `row`; arrows are routed for you and cannot
cross a box. Put things that talk to each other in neighbouring cells. Lay allowed dependencies
top to bottom. Labels can still crowd in a dense graph: past about ten nodes or twelve edges,
split it. Keep a swimlane to seven lanes or fewer.

## Fields on any block or item

| Field | Values | Meaning |
|---|---|---|
| `cites` | `["path", "path#Symbol"]` | What this claim rests on. Drift watches these, and validation fails if a built claim cites a path or symbol that does not exist. Cite the narrowest file: a folder cite is coarse, and any change under it flags the whole block. A block's cites cover the block, not each item. |
| `evidence` | `run`, `read`, `search`, `unverified` | How you know. `run`: you executed it. `read`: you read the code path. `search`: a text search only. |
| `status` | `built` (default), `proposed`, `changed`, `removed` | Anything not built needs `design`. |
| `design` | design id | Which design proposes this. |
| `open` | reason | A known mismatch the user has chosen to leave unresolved. It stays visible. |

The enforcer of a rule is a cite too: `"cites": ["tests/test_orders.py#test_single_writer"]`.
A rule nothing enforces says **review only** in its cell.

## Checks that drift reruns

```json
"checks": {
  "measures":  [{"id": "routes", "label": "HTTP routes", "command": "git grep -c '@app\\.' -- api", "value": "12"}],
  "inventory": [{"id": "tables", "label": "Tables", "command": "...one name per line...", "items": ["orders"]}]
}
```

- A measure backs a figure in the doc. `value` is the command's exact output.
- An inventory lists everything of one kind that the doc claims to cover: services, routes,
  tables, topics, jobs, packages. It is how drift notices **new** things nothing cites. Give every
  architecture doc at least one.
- Commands must only read. No network, no writes, no installs, no secrets in the command or its
  output.
- A command is one line of visible characters. Line breaks, tabs and invisible characters are
  rejected.

## Designs

`kind: "design"` adds `state` (set by the script) and `openQuestions: []`, and needs these
section ids:

| id | Content |
|---|---|
| `problem` | The problem, and what is out of scope. |
| `flow` | A swimlane of the new flow with `proposed` or `changed` steps. A cross-cutting concern shows one representative flow it touches. |
| `data` | Every data, API, event or config contract change: what stores it, delete or retention behaviour, and the migration or deployment step. A table, or text saying none and why. |
| `effects` | A row per cross-cutting concern **of this repository**. |
| `options` | A table of options with why, and which is picked. |
| `enforcement` | A table: rule, what holds it (test, lint rule, hook, type system, CI, review only), where. |
| `acceptance` | A list of criteria someone can check. |

- A diagram in a design includes, as built context nodes, every node an edge touches.
- To change an existing block when integrated, give the design block the **same block id** and
  items the same ids, marked `changed` or `removed` (a removed item needs only its id and what the
  block type requires). Add `after: "<id>"` to place a proposed item.
- To remove a whole existing block, give the design block the same id and `type` and mark the
  **block** `removed`. A `text`, `code` or `matrix` block is changed the same way, marked
  `changed`. A block with items is changed through its items; leave the block itself unmarked.
- A new block goes into the architecture section named by its `into`, else into a
  "Proposed: <title>" section.
- Only things marked other than `built` travel on integrate. Problem, options and acceptance stay
  in the design.

## Commands

`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/blueprint.py" [--repo DIR] <command>`

| Command | Does |
|---|---|
| `where [--docs-dir D]` | The docs directory, where that came from, and every doc found. |
| `set-dir D [--move]` | Change the project's docs directory. |
| `validate DOC [--no-cites]` | Errors and warnings. |
| `render DOC [--markdown] [--fragment F]` | Write the page; `--fragment` for publishing. |
| `pr-body [--base B] [--into FILE]` | Mermaid copies of the diagrams a pull request changes. |
| `gaps DESIGN` | What blocks approval. |
| `approve DESIGN` | Mark approved. Only after the user says so. |
| `ready DESIGN` | Fails unless approved and unchanged since. |
| `integrate ARCH DESIGN` | Put the design into the doc, marked as not built. |
| `resolve DOC SLUG --built\|--drop` | Fold a design in, or take it out. |
| `drift DOC [--run-commands CODE]` | Report only. |
| `pin DOC [--confirmed a,b]` | Move the doc to HEAD. Refuses while flagged items are not dealt with. |
