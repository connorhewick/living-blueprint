#!/usr/bin/env python3
"""living-blueprint: the deterministic half of the plugin. Standard library only.

Every judgement (what a doc should say) belongs to the skills. This file holds what must not
depend on judgement: where docs live, whether a doc is well formed, whether the names it cites
exist, what changed since its commit, and how a proposed design enters and leaves a doc.

Docs and config arrive with whatever repository is checked out, so both are untrusted input.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path, PurePosixPath

SCHEMA = 1
MARKER = "livingBlueprint"
CONFIG = ".claude/living-blueprint.json"
DEFAULT_DOCS_DIR = "docs/architecture"
PAGE_DIR = Path(__file__).resolve().parent / "page"

STATUSES = ("built", "proposed", "changed", "removed")
EVIDENCE = ("run", "read", "search", "unverified")
STATES = ("draft", "approved", "building", "built", "dropped")
DESIGN_SECTIONS = ("problem", "flow", "data", "effects", "options", "enforcement", "acceptance")
# block type -> the list inside it that holds addressable items
ITEM_LISTS = {
    "graph": ("nodes", "edges"),
    "swimlane": ("steps",),
    "table": ("rows",),
    "list": ("items",),
    "bars": ("bars",),
    "code": (),
    "text": (),
    "matrix": (),
}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class BlueprintError(Exception):
    pass


class InvalidDocs(BlueprintError):
    """A pull request changes a doc that cannot be drawn. Leaving it out would hide it."""


# A repository can ship a bare repository in a subfolder whose config names a program to run
GIT = ("git", "-c", "core.fsmonitor=false", "-c", "safe.bareRepository=explicit")
# control, format (bidi, zero width), surrogate, and the two Unicode line separators
HIDDEN = ("Cc", "Cf", "Cs", "Zl", "Zp")


def has_hidden(value: str) -> bool:
    return any(unicodedata.category(c) in HIDDEN for c in value)


def clean(value) -> str:
    """One line of visible text. Everything that leaves a doc for Markdown or Mermaid passes here."""
    return "".join(" " if unicodedata.category(c) in HIDDEN else c for c in str(value))


# ---------------------------------------------------------------- paths and location


def repo_root(start: Path) -> Path:
    out = subprocess.run(
        [*GIT, "-C", str(start), "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    return Path(out.stdout.strip()).resolve() if out.returncode == 0 else start.resolve()


def inside(root: Path, relative: str, what: str) -> Path:
    """Resolve a repo-relative path, refusing anything that could leave the repository."""
    if not isinstance(relative, str) or not relative.strip():
        raise BlueprintError(f"{what}: empty path")
    candidate = Path(relative)
    if candidate.is_absolute() or relative.startswith("~"):
        raise BlueprintError(f"{what}: '{relative}' must be relative to the repository root")
    if ".." in candidate.parts or ".git" in [part.casefold() for part in candidate.parts]:
        raise BlueprintError(f"{what}: '{relative}' may not contain '..' or '.git'")
    resolved = (root / candidate).resolve()
    # resolve() follows symlinks, so a link pointing outside the repository fails here
    if resolved != root and root not in resolved.parents:
        raise BlueprintError(f"{what}: '{relative}' resolves outside the repository")
    # checked again after resolving: a link can lead there, and a filesystem may ignore case
    if ".git" in [part.casefold() for part in resolved.relative_to(root).parts]:
        raise BlueprintError(f"{what}: '{relative}' leads into '.git'")
    return resolved


def refuse_links(path: Path, below: Path | None = None) -> None:
    """Never write through a symlink: a repository can ship one wherever this tool writes. With
    `below`, every folder from there down is checked as well as the file itself."""
    chain = [path]
    if below is not None:
        parts = path.relative_to(below).parts
        chain = [below.joinpath(*parts[: n + 1]) for n in range(len(parts))]
    for step in chain:
        if step.is_symlink():
            raise BlueprintError(f"{step}: is a symlink; refusing to write through it")


def encoded(path: Path, text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BlueprintError(
            f"{path}: cannot be saved as UTF-8 ({error.reason} at character {error.start}); nothing was written"
        ) from None


def safe_write(path: Path, text: str, below: Path | None = None) -> None:
    refuse_links(path, below)
    if path.exists() and not path.is_file():
        raise BlueprintError(f"{path}: is not a regular file")
    data = encoded(path, text)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    else:
        mask = os.umask(0)
        os.umask(mask)
        mode = 0o666 & ~mask
    # A new file, then a rename: a write that fails never leaves the old file cut short, and a link
    # that appears at `path` after the check is replaced, not written through. mkstemp opens with
    # O_EXCL, so nothing planted at the temporary name is followed.
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def docs_dir(root: Path, override: str | None = None) -> tuple[str, str]:
    """(repo-relative directory, where it came from). Argument beats config beats default."""
    if override:
        inside(root, override, "--docs-dir")
        return Path(override).as_posix(), "argument"
    config = root / CONFIG
    if config.exists():
        value = load_json(config).get("docsDir")
        if value is not None:
            inside(root, value, CONFIG)
            return Path(value).as_posix(), "config"
    return DEFAULT_DOCS_DIR, "default"


def git_files(root: Path, *args: str) -> list[str]:
    # -z goes straight after the subcommand: after a "--" git would read it as a path and match nothing
    out = subprocess.run([*GIT, "-C", str(root), args[0], "-z", *args[1:]], capture_output=True, text=True)
    if out.returncode != 0:
        raise BlueprintError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return [p for p in out.stdout.split("\0") if p]


def find_docs(root: Path) -> list[str]:
    """Every data file in the repository that carries the schema marker, wherever it lives."""
    found = []
    try:
        names = git_files(root, "ls-files", "--cached", "--others", "--exclude-standard")
    except (BlueprintError, OSError):
        # Not a git project, or no usable git: locating docs must still work. Drift still needs git.
        names = []
        for folder, folders, files in os.walk(root):
            folders[:] = [f for f in folders if not f.startswith(".") and f not in ("node_modules", "vendor", "target", "build", "dist", "venv")]
            names += [(Path(folder) / f).relative_to(root).as_posix() for f in files]
    for name in names:
        if not name.endswith(".json"):
            continue
        path = root / name
        try:
            info = path.lstat()
            # not a link: one can point at a device that never stops giving
            if not stat.S_ISREG(info.st_mode) or info.st_size > 5_000_000:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError):
            continue
        if isinstance(data, dict) and data.get(MARKER) == SCHEMA:
            found.append(name)
    return sorted(found)


def set_docs_dir(root: Path, new: str, move: bool) -> list[str]:
    """Point the project at a new docs directory, optionally moving the docs already there."""
    target = inside(root, new, "docs directory")
    refuse_links(root / new, below=root)
    refuse_links(root / CONFIG, below=root)
    old_rel, _ = docs_dir(root)
    old = inside(root, old_rel, "current docs directory")
    moved: list[str] = []
    if move and old.is_dir() and old != target:
        if old == root or old in target.parents or target in old.parents:
            raise BlueprintError("cannot move docs into or out of their own parent directory")
        # Only files this tool owns move: a data file and the pages generated beside it.
        owned: list[Path] = []
        for name in find_docs(root):
            data_file = root / name
            if old in data_file.resolve().parents:
                beside = (data_file, data_file.with_suffix(".html"), data_file.with_suffix(".md"))
                owned += [p for p in beside if p.is_file() and not p.is_symlink()]
        plan = [(p, target / p.resolve().relative_to(old)) for p in owned]
        for _, destination in plan:
            refuse_links(destination.parent, below=root)
        clashes = [str(d.relative_to(root)) for _, d in plan if os.path.lexists(d)]
        if clashes:
            raise BlueprintError("refusing to overwrite: " + ", ".join(clashes))
        for source, destination in plan:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            moved.append(str(destination.relative_to(root)))
    config = root / CONFIG
    data = load_json(config) if config.exists() else {}
    data["docsDir"] = Path(new).as_posix()
    write_json(config, data, below=root)
    return moved


# ---------------------------------------------------------------- reading and writing


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BlueprintError(f"{path}: not found") from None
    except (ValueError, RecursionError) as error:
        raise BlueprintError(f"{path}: not valid JSON ({error})") from None
    if not isinstance(data, dict):
        raise BlueprintError(f"{path}: expected a JSON object")
    return data


def write_json(path: Path, data: dict, below: Path | None = None) -> None:
    safe_write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n", below)


def blocks(doc: dict):
    for section in doc.get("sections", []):
        for block in section.get("blocks", []):
            yield section, block


def item_key(block: dict, list_name: str, item: dict) -> str:
    if list_name == "edges":
        return item.get("id") or f"{item.get('from')}>{item.get('to')}"
    if list_name == "bars":
        return item.get("id") or item.get("label", "")
    return item.get("id", "")


def items(doc: dict):
    """(address, block, list name, item) for every addressable item."""
    for _, block in blocks(doc):
        for list_name in ITEM_LISTS.get(block.get("type"), ()):
            for item in block.get(list_name, []):
                yield f"{block.get('id')}/{item_key(block, list_name, item)}", block, list_name, item


def status_of(thing: dict) -> str:
    return thing.get("status", "built")


# ---------------------------------------------------------------- validation


def split_cite(cite: str) -> tuple[str, str | None]:
    path, _, symbol = cite.partition("#")
    return path, symbol or None


def cite_problem(root: Path, cite: str) -> str | None:
    path, symbol = split_cite(cite)
    target = inside(root, path, f"cite '{cite}'")
    if not target.exists():
        return "path is missing"
    if symbol:
        if not target.is_file():
            return "a symbol needs a file, not a directory"
        text = target.read_text(encoding="utf-8", errors="replace")
        if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text):
            return "symbol is missing"
    return None


def shape_errors(doc: dict) -> list[str]:
    """Types and fields the renderers rely on. A wrong type elsewhere surfaces as 'malformed'."""
    errors = []
    if not isinstance(doc.get("title", ""), str):
        errors.append("title must be text")
    for section in doc.get("sections", []):
        level = section.get("level", 2)
        if not (isinstance(level, int) and 1 <= level <= 6):
            errors.append(f"section {section.get('id')}: level must be 1 to 6")
    for _, block in blocks(doc):
        where, kind = block.get("id", "?"), block.get("type")
        block.get("caption", {}).get("takeaway")  # a caption that is not an object raises here
        if not isinstance(block.get("code", ""), str):
            errors.append(f"{where}: code must be text")
        if kind == "table" and not isinstance(block.get("columns"), list):
            errors.append(f"{where}: a table needs a list of columns")
        if kind == "table" and any(not row.get("cells") for row in block.get("rows", [])):
            errors.append(f"{where}: every row needs cells")
        for name in {"graph": ("nodes",), "swimlane": ("lanes",)}.get(kind, ()):
            if any(not isinstance(e.get("title"), str) or not e.get("id") for e in block.get(name, [])):
                errors.append(f"{where}: every entry in {name} needs an id and a title")
        if kind == "swimlane" and any(not isinstance(s.get("title"), str) for s in block.get("steps", [])):
            errors.append(f"{where}: every step needs a title")
        if kind == "bars" and any(not isinstance(b.get("label"), str) for b in block.get("bars", [])):
            errors.append(f"{where}: every bar needs a label")
    return errors


def validate(doc: dict, root: Path | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings). With a root, also checks that what built items cite exists."""
    try:
        if doc.get(MARKER) == SCHEMA:
            shape = shape_errors(doc)
            if shape:
                return shape, []
        return _validate(doc, root)
    except (AttributeError, TypeError, KeyError, ValueError, RecursionError) as error:
        return [f"malformed document: {type(error).__name__}: {error}"], []


