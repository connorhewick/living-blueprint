#!/usr/bin/env python3
"""Hooks for pull requests on a branch that changed living-blueprint diagrams.

Before a tool runs: such a pull request is not opened, and its body is not rewritten, without the
current Mermaid copy, whether it goes through `gh` or a GitHub connector. For a pull request named
by number or address, `gh pr view` is asked which branches it compares. The copy must come from a
body file or a quoted heredoc: anywhere else, the shell runs parts of it. After `git push`: a
reminder that an open pull request's diagrams may now be out of date.

It allows the call whenever it cannot tell: a hook that blocks unrelated pull requests gets
disabled. Exit 2 shows stderr to the model, and before a tool runs it also refuses the call. It
does not see a pull request made on the website or outside Claude."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# `blueprint` is imported only where it is needed: this file runs on every Bash call in every project

HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*([\"']?)([A-Za-z_]\w*)\2")
# a --body that is one quoted heredoc and nothing else, as it reads once the heredoc's lines are out
QUOTED_BODY = re.compile(r"\s*\$\(\s*cat\s+<<-?\s*([\"'])[A-Za-z_]\w*\1\s*\)\s*")
MARKED = "<!-- living-blueprint:diagrams"  # blueprint.PR_OPEN, without importing it
REDIRECT = re.compile(r"[<>&|]*[<>][<>&|]*")
PULL_REQUEST = re.compile(r"#?(\d+)|(https://\S+/pull/\d+\S*)")
EDIT_SWITCHES = ("--remove-milestone",)  # every other `gh pr edit` flag takes a value
INLINE = (
    "Refused: the living-blueprint section is where the shell expands it (directly in --body, or in "
    "an unquoted heredoc), so parts of it would run as commands and the body would arrive damaged. "
    "Write the body to a file and pass it with --body-file."
)
SEPARATORS = set(";&|()\n")
WRAPPERS = ("env", "command", "exec", "nohup", "time", "then", "do", "else", "!", "{")


def split_heredocs(command: str) -> tuple[list[str], list[str], list[str]]:
    """(lines of code, quoted heredoc bodies, unquoted heredoc bodies). The shell leaves a quoted
    body as it is written; it expands an unquoted one."""
    lines: list[str] = []
    bodies: tuple[list[str], list[str]] = ([], [])
    waiting: list[tuple[str, bool, bool]] = []
    body: list[str] = []
    continued = ""
    for line in command.split("\n"):
        if waiting:
            delimiter, quoted, tabs = waiting[0]
            if (line.lstrip("\t") if tabs else line) == delimiter:
                bodies[0 if quoted else 1].append("\n".join(body))
                body = []
                waiting.pop(0)
            else:
                body.append(line)
            continue
        # joined only out here: inside a body, a closing backslash must not swallow the delimiter
        if (len(line) - len(line.rstrip("\\"))) % 2:
            continued += line[:-1] + " "
            continue
        line, continued = continued + line, ""
        lines.append(line)
        waiting += [(f.group(3), bool(f.group(2)), bool(f.group(1))) for f in HEREDOC.finditer(line)]
    return lines + ([continued] if continued else []), *bodies


def code_only(command: str) -> str:
    """The command without heredoc bodies and comments: text there only mentions a command."""
    lines = split_heredocs(command)[0]
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
        before: list[str] = []
        while rest and rest[0].startswith(("-R", "--repo")):
            width = 2 if rest[0] in ("-R", "--repo") else 1
            before, rest = before + rest[:width], rest[width:]
        if not rest or len(rest) < 2 or rest[0] != "pr" or rest[1] not in ("create", "new", "edit"):
            continue
        arguments = rest[2:] + before
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


def selector(arguments: list[str]) -> str | None:
    """Which pull request `gh pr edit` names: its one argument that is no flag, value or redirect."""
    found, found_at, skip = None, -2, False
    for index, word in enumerate(arguments):
        if skip:
            skip = False
        elif REDIRECT.fullmatch(word):
            if found_at == index - 1 and found.isdigit():
                found = None  # the 2 of `2>&1`
            skip = True
        elif word.startswith("-") and word != "-":
            skip = "=" not in word and word not in EDIT_SWITCHES and (word.startswith("--") or len(word) == 2)
        elif found is None:
            found, found_at = word, index
    return found


def branches_of(number: str, repo: str | None, cwd: Path) -> tuple[str, str] | None:
    """(head, base) of an existing pull request, or None when that cannot be told. No shell: the
    number and repository come from the command being checked."""
    command = ["gh", "pr", "view", number, "--json", "headRefName,baseRefName,isCrossRepository"]
    try:
        out = subprocess.run(command + ([f"--repo={repo}"] if repo else []), cwd=cwd, capture_output=True, text=True, timeout=10)
        data = json.loads(out.stdout) if out.returncode == 0 else {}
        if data.get("isCrossRepository", True):
            return None  # a fork's branch name says nothing about the local branch of that name
        return str(data["headRefName"]), str(data["baseRefName"])
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, AttributeError):
        return None


def local_ref(root: Path, branch: str) -> str | None:
    import blueprint as bp

    for ref in (branch, f"origin/{branch}"):
        if not ref.startswith("-") and bp.git_text(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}") is not None:
            return ref
    return None


def numbered(root: Path, number: str, repo: str | None, cwd: Path) -> tuple[str, str] | None:
    """(local head, base) for a pull request named by number or address, saying so when unknown."""
    found = branches_of(number, repo, cwd)
    head = local_ref(root, found[0]) if found else None
    if head is None:
        print(f"living-blueprint: diagram check skipped: cannot find the branches of pull request {number[:100]}", file=sys.stderr)
        return None
    return head, found[1]


def current_section(root: Path, base: str | None, head: str) -> tuple[str | None, str | None]:
    """(section, refusal). A doc that cannot be drawn is a known problem, not a doubt to allow."""
    import blueprint as bp

    try:
        return bp.pr_section(root, base, head), None
    except bp.InvalidDocs as error:
        return None, f"Refused: {error}"


def refusal(command: str, cwd: Path) -> str | None:
    try:
        found = list(pull_request_commands(command))
    except ValueError:
        # an inline section brings quotes of its own, which can leave the line unreadable
        lines, _, unquoted = split_heredocs(command)
        text = "\n".join(lines + unquoted)
        if MARKED in text and re.search(r"\bgh\b[^\n]*\bpr\s+(create|new|edit)\b", text):
            return INLINE
        raise
    for verb, arguments in found:
        message = check_one(command, verb, arguments, moved_to(command, cwd))
        if message:
            return message
    return None


def check_one(command: str, verb: str, arguments: list[str], cwd: Path) -> str | None:
    body_file = option(arguments, "--body-file", "-F")
    body = option(arguments, "--body", "-b")
    if verb == "edit" and body_file is None and body is None:
        return None
    _, quoted, unquoted = split_heredocs(command)
    quoted_in_body = body is not None and QUOTED_BODY.fullmatch(body) is not None
    from_heredoc = body_file == "-" or quoted_in_body
    # refused whatever the branch turns out to be: this text must never reach the shell
    expanded = (body is not None and MARKED in body) or (
        (body_file == "-" or (body or "").lstrip().startswith("$(")) and any(MARKED in b for b in unquoted)
    )
    if expanded:
        return INLINE

    import blueprint as bp

    root = bp.repo_root(cwd)
    base = option(arguments, "--base", "-B")
    head = option(arguments, "--head", "-H")
    head = head.split(":")[-1] if head else "HEAD"
    if verb == "edit":
        named = selector(arguments)
        pull_request = PULL_REQUEST.fullmatch(named or "")
        if pull_request:
            repo = option(arguments, "--repo", "-R")
            found = numbered(root, pull_request.group(1) or pull_request.group(2), repo, cwd)
            if found is None:
                return None
            head, base = found[0], base or found[1]
        elif named:
            head = named  # a branch name says what to compare
    section, broken = current_section(root, base, head)
    if broken or section is None:
        return broken

    given: list[str] = list(quoted) if from_heredoc else []
    if body_file and body_file != "-":
        path = Path(body_file).expanduser()
        path = path if path.is_absolute() else cwd / path
        if path.is_file():
            given.append(path.read_text(encoding="utf-8", errors="replace"))
    if any(section in text.replace("\r\n", "\n") for text in given):
        return None
    return (
        "Refused: this branch changes living-blueprint diagrams, and the pull request body does not "
        "carry their current Mermaid copy in a body file or a quoted heredoc. Write the rest of the "
        "body to a file, then:\n"
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
    base = arguments.get("base")
    head = arguments.get("head")
    head = str(head).split(":")[-1] if head else None
    number = next((str(arguments[k]) for k in ("pullNumber", "pull_number", "number") if k in arguments), "")
    if head is None and "create" not in name and number.isdigit():
        owner, repo = str(arguments.get("owner", "")), str(arguments.get("repo", ""))
        full = f"{owner}/{repo}"
        found = numbered(root, number, full if re.fullmatch(r"[\w.-]+/[\w.-]+", full) else None, cwd)
        if found is None:
            return None
        head, base = found[0], base or found[1]
    section, broken = current_section(root, base, head or "HEAD")
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
        why = " ".join(str(error).split())[:150]  # it can carry text from a doc or a command
        print(f"living-blueprint: pull request diagram check skipped ({why})", file=sys.stderr)
        return 0
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
