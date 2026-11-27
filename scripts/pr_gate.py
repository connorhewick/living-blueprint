#!/usr/bin/env python3
"""Hooks for pull requests on a branch that changed living-blueprint diagrams.

Before a tool runs: such a pull request is not opened, and its body is not rewritten, without the
current Mermaid copy, whether it goes through `gh` or a GitHub connector (`gh pr edit <number>` is
the exception: nothing here says which branch that is). After `git push`: a
reminder that an open pull request's diagrams may now be out of date.

It allows the call whenever it cannot tell: a hook that blocks unrelated pull requests gets
disabled. Exit 2 shows stderr to the model, and before a tool runs it also refuses the call. It
does not see a pull request made on the website or outside Claude."""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# `blueprint` is imported only where it is needed: this file runs on every Bash call in every project

HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*([\"']?)([A-Za-z_]\w*)\1")
SEPARATORS = set(";&|()\n")
WRAPPERS = ("env", "command", "exec", "nohup", "time", "then", "do", "else", "!", "{")


def code_only(command: str) -> str:
    """The command without heredoc bodies and comments: text there only mentions a command."""
    lines, waiting = [], []
    for line in command.replace("\\\n", " ").split("\n"):
        if waiting:
            if line.strip() == waiting[0]:
                waiting.pop(0)
            continue
        lines.append(line)
        waiting += [found.group(2) for found in HEREDOC.finditer(line)]
    kept, quote, comment, escaped, before = [], "", False, False, " "
    for char in "\n".join(lines):
        if comment:
            if char != "\n":
                continue
            comment = False
        elif escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char == "#" and (before in SEPARATORS or before.isspace()):
            comment = True
            continue
        kept.append(char)
        before = char
    return "".join(kept)


def simple_commands(command: str):
    """The words of each command in a shell line. A quoted string stays one word, so what it says
    is never taken for a command."""
    lexer = shlex.shlex(code_only(command), posix=True, punctuation_chars=";&|()<>\n")
    lexer.whitespace, lexer.whitespace_split, lexer.commenters = " \t\r", True, ""
    words: list[str] = []
    for token in lexer:
        if token and set(token) <= SEPARATORS:
            if words:
                yield words
            words = []
        else:
            words.append(token)
    if words:
        yield words


def program(words: list[str], name: str) -> list[str] | None:
    """The arguments, when this simple command runs `name`."""
    while words and (words[0] in WRAPPERS or re.match(r"[A-Za-z_]\w*=", words[0])):
        words = words[1:]
    return words[1:] if words and words[0].rsplit("/", 1)[-1] == name else None


def pull_request_commands(command: str):
    """(verb, arguments) for each `gh pr create` or `gh pr edit` the shell would really run."""
    for words in simple_commands(command):
        rest = program(words, "gh")
        while rest and rest[0].startswith(("-R", "--repo")):
            rest = rest[2 if rest[0] in ("-R", "--repo") else 1 :]
        if not rest or len(rest) < 2 or rest[0] != "pr" or rest[1] not in ("create", "new", "edit"):
            continue
        arguments = rest[2:]
        if "--help" not in arguments and "--dry-run" not in arguments:
            yield "edit" if rest[1] == "edit" else "create", arguments


def moved_to(command: str, cwd: Path) -> Path:
    """`cd somewhere && ...` runs there, not where the session is."""
    moved = re.match(r"\s*cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|]+)\s*(?:&&|;|\n)", command)
    return (cwd / Path(shlex.split(moved.group(1))[0]).expanduser()).resolve() if moved else cwd


def how_to_fix(root: Path) -> str:
    script = Path(__file__).resolve().parent / "blueprint.py"
    return f"  python3 \"{script}\" --repo \"{root}\" pr-body --base <base branch> --into <body file>"


def option(arguments: list[str], *names: str) -> str | None:
    for index, word in enumerate(arguments):
        for name in names:
            if word == name:
                return arguments[index + 1] if index + 1 < len(arguments) else ""
            if word.startswith(name + "="):
                return word[len(name) + 1 :]
            if len(name) == 2 and word.startswith(name):
                return word[2:]
    return None


def current_section(root: Path, base: str | None, head: str) -> tuple[str | None, str | None]:
    """(section, refusal). A doc that cannot be drawn is a known problem, not a doubt to allow."""
    import blueprint as bp

    try:
        return bp.pr_section(root, base, head), None
    except bp.InvalidDocs as error:
        return None, f"Refused: {error}"


def refusal(command: str, cwd: Path) -> str | None:
    for verb, arguments in pull_request_commands(command):
        message = check_one(command, verb, arguments, moved_to(command, cwd))
        if message:
            return message
    return None


def check_one(command: str, verb: str, arguments: list[str], cwd: Path) -> str | None:
    body_file = option(arguments, "--body-file", "-F")
    sets_body = body_file is not None or option(arguments, "--body", "-b") is not None
    head = option(arguments, "--head", "-H")
    if verb == "edit":
        if not sets_body:
            return None
        if arguments and not arguments[0].startswith("-"):
            head = arguments[0]  # a branch name says what to compare; a number or address does not
            if head.isdigit() or "://" in head:
                print("living-blueprint: diagram check skipped: cannot tell which branch that pull request is", file=sys.stderr)
                return None

    import blueprint as bp

    root = bp.repo_root(cwd)
    section, broken = current_section(root, option(arguments, "--base", "-B"), head.split(":")[-1] if head else "HEAD")
    if broken or section is None:
        return broken

    shown = command
    if body_file and body_file != "-":
        path = Path(body_file).expanduser()
        path = path if path.is_absolute() else cwd / path
        if path.is_file():
            shown += "\n" + path.read_text(encoding="utf-8", errors="replace")
    if section in shown.replace("\r\n", "\n"):
        return None
    return (
        "Refused: this branch changes living-blueprint diagrams, and the pull request body does not "
        "carry their current Mermaid copy. Write the rest of the body to a file, then:\n"
        f"{how_to_fix(root)}\n"
        "and pass that file with --body-file. For an open pull request, first save its current body "
        "with `gh pr view <n> --json body -q .body > <body file>`. In a command that was just "
        "refused, a body file written by that same command does not exist yet: write it first."
    )


def connector_refusal(tool: str, arguments: dict, cwd: Path) -> str | None:
    """A GitHub connector carries the body as a field. Matched by words in the tool's name, since
    connectors name their tools differently."""
    name = tool.lower()
    if "pull_request" not in name or not any(verb in name for verb in ("create", "update")):
        return None
    if any(other in name for other in ("review", "comment", "branch", "copilot")):
        return None
    body = arguments.get("body")
    if body is None and "create" not in name:
        return None

    import blueprint as bp

    root = bp.repo_root(cwd)
    head = arguments.get("head")
    section, broken = current_section(root, arguments.get("base"), str(head).split(":")[-1] if head else "HEAD")
    if broken:
        return broken
    if section is None or section in str(body or "").replace("\r\n", "\n"):
        return None
    return (
        "Refused: this branch changes living-blueprint diagrams, and the pull request body does not "
        "carry their current Mermaid copy. Put the output of this in the body, unchanged:\n"
        f"{how_to_fix(root)}"
    )


def pushed_from(command: str, cwd: Path) -> Path | None:
    """Where a `git push` in this line runs, or None when there is none."""
    for words in simple_commands(command):
        rest = program(words, "git")
        where = moved_to(command, cwd)
        while rest and rest[0].startswith("-"):
            if rest[0] == "-C" and len(rest) > 1:
                where = (where / Path(rest[1]).expanduser()).resolve()
            rest = rest[2 if rest[0] in ("-C", "-c") else 1 :]
        if rest and rest[0] == "push" and "--dry-run" not in rest and "--help" not in rest:
            return where
    return None


def push_reminder(command: str, cwd: Path) -> str | None:
    where = pushed_from(command, cwd)
    if where is None:
        return None

    import blueprint as bp

    section, broken = current_section(bp.repo_root(where), None, "HEAD")
    if broken:
        return "After this push: " + broken.replace("Refused: ", "")
    if section is None:
        return None
    return (
        "This branch changes living-blueprint diagrams. If a pull request is open for it, pushing "
        "did not update its body: run /living-blueprint:pr so the diagrams on GitHub are current."
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
        tool = str(event.get("tool_name", ""))
        arguments = event.get("tool_input", {})
        cwd = Path(event.get("cwd") or ".")
        command = arguments.get("command", "")
        if tool.startswith("mcp__"):
            message = connector_refusal(tool, arguments, cwd)
        elif event.get("hook_event_name") == "PostToolUse":
            message = push_reminder(command, cwd) if "push" in command else None
        else:
            message = refusal(command, cwd) if "gh" in command else None
    except Exception as error:  # allow, and say so: see the module docstring
        print(f"living-blueprint: pull request diagram check skipped ({error})", file=sys.stderr)
        return 0
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