def _validate(doc: dict, root: Path | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if doc.get(MARKER) != SCHEMA:
        return [f"missing marker: \"{MARKER}\": {SCHEMA}"], []
    if doc.get("kind") not in ("architecture", "design"):
        errors.append("kind must be 'architecture' or 'design'")
    if not SLUG.match(str(doc.get("id", ""))):
        errors.append("id must be a lowercase slug")
    if not doc.get("title"):
        errors.append("title is required")
    if doc.get("commit") and not COMMIT.match(str(doc["commit"])):
        errors.append("commit must be 7-40 lowercase hex characters")
    layers = {layer.get("id") for layer in doc.get("layers", [])}
    for layer in doc.get("layers", []):
        if "color" in layer and not COLOR.match(str(layer["color"])):
            errors.append(f"layer {layer.get('id')}: color must be #rrggbb")

    seen_ids: set[str] = set()
    for section in doc.get("sections", []):
        for thing, label in [(section, "section")] + [(b, "block") for b in section.get("blocks", [])]:
            ident = thing.get("id", "")
            if not SLUG.match(str(ident)):
                errors.append(f"{label} id '{ident}' must be a lowercase slug")
            elif ident in seen_ids:
                errors.append(f"id '{ident}' is used twice")
            seen_ids.add(ident)

    def check_meta(where: str, thing: dict) -> None:
        if status_of(thing) not in STATUSES:
            errors.append(f"{where}: status must be one of {', '.join(STATUSES)}")
        if status_of(thing) != "built" and not thing.get("design"):
            errors.append(f"{where}: a {status_of(thing)} item needs 'design': <slug>")
        if "evidence" in thing and thing["evidence"] not in EVIDENCE:
            errors.append(f"{where}: evidence must be one of {', '.join(EVIDENCE)}")
        cites = thing.get("cites", [])
        if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
            errors.append(f"{where}: cites must be a list of strings")

    for _, block in blocks(doc):
        kind = block.get("type")
        where = block.get("id", "?")
        if kind not in ITEM_LISTS:
            errors.append(f"{where}: unknown block type '{kind}'")
            continue
        check_meta(where, block)
        caption = block.get("caption", {})
        if kind not in ("text",) and not caption.get("takeaway"):
            errors.append(f"{where}: caption.takeaway is required")
        keys: set[str] = set()
        for list_name in ITEM_LISTS[kind]:
            for item in block.get(list_name, []):
                key = item_key(block, list_name, item)
                if not key or key == "None>None":
                    errors.append(f"{where}: every entry in {list_name} needs an id")
                if (list_name, key) in keys:
                    errors.append(f"{where}: {list_name} '{key}' is used twice")
                keys.add((list_name, key))
                check_meta(f"{where}/{key}", item)
        if kind == "graph":
            node_ids = {n.get("id") for n in block.get("nodes", [])}
            cells: set[tuple] = set()
            for node in block.get("nodes", []):
                cell = (node.get("col"), node.get("row"))
                if not all(isinstance(v, int) and v >= 0 for v in cell):
                    errors.append(f"{where}/{node.get('id')}: col and row must be whole numbers from 0")
                elif cell in cells:
                    errors.append(f"{where}/{node.get('id')}: shares a grid cell with another node")
                elif cell[0] > 4:
                    errors.append(f"{where}/{node.get('id')}: col is at most 4; split the diagram")
                cells.add(cell)
                if node.get("layer") not in layers:
                    errors.append(f"{where}/{node.get('id')}: unknown layer '{node.get('layer')}'")
            for edge in block.get("edges", []):
                for end in ("from", "to"):
                    if edge.get(end) not in node_ids:
                        errors.append(f"{where}: edge {end} '{edge.get(end)}' is not a node")
        if kind == "swimlane":
            lanes = {lane.get("id") for lane in block.get("lanes", [])}
            for lane in block.get("lanes", []):
                if lane.get("layer") not in layers:
                    errors.append(f"{where}: lane '{lane.get('id')}' has unknown layer '{lane.get('layer')}'")
            if len(lanes) > 7:
                errors.append(f"{where}: at most 7 lanes; split the flow")
            earlier: set[str] = set()
            for step in block.get("steps", []):
                if step.get("lane") not in lanes:
                    errors.append(f"{where}/{step.get('id')}: unknown lane '{step.get('lane')}'")
                for source in step.get("from", []):
                    if source not in earlier:
                        errors.append(f"{where}/{step.get('id')}: 'from' must name an earlier step")
                earlier.add(step.get("id"))
        if kind == "table":
            width = len(block.get("columns", []))
            for row in block.get("rows", []):
                if len(row.get("cells", [])) != width:
                    errors.append(f"{where}/{row.get('id')}: expected {width} cells")
        if kind == "bars":
            for bar in block.get("bars", []):
                if not isinstance(bar.get("value"), (int, float)):
                    errors.append(f"{where}: bar '{bar.get('label')}' needs a numeric value")

    for group in ("measures", "inventory"):
        ids: set[str] = set()
        for entry in doc.get("checks", {}).get(group, []):
            if not entry.get("id") or not isinstance(entry.get("command"), str):
                errors.append(f"checks.{group}: each entry needs an id and a command")
            elif has_hidden(entry["command"]) or has_hidden(str(entry["id"])):
                # what a person reads before approving must be what runs
                errors.append(f"checks.{group}: '{clean(entry['id'])}' has hidden or control characters; keep it to one visible line")
            if entry.get("id") in ids:
                errors.append(f"checks.{group}: id '{entry.get('id')}' is used twice")
            ids.add(entry.get("id"))

    if doc.get("kind") == "design":
        present = {s.get("id") for s in doc.get("sections", [])}
        for required in DESIGN_SECTIONS:
            if required not in present:
                errors.append(f"design is missing the '{required}' section")
        if doc.get("state", "draft") not in STATES:
            errors.append(f"state must be one of {', '.join(STATES)}")

    if root is not None:
        uncited = 0
        for address, block, _, item in items(doc):
            if status_of(item) != "built" or status_of(block) != "built":
                continue
            if not item.get("cites") and not block.get("cites"):
                uncited += 1
        if uncited:
            warnings.append(f"{uncited} built items cite nothing, so drift cannot watch them")
        for address, thing in [(b.get("id"), b) for _, b in blocks(doc)] + [(a, i) for a, _, _, i in items(doc)]:
            if status_of(thing) in ("proposed",) or thing.get("evidence") == "unverified":
                continue
            for cite in thing.get("cites", []):
                try:
                    problem = cite_problem(root, cite)
                except BlueprintError as error:
                    errors.append(str(error))
                    continue
                if problem:
                    errors.append(f"{address}: cite '{cite}': {problem}")
    return errors, warnings


def design_gaps(doc: dict) -> list[str]:
    """What stops a well-formed design from being approved."""
    gaps = []
    sections = {s.get("id"): s for s in doc.get("sections", [])}

    def has(section: str, kind: str) -> list[dict]:
        return [b for b in sections.get(section, {}).get("blocks", []) if b.get("type") == kind]

    if not any(status_of(s) != "built" or status_of(b) != "built" for b in has("flow", "swimlane") for s in b.get("steps", [])):
        gaps.append("flow: needs a swimlane that marks what changes from today")
    for section in DESIGN_SECTIONS:
        if not sections.get(section, {}).get("blocks"):
            gaps.append(f"{section}: is empty (state 'none' and why, if nothing applies)")
    if not any(b.get("rows") for b in has("options", "table")):
        gaps.append("options: needs a table of options, with the pick and why")
    if not any(b.get("rows") for b in has("enforcement", "table")):
        gaps.append("enforcement: needs a table of rules and what enforces each")
    if not any(b.get("items") for b in has("acceptance", "list")):
        gaps.append("acceptance: needs a list of criteria that can be checked")
    for question in doc.get("openQuestions", []):
        gaps.append(f"open question: {question}")
    return gaps


def digest(doc: dict) -> str:
    content = {k: v for k, v in doc.items() if k not in ("state", "approvedDigest")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:16]


def approve(doc: dict) -> None:
    if doc.get("kind") != "design":
        raise BlueprintError("only a design can be approved")
    problems = validate(doc)[0] + design_gaps(doc)
    if problems:
        raise BlueprintError("not ready for approval:\n  " + "\n  ".join(problems))
    doc["state"] = "approved"
    doc["approvedDigest"] = digest(doc)


def ready_to_build(doc: dict) -> None:
    if doc.get("kind") != "design":
        raise BlueprintError("build needs a design document")
    if doc.get("state") not in ("approved", "building"):
        raise BlueprintError(f"design is '{doc.get('state', 'draft')}', not approved")
    if doc.get("approvedDigest") != digest(doc):
        raise BlueprintError("design changed after it was approved; get it approved again")


# ---------------------------------------------------------------- designs in and out of a doc


def replace_block(sections: dict, block: dict, target: dict, slug: str) -> None:
    """A design that marks a whole existing block: remove it, or change one that has no items."""
    where, status = block["id"], status_of(block)
    if block.get("type") != target.get("type"):
        raise BlueprintError(f"block '{where}' is a {target.get('type')} in the architecture doc")
    if status_of(target) != "built":
        raise BlueprintError(f"{where}: already changed by design '{target.get('design')}'")
    if status == "proposed":
        raise BlueprintError(f"{where}: marked proposed but already exists; use 'changed'")
    if status == "changed" and ITEM_LISTS[target["type"]]:
        raise BlueprintError(f"{where}: this block has items, so mark the items that change and leave the block unmarked")
    original = copy.deepcopy(target)
    if status == "changed":
        incoming = copy.deepcopy(block)
        incoming.pop("into", None)
        target.update(incoming)
    target.update(status=status, design=slug, was=original)


def integrate(architecture: dict, design: dict) -> dict:
    """Return the architecture doc with the design's changes in it, marked as not built."""
    if architecture.get("kind") != "architecture" or design.get("kind") != "design":
        raise BlueprintError("integrate takes an architecture doc and a design doc")
    result = copy.deepcopy(architecture)
    slug = design["id"]
    if any(i.get("design") == slug for _, _, _, i in items(result)) or any(b.get("design") == slug for _, b in blocks(result)):
        raise BlueprintError(f"'{slug}' is already integrated; resolve it with --drop first")

    layer_ids = {layer["id"] for layer in result.get("layers", [])}
    for layer in design.get("layers", []):
        if layer["id"] not in layer_ids:
            result.setdefault("layers", []).append({**layer, "design": slug})

    existing = {b["id"]: b for _, b in blocks(result)}
    sections = {s["id"]: s for s in result.get("sections", [])}
    changed_something = False
    for _, block in blocks(design):
        lists = ITEM_LISTS.get(block.get("type"), ())
        changes = [(n, i) for n in lists for i in block.get(n, []) if status_of(i) != "built"]
        if not changes and status_of(block) == "built":
            continue  # context, or a design-only part such as the problem statement
        changed_something = True
        target = existing.get(block["id"])
        if target is not None and status_of(block) != "built":
            replace_block(sections, block, target, slug)
            continue
        if target is None:
            added = copy.deepcopy(block)
            added.update(status="proposed", design=slug)
            into = added.pop("into", None)
            if into is None or into not in sections:
                into = f"proposed-{slug}"[:64]
                if into not in sections:
                    section = {"id": into, "title": f"Proposed: {design['title']}", "level": 2, "design": slug, "blocks": []}
                    result.setdefault("sections", []).append(section)
                    sections[into] = section
            sections[into]["blocks"].append(added)
            continue
        if target.get("type") != block.get("type"):
            raise BlueprintError(f"block '{block['id']}' is a {target.get('type')} in the architecture doc")
        for list_name, item in changes:
            key = item_key(block, list_name, item)
            entries = target.setdefault(list_name, [])
            index = next((n for n, e in enumerate(entries) if item_key(target, list_name, e) == key), None)
            incoming = {**copy.deepcopy(item), "design": slug}
            after = incoming.pop("after", None)
            if index is not None and status_of(entries[index]) != "built":
                raise BlueprintError(f"{block['id']}/{key}: already changed by design '{entries[index].get('design')}'")
            if status_of(item) == "proposed":
                if index is not None:
                    raise BlueprintError(f"{block['id']}/{key}: marked proposed but already exists; use 'changed'")
                position = next((n + 1 for n, e in enumerate(entries) if item_key(target, list_name, e) == after), len(entries))
                entries.insert(position, incoming)
                continue
            if index is None:
                raise BlueprintError(f"{block['id']}/{key}: marked {status_of(item)} but is not in the architecture doc")
            original = entries[index]
            merged = {**original, **incoming} if status_of(item) == "changed" else {**original, "status": "removed", "design": slug}
            merged["was"] = original
            entries[index] = merged
    if not changed_something:
        raise BlueprintError("the design marks nothing as proposed, changed or removed")
    errors = validate(result)[0]
    if errors:
        raise BlueprintError("integration would break the doc:\n  " + "\n  ".join(errors))
    return result


def resolve(doc: dict, slug: str, outcome: str) -> dict:
    """Fold a design in ('built') or take it out again ('drop')."""
    result = copy.deepcopy(doc)
    touched = 0
    sections = []
    for section in result.get("sections", []):
        kept_blocks = []
        for block in section.get("blocks", []):
            whole_block = block.get("design") == slug
            if whole_block and outcome == "drop":
                touched += 1
                if "was" in block:
                    kept_blocks.append(block["was"])
                continue
            if whole_block and outcome == "built" and status_of(block) == "removed":
                touched += 1
                continue
            for list_name in ITEM_LISTS.get(block.get("type"), ()):
                kept = []
                for item in block.get(list_name, []):
                    if item.get("design") != slug:
                        kept.append(item)
                        continue
                    touched += 1
                    if outcome == "drop":
                        if "was" in item:
                            kept.append(item["was"])
                        continue
                    if status_of(item) == "removed":
                        continue
                    for field in ("status", "was", "design"):
                        item.pop(field, None)
                    # What was planned is not yet what was verified.
                    item["evidence"] = "unverified"
                    kept.append(item)
                if list_name in block:
                    block[list_name] = kept
            if whole_block:
                touched += 1
                for field in ("status", "was", "design"):
                    block.pop(field, None)
                block["evidence"] = "unverified"
            kept_blocks.append(block)
        section["blocks"] = kept_blocks
        if section.get("design") == slug:
            if outcome == "drop" and not kept_blocks:
                continue
            section.pop("design", None)
            if outcome == "built" and str(section.get("title", "")).startswith("Proposed: "):
                section["title"] = section["title"][len("Proposed: "):]
        sections.append(section)
    result["sections"] = sections
    layers = []
    for layer in result.get("layers", []):
        if layer.get("design") == slug:
            if outcome == "drop":
                continue
            layer.pop("design")
        layers.append(layer)
    if "layers" in result:
        result["layers"] = layers
    if not touched:
        raise BlueprintError(f"nothing in this doc belongs to design '{slug}'")
    return result


# ---------------------------------------------------------------- drift


def changed_since(root: Path, commit: str) -> dict[str, str]:
    """path -> A, M or D, from the commit to the working tree, untracked files included."""
    if not COMMIT.match(commit or ""):
        raise BlueprintError("the doc has no valid commit")
    probe = subprocess.run([*GIT, "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
    if probe.returncode != 0:
        raise BlueprintError(f"commit {commit} is not in this clone (shallow clone or rewritten history); re-verify the whole doc")
    fields = git_files(root, "diff", "--name-status", "--no-renames", commit, "--")
    changes = {path: status[0] for status, path in zip(fields[0::2], fields[1::2])}
    for path in git_files(root, "ls-files", "--others", "--exclude-standard"):
        changes[path] = "A"
    return changes


def commands(doc: dict) -> list[tuple[str, str, str]]:
    return [(g, e["id"], e["command"]) for g in ("measures", "inventory") for e in doc.get("checks", {}).get(g, [])]


def command_digest(doc: dict) -> str:
    return hashlib.sha256(json.dumps(commands(doc)).encode()).hexdigest()


def run_checks(root: Path, doc: dict) -> list[dict]:
    # stops `python -c` from importing a module the repository planted (Python 3.11 and newer)
    environment = {**os.environ, "PYTHONSAFEPATH": "1"}
    results = []
    for group in ("measures", "inventory"):
        for entry in doc.get("checks", {}).get(group, []):
            try:
                out = subprocess.run(entry["command"], shell=True, cwd=root, env=environment, capture_output=True, text=True, timeout=60)
                text, code = out.stdout.strip(), out.returncode
            except subprocess.TimeoutExpired:
                text, code = "", "timeout"
            result = {"group": group, "id": entry["id"], "exit": code}
            if code != 0:
                # A failed command is no answer, never "nothing there".
                result["state"] = "failed"
            elif group == "measures":
                result.update(recorded=str(entry.get("value", "")), now=text)
                result["state"] = "same" if text == str(entry.get("value", "")).strip() else "differs"
            else:
                now = sorted({line.strip() for line in text.splitlines() if line.strip()})
                recorded = set(entry.get("items", []))
                result.update(added=sorted(set(now) - recorded), gone=sorted(recorded - set(now)))
                result["state"] = "differs" if result["added"] or result["gone"] else "same"
            results.append(result)
    return results


def covered(path: str, cited: set[str]) -> bool:
    return any(path == c or path.startswith(c.rstrip("/") + "/") for c in cited)


def owned_files(root: Path, doc_rel: str) -> set[str]:
    """What this tool writes: each data file, the pages beside it, and the config. Everything else
    is watched, wherever the docs live: code next to a doc is still code."""
    owned = {CONFIG}
    for name in {*find_docs(root), doc_rel}:
        path = PurePosixPath(name)
        owned |= {name, path.with_suffix(".html").as_posix(), path.with_suffix(".md").as_posix()}
    return owned


def drift(root: Path, doc: dict, doc_rel: str, approved_commands: str | None = None) -> dict:
    if not doc.get("commit"):
        raise BlueprintError("this doc is not pinned to a commit (designs never are), so there is nothing to compare")
    changes = changed_since(root, doc["commit"])
    owned = owned_files(root, doc_rel)
    changes = {p: s for p, s in changes.items() if p not in owned}

    flagged: dict[str, list[str]] = {}
    cited: set[str] = set()
    for address, thing in [(b["id"], b) for _, b in blocks(doc)] + [(a, i) for a, _, _, i in items(doc)]:
        for cite in thing.get("cites", []):
            path, _ = split_cite(cite)
            path = Path(path).as_posix()
            inside(root, path, f"cite '{cite}'")
            cited.add(path)
            if status_of(thing) == "proposed":
                continue
            problem = cite_problem(root, cite)
            hit = [p for p in changes if covered(p, {path})]
            if problem:
                flagged.setdefault(address, []).append(f"{cite}: {problem}")
            elif hit:
                flagged.setdefault(address, []).append(f"{cite}: changed ({', '.join(sorted(hit)[:5])})")

    sources = [Path(s).as_posix() for s in doc.get("sources", ["."])]
    in_scope = lambda p: "." in sources or covered(p, set(sources))
    uncovered = {
        kind: sorted(p for p, s in changes.items() if s == kind and in_scope(p) and not covered(p, cited))
        for kind in ("A", "M", "D")
    }
    # A folder cite watches a block for change. It does not describe each file that later appears in
    # the folder, so a new one is listed even though some block cites its parent.
    folders = {c for c in cited if (root / c).is_dir()}
    in_cited_folder = sorted(
        p for p, s in changes.items() if s == "A" and in_scope(p) and p not in cited and covered(p, folders)
    )
    proposed = sorted(a for a, _, _, i in items(doc) if status_of(i) != "built")
    proposed += sorted(b["id"] for _, b in blocks(doc) if status_of(b) != "built")
    report = {
        "doc": doc_rel,
        "commit": doc.get("commit"),
        "changedFiles": len(changes),
        "flagged": flagged,
        "uncoveredAdded": uncovered["A"],
        "addedInCitedFolder": in_cited_folder,
        "uncoveredModified": uncovered["M"],
        "uncoveredDeleted": uncovered["D"],
        "notYetBuilt": proposed,
    }
    if not commands(doc):
        report["checks"] = {"state": "none recorded"}
    elif approved_commands == command_digest(doc):
        report["checks"] = {"state": "ran", "results": run_checks(root, doc)}
    else:
        # These strings came with the repository. Nothing runs until a person has seen them.
        report["checks"] = {
            "state": "not run: approval required",
            "approve": command_digest(doc),
            "commands": [{"group": g, "id": i, "command": c} for g, i, c in commands(doc)],
        }
    return report


def pin(root: Path, doc: dict, doc_rel: str, confirmed: set[str]) -> str:
    """Advance the doc's commit, only once every flagged item has been dealt with."""
    if doc.get("commit"):
        report = drift(root, doc, doc_rel)
        by_address = {b["id"]: b for _, b in blocks(doc)}
        by_address.update({a: i for a, _, _, i in items(doc)})
        pending = [
            a for a in report["flagged"]
            if a not in confirmed and by_address[a].get("evidence") != "unverified" and not by_address[a].get("open")
        ]
        if pending:
            raise BlueprintError(
                "not advancing the commit. Re-check these, then confirm them, or mark them "
                "'evidence': 'unverified' or 'open': '<reason>':\n  " + "\n  ".join(sorted(pending))
            )
    errors = validate(doc, root)[0]
    if errors:
        raise BlueprintError("not advancing the commit; the doc has errors:\n  " + "\n  ".join(errors))
    if git_text(root, "rev-parse", "-q", "--verify", "HEAD^{commit}") is None:
        raise BlueprintError("there is no commit yet, so the doc cannot be pinned")
    owned = owned_files(root, doc_rel)
    dirty = [
        p for p in git_files(root, "diff", "--name-only", "HEAD", "--")
        + git_files(root, "ls-files", "--others", "--exclude-standard")
        if p not in owned
    ]
    if dirty:
        raise BlueprintError("not advancing the commit; these are not committed: " + ", ".join(sorted(dirty)[:10]))
    head = subprocess.run([*GIT, "-C", str(root), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True)
    doc["commit"] = head.stdout.strip()
    return doc["commit"]


# ---------------------------------------------------------------- rendering


def render_html(doc: dict, fragment: bool = False) -> str:
    # '<' is escaped so no string in the doc can close the script element that carries it.
    payload = json.dumps(doc, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    payload = payload.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    css = (PAGE_DIR / "page.css").read_text(encoding="utf-8")
    script = (PAGE_DIR / "page.js").read_text(encoding="utf-8")
    shell = (PAGE_DIR / "shell.html").read_text(encoding="utf-8")
    head = f"<title>{html.escape(doc['title'])}</title>\n<style>\n{css}</style>\n"
    body = f'{shell}<script type="application/json" id="lb-data">{payload}</script>\n<script>\n{script}</script>\n'
    if fragment:
        return head + body
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        f"{head}</head>\n<body>\n{body}</body>\n</html>\n"
    )


def md_cell(text: str) -> str:
    return clean(text).replace("\\", "\\\\").replace("&", "&amp;").replace("<", "&lt;").replace("|", "\\|")


def shown_status(thing: dict, block: dict | None = None) -> str:
    """An item's own status, or its block's: everything in a new diagram is new."""
    own = status_of(thing)
    return status_of(block) if own == "built" and block is not None else own


def md_status(thing: dict, block: dict | None = None) -> str:
    status = shown_status(thing, block)
    return "" if status == "built" else f"**[{status.upper()}]** "


def mermaid_text(value) -> str:
    """Doc strings are untrusted: drop whatever could end a label, a statement or the code fence."""
    return " ".join(re.sub(r'["\[\]{}|<>`;#]|%%', " ", clean(value)).split())


def mark(status: str) -> str:
    # said in words, so the diagram reads without colour
    return "" if status == "built" else {"proposed": "NEW", "changed": "CHANGES", "removed": "REMOVES"}[status] + ": "


def mermaid_graph(block: dict) -> list[str]:
    ids = {n["id"]: f"n{i}" for i, n in enumerate(block.get("nodes", []))}
    out = ["```mermaid", "flowchart TB"]
    for node in block.get("nodes", []):
        status = shown_status(node, block)
        style = "" if status == "built" else f":::{status}"
        name = ids[node["id"]]
        out.append(f'  {name}["{mark(status)}{mermaid_text(node["title"]) or name}"]{style}')
    for edge in block.get("edges", []):
        status = shown_status(edge, block)
        label = (mark(status) + mermaid_text(edge.get("label", ""))).strip()
        arrow = "-->" if status == "built" else "-.->"
        if label:
            arrow += f'|"{label}"|'
        out.append(f'  {ids[edge["from"]]} {arrow} {ids[edge["to"]]}')
    out += [
        "  classDef proposed stroke:#8a4fd0,stroke-width:3px,stroke-dasharray:6 3",
        "  classDef changed stroke:#8a4fd0,stroke-width:3px",
        "  classDef removed stroke:#c0392b,stroke-width:2px,stroke-dasharray:2 3",
        "```",
    ]
    return out


def mermaid_swimlane(block: dict) -> list[str]:
    """A swimlane as a sequence diagram: lanes are participants, a step is the arrow reaching its lane."""
    lanes = {lane["id"]: f"L{i}" for i, lane in enumerate(block.get("lanes", []))}
    out = ["```mermaid", "sequenceDiagram"]
    out += [f"  participant {lanes[lane['id']]} as {mermaid_text(lane['title']) or lanes[lane['id']]}" for lane in block.get("lanes", [])]
    where: dict[str, str] = {}
    previous = None
    for number, step in enumerate(block.get("steps", []), 1):
        here = lanes[step["lane"]]
        sources = [where[s] for s in step["from"]] if step.get("from") else [previous or here]
        status = shown_status(step, block)
        arrow = "->>" if status == "built" else "-->>"
        text = f"{number}. {mark(status)}{mermaid_text(step['title'])}"
        out += [f"  {source}{arrow}{here}: {text}" for source in sources]
        effect = mermaid_text(step.get("effect") or "")
        if effect:
            out.append(f"  Note over {here}: {effect}")
        where[step.get("id")] = previous = here
    out.append("```")
    return out


def render_markdown(doc: dict) -> str:
    """A line-per-fact copy for review comments in a pull request. GitHub draws the mermaid."""
    out = [f"# {md_cell(doc['title'])}", "", "> Generated from the data file. Edit that, not this.", ""]
    if doc.get("kind") == "design":
        out += [f"State: **{doc.get('state', 'draft')}**", ""]
    if doc.get("summary"):
        out += [md_cell(doc["summary"]), ""]
    if doc.get("openQuestions"):
        out += ["## Open questions", ""] + [f"- {md_cell(q)}" for q in doc["openQuestions"]] + [""]
    for section in doc.get("sections", []):
        out += ["#" * (section.get("level", 2)) + " " + md_cell(section.get("title", section["id"])), ""]
        for block in section.get("blocks", []):
            kind = block["type"]
            if status_of(block) != "built":
                out += [md_status(block).strip(), ""]
            if kind == "graph":
                out += mermaid_graph(block) + [""]
            elif kind == "swimlane":
                out += mermaid_swimlane(block) + [""]
                lanes = {lane["id"]: lane["title"] for lane in block.get("lanes", [])}
                out += ["| # | Component | Step | Side effect |", "|---|---|---|---|"]
                for number, step in enumerate(block.get("steps", []), 1):
                    text = md_cell(step["title"]) + (f": {md_cell(step['note'])}" if step.get("note") else "")
                    out.append(f"| {number} | {md_cell(lanes[step['lane']])} | {md_status(step, block)}{text} | {md_cell(step.get('effect', ''))} |")
                out.append("")
            elif kind == "table":
                out.append("| " + " | ".join(md_cell(c) for c in block["columns"]) + " |")
                out.append("|" + "---|" * len(block["columns"]))
                for row in block.get("rows", []):
                    cells = [md_cell(c) for c in row["cells"]]
                    cells[0] = md_status(row, block) + cells[0]
                    out.append("| " + " | ".join(cells) + " |")
                out.append("")
            elif kind == "list":
                out += [f"- {md_status(i, block)}{md_cell(i.get('text', ''))}" for i in block.get("items", [])] + [""]
            elif kind == "bars":
                out += ["| Item | Value |", "|---|---|"] + [f"| {md_cell(b['label'])} | {b['value']} |" for b in block.get("bars", [])] + [""]
            elif kind == "code":
                code = block.get("code", "")
                longest = max((len(run) for run in re.findall("`+", code)), default=0)
                fence = "`" * max(3, longest + 1)
                out += [fence, code, fence, ""]
            elif kind == "text":
                out += [md_cell(block.get("text", "")), ""]
            caption = block.get("caption", {})
            if caption.get("takeaway"):
                out += [f"**{md_cell(caption['takeaway'])}** {md_cell(caption.get('text', ''))}".rstrip(), ""]
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------- pull request bodies

PR_OPEN = "<!-- living-blueprint:diagrams"
PR_CLOSE = "<!-- /living-blueprint:diagrams -->"
PR_LIMIT = 50_000  # GitHub stops a body at 65,536 characters, and the rest of it needs room


def prose(value) -> str:
    """Text outside a code fence is live on GitHub: it can notify people, link anywhere and, with a
    word like "closes", close an issue on merge. A zero-width space breaks each of those."""
    text = md_cell(value).replace("[", "\\[").replace("]", "\\]")  # no [words](hidden address)
    text = re.sub(r"([@#])(?=\w)", "\\1\u200b", text)
    text = re.sub(r"(?i)\b(gh-)(?=\d)", "\\1\u200b", text)
    text = text.replace("://", ":\u200b//")
    text = re.sub(r"(?i)\b(www)\.", "\\1\u200b.", text)
    return re.sub(r"(?i)\b(c)(lose[sd]?)\b|\b(f)(ix(?:es|ed)?)\b|\b(r)(esolve[sd]?)\b",
                  lambda m: "\u200b".join(g for g in m.groups() if g), text)


def git_text(root: Path, *args: str) -> str | None:
    out = subprocess.run([*GIT, "-C", str(root), *args], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def default_base(root: Path) -> str | None:
    head = git_text(root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    for ref in ([head.strip()] if head else []) + ["origin/main", "origin/master", "main", "master"]:
        if git_text(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}") is not None:
            return ref
    return None


def doc_at(root: Path, ref: str, path: str) -> dict | None:
    text = git_text(root, "show", f"{ref}:{path}")
    try:
        data = json.loads(text) if text is not None else None
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) and data.get(MARKER) == SCHEMA else None


def marked(root: Path, ref: str, paths: list[str]) -> list[str]:
    """Which of these carry the marker, asked of git once: a branch can change thousands of JSON
    files that have nothing to do with this tool."""
    if not paths:
        return []
    out = subprocess.run(
        [*GIT, "-C", str(root), "grep", "-z", "-l", "-F", "-e", f'"{MARKER}"', ref, "--", "*.json"],
        capture_output=True, text=True,
    )
    if out.returncode > 1:  # 1 is "no matches"
        raise BlueprintError(f"git grep failed: {out.stderr.strip()}")
    holders = {entry.partition(":")[2] for entry in out.stdout.split("\0") if entry}
    return [p for p in paths if p in holders]


def pr_section(root: Path, base: str | None = None, head: str = "HEAD") -> str | None:
    """The diagrams a pull request from head into base must show, or None when it has none."""
    base = base or default_base(root)
    for ref in (base, head):
        if not ref or ref.startswith("-"):
            raise BlueprintError("cannot tell which branches the pull request compares; pass --base")
    # gh takes a branch name; the local clone may only have it as a remote-tracking ref
    if git_text(root, "rev-parse", "-q", "--verify", f"origin/{base}^{{commit}}") is not None:
        base = f"origin/{base}"
    fork = git_text(root, "merge-base", base, head)
    if fork is None:
        raise BlueprintError(f"no common commit between {base} and {head}")
    fork = fork.strip()

    found = []  # (is architecture, path, doc, diagram blocks)
    broken = []
    changed = git_files(root, "diff", "--name-only", "--no-renames", "--diff-filter=d", fork, head, "--")
    for path in marked(root, head, [p for p in changed if p.endswith(".json")]):
        doc = doc_at(root, head, path)
        if doc is None:
            text = git_text(root, "show", f"{head}:{path}") or ""
            try:
                json.loads(text)  # valid JSON that is not a doc only mentions the marker
            except (ValueError, RecursionError):
                broken.append(f"{clean(path)}: not valid JSON")
            continue
        errors = validate(doc)[0]
        if errors:
            broken.append(f"{clean(path)}: {clean('; '.join(errors[:3]))}")
            continue
        diagrams = [b for _, b in blocks(doc) if b.get("type") in ("graph", "swimlane")]
        if doc.get("kind") != "design":
            before = doc_at(root, fork, path)
            old = {b.get("id"): b for _, b in blocks(before)} if before else {}
            diagrams = [b for b in diagrams if old.get(b["id"]) != b]
        if diagrams:
            found.append((doc.get("kind") != "design", path, doc, diagrams))
    if broken:
        raise InvalidDocs("this pull request changes docs that cannot be drawn; fix them first:\n  " + "\n  ".join(broken))
    if not found:
        return None

    body = ["## Diagrams", "", "Generated by living-blueprint from the files in this pull request. "
            "**NEW**, **CHANGES** and **REMOVES** mark what a design changes; unmarked parts are context."]
    size, omitted = 0, []
    for is_architecture, path, doc, diagrams in sorted(found, key=lambda f: (f[0], f[1])):
        title = prose(doc["title"])
        heading = ["", f"### {'Architecture doc updated' if is_architecture else 'Design'}: {title}", "",
                   f"`{re.sub('[`<>]', '?', clean(path))}`" + ("" if is_architecture else f" · state: {doc.get('state', 'draft')}")]
        body += heading
        for block in diagrams:
            takeaway = prose(block.get("caption", {}).get("takeaway", block["id"]))
            drawn = mermaid_graph(block) if block["type"] == "graph" else mermaid_swimlane(block)
            piece = ["", f"**{takeaway}**", ""] + drawn
            if is_architecture:
                piece = ["", f"<details><summary>{takeaway.replace('<', '&lt;')}</summary>", ""] + drawn + ["", "</details>"]
            length = sum(len(line) + 1 for line in piece)
            if size + length > PR_LIMIT:
                omitted.append(f"`{block['id']}`")
                continue
            size += length
            body += piece
    if omitted:
        body += ["", f"Left out to fit GitHub's size limit: {', '.join(omitted)}. Open the files above."]
    content = "\n".join(body)
    stamp = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f"{PR_OPEN} {stamp} -->\n{content}\n{PR_CLOSE}"


def put_section(body: str, section: str | None) -> str:
    """Replace the generated part of a body, or add it at the end. The rest is left alone."""
    pattern = re.compile(re.escape(PR_OPEN) + r".*?" + re.escape(PR_CLOSE), re.DOTALL)
    if pattern.search(body):
        return pattern.sub(lambda _: section or "", body, count=1)
    if not section:
        return body
    return (body.rstrip() + "\n\n" if body.strip() else "") + section + "\n"


# ---------------------------------------------------------------- command line


def emit(value) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blueprint.py", description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.getcwd(), help="any path inside the project (default: here)")
    sub = parser.add_subparsers(dest="command", required=True)
    where = sub.add_parser("where", help="show where docs live and what exists")
    where.add_argument("--docs-dir")
    setdir = sub.add_parser("set-dir", help="change where this project keeps its docs")
    setdir.add_argument("directory")
    setdir.add_argument("--move", action="store_true", help="also move the docs already there")
    check = sub.add_parser("validate")
    check.add_argument("doc")
    check.add_argument("--no-cites", action="store_true", help="skip checking cited names against the tree")
    render = sub.add_parser("render")
    render.add_argument("doc")
    render.add_argument("--markdown", action="store_true", help="also write a .md copy")
    render.add_argument("--fragment", metavar="FILE", help="write a page without the document wrapper, for publishing")
    for name in ("approve", "ready", "gaps"):
        sub.add_parser(name).add_argument("doc")
    merge = sub.add_parser("integrate")
    merge.add_argument("architecture")
    merge.add_argument("design")
    done = sub.add_parser("resolve")
    done.add_argument("doc")
    done.add_argument("slug")
    group = done.add_mutually_exclusive_group(required=True)
    group.add_argument("--built", action="store_true")
    group.add_argument("--drop", action="store_true")
    look = sub.add_parser("drift", help="report what may be out of date; changes nothing")
    look.add_argument("doc")
    look.add_argument("--run-commands", metavar="APPROVAL", help="the code printed with the commands, after a person has read them")
    request = sub.add_parser("pr-body", help="the Mermaid diagrams for a pull request's description")
    request.add_argument("--base", help="branch the pull request merges into")
    request.add_argument("--head", default="HEAD")
    request.add_argument("--into", metavar="FILE", help="add or replace the section in this body file")
    advance = sub.add_parser("pin", help="move a doc to the current commit")
    advance.add_argument("doc")
    advance.add_argument("--confirmed", default="", help="comma-separated flagged addresses that were re-checked")
    args = parser.parse_args(argv)

    try:
        root = repo_root(Path(args.repo))

        def located(name: str) -> tuple[Path, str, dict]:
            path = Path(name)
            path = path if path.is_absolute() else root / path
            if path.is_symlink():
                raise BlueprintError(f"{name}: is a symlink; name the file itself")
            path = path.resolve()
            if root not in path.parents:
                raise BlueprintError(f"{name}: not inside the repository {root}")
            relative = path.relative_to(root).as_posix()
            inside(root, relative, name)
            return path, relative, load_json(path)

        if args.command == "where":
            directory, source = docs_dir(root, args.docs_dir)
            docs = find_docs(root)
            emit({"repo": str(root), "docsDir": directory, "from": source, "docs": docs,
                  "outsideDocsDir": [d for d in docs if not covered(d, {directory}) and directory != "."]})
        elif args.command == "set-dir":
            moved = set_docs_dir(root, args.directory, args.move)
            emit({"docsDir": args.directory, "config": CONFIG, "moved": moved})
        elif args.command == "validate":
            _, _, doc = located(args.doc)
            errors, warnings = validate(doc, None if args.no_cites else root)
            emit({"errors": errors, "warnings": warnings})
            return 1 if errors else 0
        elif args.command == "render":
            path, _, doc = located(args.doc)
            errors = validate(doc)[0]
            if errors:
                raise BlueprintError("cannot render:\n  " + "\n  ".join(errors))
            outputs = [(path.with_suffix(".html"), render_html(doc), root)]
            if args.markdown:
                outputs.append((path.with_suffix(".md"), render_markdown(doc), root))
            if args.fragment:  # may be anywhere the caller names, such as a scratch folder
                outputs.append((Path(args.fragment), render_html(doc, fragment=True), None))
            for target, text, below in outputs:
                refuse_links(target, below)  # all of them, before the first is written
                encoded(target, text)
            for target, text, below in outputs:
                safe_write(target, text, below)
            written = [target for target, _, _ in outputs]
            emit({"written": [str(p) for p in written]})
        elif args.command in ("approve", "ready", "gaps"):
            path, _, doc = located(args.doc)
            if args.command == "gaps":
                emit({"gaps": validate(doc)[0] + design_gaps(doc)})
            elif args.command == "approve":
                approve(doc)
                write_json(path, doc)
                emit({"state": "approved", "digest": doc["approvedDigest"]})
            else:
                ready_to_build(doc)
                emit({"ready": True})
        elif args.command == "integrate":
            path, _, architecture = located(args.architecture)
            _, _, design = located(args.design)
            write_json(path, integrate(architecture, design))
            emit({"integrated": design["id"], "into": str(path)})
        elif args.command == "resolve":
            path, _, doc = located(args.doc)
            outcome = "built" if args.built else "drop"
            if doc.get("kind") == "design" and doc.get("id") == args.slug:
                doc["state"] = "built" if args.built else "dropped"
                write_json(path, doc)
            else:
                write_json(path, resolve(doc, args.slug, outcome))
            emit({"resolved": args.slug, "outcome": outcome})
        elif args.command == "drift":
            _, relative, doc = located(args.doc)
            errors = validate(doc)[0]
            if errors:
                raise BlueprintError("the doc is not well formed:\n  " + "\n  ".join(errors))
            emit(drift(root, doc, relative, args.run_commands))
        elif args.command == "pr-body":
            section = pr_section(root, args.base, args.head)
            stale = [p for p in git_files(root, "diff", "--name-only", "HEAD", "--") if p.endswith(".json") and doc_at(root, "HEAD", p)]
            if stale:
                print("blueprint: not committed, so not in these diagrams: " + ", ".join(stale), file=sys.stderr)
            if args.into:
                target = Path(args.into)
                refuse_links(target)
                before = target.read_text(encoding="utf-8") if target.exists() else ""
                safe_write(target, put_section(before, section))
                emit({"into": str(target), "diagrams": bool(section)})
            else:
                print(section or "")
        elif args.command == "pin":
            path, relative, doc = located(args.doc)
            commit = pin(root, doc, relative, {c for c in args.confirmed.split(",") if c})
            write_json(path, doc)
            emit({"commit": commit})
    except BlueprintError as error:
        print(f"blueprint: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
