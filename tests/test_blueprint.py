"""python3 -m unittest discover -s tests"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import blueprint as bp  # noqa: E402
import pr_gate  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "shop"
ARCH = "docs/architecture/shop.json"
DESIGN = "docs/architecture/designs/order-cancel/design.json"


def git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        check=True, capture_output=True,
    )


class Repo(unittest.TestCase):
    """A throwaway git copy of the made-up shop, with its doc pinned to the first commit."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = (Path(self.folder.name) / "shop").resolve()
        shutil.copytree(FIXTURE, self.root)
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "add", "api", "db", "web", "worker")
        git(self.root, "commit", "-qm", "code")
        self.doc = self.load(ARCH)
        bp.pin(self.root, self.doc, ARCH, set())

    def load(self, name):
        return json.loads((self.root / name).read_text())

    def edit(self, name, old, new):
        path = self.root / name
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))


class Location(Repo):
    def test_default_then_config_then_argument(self):
        self.assertEqual(bp.docs_dir(self.root), ("docs/architecture", "default"))
        bp.set_docs_dir(self.root, "wiki/arch", move=False)
        self.assertEqual(bp.docs_dir(self.root), ("wiki/arch", "config"))
        self.assertEqual(bp.docs_dir(self.root, "services/a/docs"), ("services/a/docs", "argument"))

    def test_paths_that_leave_the_repository_are_refused(self):
        (self.root / "escape").symlink_to(self.root.parent)
        for bad in ("/etc", "../out", "a/../../out", "~/docs", "escape/docs", ".git/hooks", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(bp.BlueprintError):
                    bp.set_docs_dir(self.root, bad, move=False)
                with self.assertRaises(bp.BlueprintError):
                    bp.docs_dir(self.root, bad or "..")

    def test_a_hostile_config_is_refused(self):
        bp.write_json(self.root / bp.CONFIG, {"docsDir": "../../outside"})
        with self.assertRaises(bp.BlueprintError):
            bp.docs_dir(self.root)

    def test_move_takes_the_docs_and_their_pages_but_nothing_else(self):
        (self.root / "docs/architecture/shop.html").write_text("page")
        (self.root / "docs/architecture/notes.txt").write_text("mine")
        bp.set_docs_dir(self.root, "handbook", move=True)
        self.assertTrue((self.root / "handbook/shop.json").exists())
        self.assertTrue((self.root / "handbook/shop.html").exists())
        self.assertTrue((self.root / "handbook/designs/order-cancel/design.json").exists())
        self.assertTrue((self.root / "docs/architecture/notes.txt").exists())

    def test_move_refuses_to_overwrite(self):
        (self.root / "handbook").mkdir()
        (self.root / "handbook/shop.json").write_text("{}")
        with self.assertRaises(bp.BlueprintError):
            bp.set_docs_dir(self.root, "handbook", move=True)
        self.assertTrue((self.root / ARCH).exists())

    def test_docs_are_found_by_marker_wherever_they_are(self):
        (self.root / "elsewhere").mkdir()
        shutil.move(self.root / ARCH, self.root / "elsewhere/renamed.json")
        self.assertIn("elsewhere/renamed.json", bp.find_docs(self.root))


class WithoutGit(unittest.TestCase):
    def test_docs_can_still_be_located(self):
        with tempfile.TemporaryDirectory() as folder:
            root = (Path(folder) / "plain").resolve()
            shutil.copytree(FIXTURE, root)
            self.assertIn(ARCH, bp.find_docs(root))


class Validation(Repo):
    def test_fixtures_are_valid(self):
        self.assertEqual(bp.validate(self.load(ARCH), self.root)[0], [])
        self.assertEqual(bp.validate(self.load(DESIGN), self.root)[0], [])

    def test_a_cited_name_that_does_not_exist_is_an_error(self):
        doc = self.load(ARCH)
        doc["sections"][0]["blocks"][0]["nodes"][0]["cites"] = ["web/src/Checkout.tsx#Checkou"]
        self.assertTrue(any("symbol is missing" in e for e in bp.validate(doc, self.root)[0]))

    def test_cites_may_not_leave_the_repository(self):
        doc = self.load(ARCH)
        doc["sections"][0]["blocks"][0]["nodes"][0]["cites"] = ["../../etc/passwd#root"]
        self.assertTrue(any("'..'" in e for e in bp.validate(doc, self.root)[0]))

    def test_structural_mistakes_are_reported(self):
        doc = self.load(ARCH)
        graph = doc["sections"][0]["blocks"][0]
        graph["edges"].append({"from": "checkout", "to": "nowhere"})
        graph["nodes"][1]["col"], graph["nodes"][1]["row"] = 0, 0
        doc["commit"] = "--output=/tmp/x"
        errors = " ".join(bp.validate(doc)[0])
        for expected in ("is not a node", "shares a grid cell", "commit must be"):
            self.assertIn(expected, errors)


class Approval(Repo):
    def test_only_an_unchanged_approved_design_may_be_built(self):
        design = self.load(DESIGN)
        with self.assertRaises(bp.BlueprintError):
            bp.ready_to_build(design)
        bp.approve(design)
        bp.ready_to_build(design)
        design["sections"][-1]["blocks"][0]["items"].pop()
        with self.assertRaisesRegex(bp.BlueprintError, "changed after"):
            bp.ready_to_build(design)

    def test_open_questions_and_missing_parts_block_approval(self):
        design = self.load(DESIGN)
        design["openQuestions"] = ["Who may cancel?"]
        design["sections"][-1]["blocks"][0]["items"] = []
        with self.assertRaises(bp.BlueprintError) as caught:
            bp.approve(design)
        self.assertIn("Who may cancel?", str(caught.exception))
        self.assertIn("acceptance", str(caught.exception))


class Integration(Repo):
    def test_drop_restores_the_original_exactly(self):
        arch = self.load(ARCH)
        merged = bp.integrate(arch, self.load(DESIGN))
        self.assertNotEqual(merged, arch)
        self.assertEqual(bp.resolve(merged, "order-cancel", "drop"), arch)

    def test_proposals_are_marked_and_design_only_parts_stay_out(self):
        merged = bp.integrate(self.load(ARCH), self.load(DESIGN))
        found = {a: i for a, _, _, i in bp.items(merged)}
        self.assertEqual(found["layers/notify"]["status"], "proposed")
        self.assertEqual(found["layers/service"]["status"], "changed")
        self.assertEqual(found["layers/service"]["was"]["lines"], ["Only writer of orders"])
        ids = {b["id"] for _, b in bp.blocks(merged)}
        self.assertIn("cancel-flow", ids)
        self.assertNotIn("options-table", ids)
        self.assertNotIn("acceptance-list", ids)

    def test_built_clears_the_marks_and_leaves_claims_unverified(self):
        merged = bp.integrate(self.load(ARCH), self.load(DESIGN))
        built = bp.resolve(merged, "order-cancel", "built")
        found = {a: i for a, _, _, i in bp.items(built)}
        self.assertNotIn("status", found["layers/notify"])
        self.assertEqual(found["layers/notify"]["evidence"], "unverified")
        self.assertNotIn('"design"', json.dumps(built))

    def test_two_designs_may_not_change_the_same_thing(self):
        merged = bp.integrate(self.load(ARCH), self.load(DESIGN))
        other = self.load(DESIGN)
        other["id"] = "other"
        for _, block in bp.blocks(other):
            block["id"] = block["id"] if block["id"] == "layers" else "other-" + block["id"]
            for node in block.get("nodes", []):
                if node["id"] == "notify":
                    node["id"], node["col"], node["row"] = "other-node", 2, 0
            for edge in block.get("edges", []):
                edge["to"] = "other-node"
        with self.assertRaisesRegex(bp.BlueprintError, "already changed"):
            bp.integrate(merged, other)


class Drift(Repo):
    def report(self, **kwargs):
        return bp.drift(self.root, self.doc, ARCH, **kwargs)

    def test_nothing_changed_means_nothing_flagged(self):
        report = self.report()
        self.assertEqual(report["flagged"], {})
        self.assertEqual(report["uncoveredAdded"], [])

    def test_a_removed_name_and_a_changed_file_are_flagged(self):
        self.edit("api/queue.py", "def publish(", "def emit(")
        flagged = self.report()["flagged"]
        self.assertIn("layers/queue", flagged)
        self.assertIn("symbol is missing", flagged["layers/queue"][0])
        self.assertNotIn("gaps/no-outbox", flagged)  # it cites orders.py, which did not change

    def test_a_committed_edit_to_a_cited_file_is_flagged(self):
        self.edit("api/queue.py", "print(topic, message)", "print(message)")
        git(self.root, "commit", "-qam", "change")
        self.assertIn("changed (api/queue.py)", self.report()["flagged"]["layers/queue"][0])

    def test_new_code_the_doc_does_not_cover_is_listed(self):
        (self.root / "worker/refunds.py").write_text("def refund(): pass\n")
        self.assertEqual(self.report()["uncoveredAdded"], ["worker/refunds.py"])

    def test_a_new_file_inside_a_cited_folder_is_not_hidden_by_it(self):
        # the shop's size chart cites the whole api/ folder; that must not count as covering a new file
        (self.root / "api/admin.py").write_text("def force(): pass\n")
        report = self.report()
        self.assertEqual(report["addedInCitedFolder"], ["api/admin.py"])
        self.assertIn("size", report["flagged"])

    def test_scope_limits_what_counts_as_uncovered(self):
        self.doc["sources"] = ["api"]
        (self.root / "worker/refunds.py").write_text("x = 1\n")
        self.assertEqual(self.report()["uncoveredAdded"], [])

    def test_commands_never_run_without_the_approval_code(self):
        canary = self.root / "ran"
        self.doc["checks"]["measures"][0]["command"] = f"touch '{canary}'; echo 2"
        for approval in (None, "wrong"):
            report = self.report(approved_commands=approval)
            self.assertFalse(canary.exists())
            self.assertIn("approval required", report["checks"]["state"])
        self.report(approved_commands=report["checks"]["approve"])
        self.assertTrue(canary.exists())

    def test_an_approval_does_not_carry_over_to_edited_commands(self):
        approval = bp.command_digest(self.doc)
        canary = self.root / "ran"
        self.doc["checks"]["measures"][0]["command"] = f"touch '{canary}'"
        self.report(approved_commands=approval)
        self.assertFalse(canary.exists())

    def test_measures_and_inventory_report_differences_and_failures(self):
        self.edit("db/schema.sql", "CREATE TABLE order_events", "CREATE TABLE refunds (id text);\nCREATE TABLE order_events")
        self.doc["checks"]["measures"][0]["command"] = "false"
        report = self.report(approved_commands=bp.command_digest(self.doc))
        results = {r["id"]: r for r in report["checks"]["results"]}
        self.assertEqual(results["routes"]["state"], "failed")
        self.assertEqual(results["tables"]["added"], ["refunds"])

    def test_pin_waits_until_every_flagged_item_is_dealt_with(self):
        self.edit("api/queue.py", "print(topic, message)", "print(message)")
        git(self.root, "commit", "-qam", "change")
        before = self.doc["commit"]
        with self.assertRaisesRegex(bp.BlueprintError, "layers/queue"):
            bp.pin(self.root, self.doc, ARCH, set())
        self.assertEqual(self.doc["commit"], before)
        confirmed = set(self.report()["flagged"])
        self.assertNotEqual(bp.pin(self.root, self.doc, ARCH, confirmed), before)

    def test_pin_accepts_an_item_marked_unverified(self):
        self.edit("api/queue.py", "print(topic, message)", "print(message)")
        git(self.root, "commit", "-qam", "change")
        for address, thing in [(b["id"], b) for _, b in bp.blocks(self.doc)] + [(a, i) for a, _, _, i in bp.items(self.doc)]:
            if address in self.report()["flagged"]:
                thing["evidence"] = "unverified"
        bp.pin(self.root, self.doc, ARCH, set())

    def test_pin_refuses_uncommitted_code(self):
        (self.root / "worker/refunds.py").write_text("x = 1\n")
        with self.assertRaisesRegex(bp.BlueprintError, "not committed"):
            bp.pin(self.root, self.doc, ARCH, set())

    def test_a_commit_that_is_not_here_is_said_plainly(self):
        self.doc["commit"] = "0123456789ab"
        with self.assertRaisesRegex(bp.BlueprintError, "re-verify the whole doc"):
            self.report()


def cli(root, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts/blueprint.py"), "--repo", str(root), *args], capture_output=True, text=True)


class NothingIsWrittenThroughALink(Repo):
    """A repository can ship a symlink where this tool is about to write."""

    def setUp(self):
        super().setUp()
        self.victim = self.root.parent / "victim"
        self.victim.write_text('{"keep": true}\n')

    def untouched(self):
        self.assertEqual(self.victim.read_text(), '{"keep": true}\n')

    def test_render_refuses_a_linked_page_or_markdown_copy(self):
        for suffix in (".html", ".md"):
            with self.subTest(suffix=suffix):
                link = (self.root / ARCH).with_suffix(suffix)
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(self.victim)
                out = cli(self.root, "render", ARCH, "--markdown")
                self.assertEqual(out.returncode, 2, out.stdout)
                self.assertIn("symlink", out.stderr)
                self.untouched()
                link.unlink()

    def test_a_link_that_stays_inside_the_repository_is_refused_too(self):
        hook = self.root / "run-me"
        hook.write_text("original\n")
        (self.root / ARCH).with_suffix(".md").symlink_to(hook)
        self.assertEqual(cli(self.root, "render", ARCH, "--markdown").returncode, 2)
        self.assertEqual(hook.read_text(), "original\n")

    def test_fragment_and_body_files_may_not_be_links(self):
        link = self.root.parent / "link"
        link.symlink_to(self.victim)
        for args in (("render", ARCH, "--fragment", str(link)), ("pr-body", "--base", "main", "--into", str(link))):
            with self.subTest(args=args):
                self.assertEqual(cli(self.root, *args).returncode, 2)
                self.untouched()

    def test_a_linked_config_or_config_folder_is_refused(self):
        (self.root / ".claude").mkdir()
        (self.root / bp.CONFIG).symlink_to(self.victim)
        with self.assertRaisesRegex(bp.BlueprintError, "symlink"):
            bp.set_docs_dir(self.root, "handbook", move=False)
        self.untouched()
        (self.root / bp.CONFIG).unlink()
        (self.root / ".claude").rmdir()
        (self.root / "real").mkdir()
        (self.root / ".claude").symlink_to(self.root / "real")
        with self.assertRaisesRegex(bp.BlueprintError, "symlink"):
            bp.set_docs_dir(self.root, "handbook", move=False)

    def test_a_linked_doc_is_neither_found_nor_opened(self):
        link = self.root / "docs/architecture/alias.json"
        link.symlink_to(self.root / ARCH)
        self.assertNotIn("docs/architecture/alias.json", bp.find_docs(self.root))
        self.assertEqual(cli(self.root, "render", "docs/architecture/alias.json").returncode, 2)

    def test_git_internals_are_out_of_reach_by_any_spelling(self):
        (self.root / "docs/g").symlink_to(self.root / ".git")
        for bad in (".GIT/config", ".Git/hooks", "docs/g/config"):
            with self.subTest(bad=bad):
                with self.assertRaises(bp.BlueprintError):
                    bp.inside(self.root, bad, "cite")

    def test_a_bare_repository_inside_the_project_runs_nothing(self):
        sub, marker = self.root / "sub", self.root.parent / "ran"
        subprocess.run(["git", "init", "-q", "--bare", str(sub)], check=True, capture_output=True)
        for key, value in (("core.bare", "false"), ("core.worktree", "."), ("core.fsmonitor", f"touch '{marker}'; false")):
            subprocess.run(["git", "config", "--file", str(sub / "config"), key, value], check=True)
        bp.find_docs(bp.repo_root(sub))
        self.assertFalse(marker.exists())


class HostileText(Repo):
    def test_check_commands_may_not_hide_characters(self):
        for hidden in ("echo ok ‮; rm x", "echo a\recho b", "echo ​x", "echo \x1b[2K"):
            with self.subTest(hidden=repr(hidden)):
                self.doc["checks"]["measures"][0]["command"] = hidden
                self.assertTrue(any("hidden" in e for e in bp.validate(self.doc)[0]))

    def test_the_command_code_is_the_whole_hash(self):
        self.assertEqual(len(bp.command_digest(self.doc)), 64)

    def test_python_checks_do_not_import_from_the_repository(self):
        self.doc["checks"] = {"measures": [{"id": "env", "command": "echo $PYTHONSAFEPATH", "value": "1"}]}
        self.assertEqual(bp.run_checks(self.root, self.doc)[0]["state"], "same")

    def test_malformed_docs_are_errors_not_crashes(self):
        def broken(change):
            doc = self.load(ARCH)
            change(doc)
            return bp.validate(doc)[0]

        table = lambda d: next(b for _, b in bp.blocks(d) if b["type"] == "table")
        for name, change in {
            "sections": lambda d: d.update(sections=[1]),
            "level": lambda d: d["sections"][0].update(level=10**10),
            "node title": lambda d: d["sections"][0]["blocks"][0]["nodes"][0].pop("title"),
            "columns": lambda d: table(d).pop("columns"),
            "caption": lambda d: d["sections"][0]["blocks"][0].update(caption="x"),
            "title": lambda d: d.update(title=5),
        }.items():
            with self.subTest(name=name):
                self.assertTrue(broken(change))

    def test_a_label_with_nothing_drawable_falls_back_to_an_id(self):
        block = {"id": "g", "nodes": [{"id": "a", "title": "[]"}], "edges": []}
        self.assertIn('n0["n0"]', "\n".join(bp.mermaid_graph(block)))
        lane = {"id": "s", "lanes": [{"id": "a", "title": "`"}], "steps": [{"id": "x", "lane": "a", "title": "go", "effect": "  "}]}
        drawn = "\n".join(bp.mermaid_swimlane(lane))
        self.assertIn("participant L0 as L0", drawn)
        self.assertNotIn("Note over", drawn)

    def test_a_code_block_cannot_close_its_own_fence(self):
        doc = {"title": "t", "sections": [{"id": "s", "blocks": [{"id": "c", "type": "code", "code": "a\n`````\n<b>"}]}]}
        self.assertIn("``````\na\n`````\n<b>\n``````", bp.render_markdown(doc))


class DocBesideItsCode(Repo):
    BESIDE = "api/shop.json"

    def setUp(self):
        super().setUp()
        shutil.move(self.root / ARCH, self.root / self.BESIDE)
        self.doc["sources"] = ["api", "docs"]
        bp.write_json(self.root / self.BESIDE, self.doc)
        (self.root / "api/shop.html").write_text("generated")

    def report(self):
        return bp.drift(self.root, self.doc, self.BESIDE)

    def test_the_tools_own_files_are_not_drift(self):
        self.assertEqual(self.report()["changedFiles"], 0)

    def test_code_in_the_docs_folder_is_still_watched(self):
        self.edit("api/queue.py", "print(topic, message)", "print(message)")
        (self.root / "api/new.py").write_text("x = 1\n")
        report = self.report()
        self.assertIn("layers/queue", report["flagged"])
        self.assertIn("api/new.py", report["uncoveredAdded"] + report["addedInCitedFolder"])
        with self.assertRaises(bp.BlueprintError):
            bp.pin(self.root, self.doc, self.BESIDE, set(report["flagged"]))

    def test_other_files_in_the_docs_directory_are_watched_too(self):
        (self.root / "docs/architecture/helper.py").write_text("x = 1\n")
        self.assertIn("docs/architecture/helper.py", self.report()["uncoveredAdded"])


class FirstPin(unittest.TestCase):
    def test_a_repository_with_no_commit_is_said_plainly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = (Path(folder) / "new").resolve()
            shutil.copytree(FIXTURE, root)
            git(root, "init", "-q")
            doc = json.loads((root / ARCH).read_text())
            doc["commit"] = ""
            with self.assertRaisesRegex(bp.BlueprintError, "no commit yet"):
                bp.pin(root, doc, ARCH, set())


class WholeBlocks(Repo):
    """Text and code blocks have no items, so a design changes them as a whole."""

    def design(self, *changes):
        design = self.load(DESIGN)
        design["sections"][0]["blocks"] += list(changes)
        return design

    def arch(self):
        arch = self.load(ARCH)
        arch["sections"][0]["blocks"] += [
            {"id": "note", "type": "text", "text": "old words"},
            {"id": "pattern", "type": "code", "code": "old()", "caption": {"takeaway": "t"}},
        ]
        return arch

    def merged(self):
        return bp.integrate(self.arch(), self.design(
            {"id": "note", "type": "text", "text": "new words", "status": "changed", "design": "order-cancel"},
            {"id": "pattern", "type": "code", "status": "removed", "design": "order-cancel", "caption": {"takeaway": "t"}},
        ))

    def found(self, doc):
        return {b["id"]: b for _, b in bp.blocks(doc)}

    def test_integrate_keeps_what_the_design_asked_for(self):
        found = self.found(self.merged())
        self.assertEqual((found["note"]["status"], found["note"]["text"]), ("changed", "new words"))
        self.assertEqual((found["pattern"]["status"], found["pattern"]["code"]), ("removed", "old()"))
        self.assertIn("**[CHANGED]**", bp.render_markdown(self.merged()))

    def test_drop_restores_and_built_applies(self):
        self.assertEqual(bp.resolve(self.merged(), "order-cancel", "drop"), self.arch())
        found = self.found(bp.resolve(self.merged(), "order-cancel", "built"))
        self.assertNotIn("pattern", found)
        self.assertEqual(found["note"]["text"], "new words")
        for gone in ("status", "was", "design"):
            self.assertNotIn(gone, found["note"])

    def test_a_block_with_items_is_changed_item_by_item(self):
        with self.assertRaisesRegex(bp.BlueprintError, "mark the items"):
            bp.integrate(self.arch(), self.design({"id": "layers", "type": "graph", "status": "changed", "design": "order-cancel",
                                                    "caption": {"takeaway": "t"}, "nodes": [], "edges": []}))

    def test_a_wholly_new_diagram_is_marked_new(self):
        block = {"id": "g", "status": "proposed", "design": "d", "nodes": [{"id": "a", "title": "Cancel"}, {"id": "b", "title": "Mail"}],
                 "edges": [{"from": "a", "to": "b"}]}
        drawn = "\n".join(bp.mermaid_graph(block))
        self.assertIn('"NEW: Cancel"]:::proposed', drawn)
        self.assertIn("-.->", drawn)
        lane = {"id": "s", "status": "proposed", "lanes": [{"id": "a", "title": "A"}], "steps": [{"id": "x", "lane": "a", "title": "go"}]}
        self.assertIn("NEW: go", "\n".join(bp.mermaid_swimlane(lane)))

    def test_a_built_design_is_no_longer_titled_proposed(self):
        design = self.load(DESIGN)
        for _, block in bp.blocks(design):
            block.pop("into", None)
        merged = bp.integrate(self.load(ARCH), design)
        self.assertTrue([s for s in merged["sections"] if s["title"].startswith("Proposed:")])
        built = bp.resolve(merged, "order-cancel", "built")
        self.assertFalse([s for s in built["sections"] if s["title"].startswith("Proposed:")])


class PageCheck(Repo):
    def test_a_browser_that_cannot_run_is_unchecked_not_passed_or_failed(self):
        page = self.root / "page.html"
        page.write_text(bp.render_html(self.doc))
        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_page.py"), str(page)],
            env={"LB_CHROME": "/usr/bin/false", "PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("unchecked", out.stdout)


class Rendering(Repo):
    def test_no_doc_string_can_close_the_script_element(self):
        doc = self.load(ARCH)
        doc["title"] = "</title><img src=x onerror=alert(1)>"
        doc["summary"] = "</script><script>alert(1)</script><!--"
        page = bp.render_html(doc)
        self.assertNotIn("<script>alert(1)", page)
        self.assertNotIn("<img src=x", page)
        payload = page.split('id="lb-data">')[1].split("</script>")[0]
        self.assertEqual(json.loads(payload)["summary"], doc["summary"])

    def test_the_page_builds_no_markup_from_strings(self):
        script = (ROOT / "scripts/page/page.js").read_text()
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(sink, script)

    def test_markdown_marks_proposals(self):
        text = bp.render_markdown(self.load(DESIGN))
        self.assertIn("**[PROPOSED]**", text)
        self.assertIn("```mermaid", text)


class PullRequest(Repo):
    """main holds the code and the architecture doc; the branch adds the design."""

    def setUp(self):
        super().setUp()
        bp.write_json(self.root / ARCH, self.doc)
        saved = (self.root / DESIGN).read_text()
        (self.root / DESIGN).unlink()
        git(self.root, "add", "docs")
        git(self.root, "commit", "-qm", "docs")
        git(self.root, "switch", "-qc", "feat/cancel")
        (self.root / DESIGN).parent.mkdir(parents=True, exist_ok=True)
        (self.root / DESIGN).write_text(saved)
        git(self.root, "add", "docs")
        git(self.root, "commit", "-qm", "design")

    def section(self):
        return bp.pr_section(self.root, "main")

    def commit_design(self, change):
        design = self.load(DESIGN)
        change(design)
        bp.write_json(self.root / DESIGN, design)
        git(self.root, "commit", "-qam", "edit design")

    def test_a_design_only_branch_carries_its_diagrams_as_mermaid(self):
        section = self.section()
        for expected in ("flowchart TB", "sequenceDiagram", "NEW: send_cancellation", "CHANGES: OrderService", "participant L2 as OrderService"):
            self.assertIn(expected, section)
        self.assertEqual(section.count("```mermaid"), 2)

    def test_code_alongside_the_design_changes_nothing_about_the_section(self):
        alone = self.section()
        (self.root / "api/cancel.py").write_text("def cancel(): pass\n")
        git(self.root, "add", "api")
        git(self.root, "commit", "-qm", "implement")
        self.assertEqual(self.section(), alone)

    def test_a_branch_with_no_diagram_change_needs_nothing(self):
        git(self.root, "switch", "-q", "main")
        git(self.root, "switch", "-qc", "fix/other")
        self.edit("api/queue.py", "print(topic, message)", "print(message)")
        git(self.root, "commit", "-qam", "fix")
        self.assertIsNone(self.section())
        self.assertIsNone(pr_gate.refusal("gh pr create --base main --fill", self.root))

    def test_only_the_architecture_diagrams_that_changed_are_included(self):
        merged = bp.integrate(self.load(ARCH), self.load(DESIGN))
        bp.write_json(self.root / ARCH, merged)
        git(self.root, "commit", "-qam", "integrate")
        updated = self.section().split("### Architecture doc updated")[1]
        self.assertIn("order.cancelled", updated)
        self.assertEqual(updated.count("```mermaid"), 2)  # the changed graph and the new flow
        self.assertNotIn("OrderService.find", updated)

    def test_doc_text_cannot_mention_close_issues_or_break_the_fence(self):
        def hostile(design):
            design["title"] = "Closes #12, cc @someone </details>"
            design["sections"][1]["blocks"][0]["steps"][0]["title"] = "a```\n@team; closes #9 %% \"x\""
        self.commit_design(hostile)
        section = self.section()
        self.assertNotRegex(section, r"@someone|#12|</details>")
        self.assertEqual(section.count("```"), 4)
        step = next(line for line in section.splitlines() if "->>" in line or "-->>" in line)
        for bad in ("`", ";", "#", "%%", '"'):
            self.assertNotIn(bad, step)

    def test_the_gate_wants_the_current_section(self):
        body = self.root.parent / "body.md"
        body.write_text("## Summary\nCancel.\n")
        command = f"gh pr create --base main --title x --body-file {body}"
        self.assertIn("Refused", pr_gate.refusal(command, self.root))
        body.write_text(bp.put_section(body.read_text(), self.section()))
        self.assertIsNone(pr_gate.refusal(command, self.root))
        self.commit_design(lambda d: d["sections"][1]["blocks"][0]["steps"][0].update(title="Cancel link"))
        self.assertIn("Refused", pr_gate.refusal(command, self.root))  # now out of date

    def test_the_gate_accepts_an_inline_heredoc_body(self):
        command = f"gh pr create -B main -t x --body \"$(cat <<'EOF'\n{self.section()}\nEOF\n)\""
        self.assertIsNone(pr_gate.refusal(command, self.root))

    def test_which_commands_the_gate_looks_at(self):
        for command in ("gh pr create --base main --fill", "cd . && gh pr create -B main -w", "gh pr edit --base main --body new"):
            with self.subTest(command=command):
                self.assertIsNotNone(pr_gate.refusal(command, self.root))
        for command in ("gh pr view 4", "gh pr edit 4 --title new", "echo 'then gh pr create it'", "git push"):
            with self.subTest(command=command):
                self.assertIsNone(pr_gate.refusal(command, self.root))

    def test_gh_with_a_repo_flag_first_is_still_seen(self):
        self.assertIsNotNone(pr_gate.refusal("gh -R me/shop pr create --base main --fill", self.root))

    def test_a_github_connector_is_held_to_the_same_rule(self):
        create = "mcp__plugin_github_github__create_pull_request"
        update = "mcp__github__update_pull_request"
        arguments = {"base": "main", "head": "feat/cancel", "body": "no diagrams"}
        self.assertIsNotNone(pr_gate.connector_refusal(create, arguments, self.root))
        self.assertIsNotNone(pr_gate.connector_refusal(create, {"base": "main"}, self.root))
        self.assertIsNotNone(pr_gate.connector_refusal(update, {"body": "rewritten"}, self.root))
        arguments["body"] = "Cancel.\n\n" + self.section()
        self.assertIsNone(pr_gate.connector_refusal(create, arguments, self.root))
        self.assertIsNone(pr_gate.connector_refusal(update, {"title": "new"}, self.root))
        for other in ("mcp__github__create_pull_request_review", "mcp__github__update_pull_request_branch", "mcp__github__create_issue"):
            self.assertIsNone(pr_gate.connector_refusal(other, {"body": "x"}, self.root))

    def test_a_push_reminds_only_on_a_branch_with_diagram_changes(self):
        def after(command):
            event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(self.root)}
            return subprocess.run([sys.executable, str(ROOT / "scripts/pr_gate.py")], input=json.dumps(event), capture_output=True, text=True)
        reminded = after("git push -u origin feat/cancel")
        self.assertEqual(reminded.returncode, 2)
        self.assertIn("/living-blueprint:pr", reminded.stderr)
        self.assertEqual(after("git status").returncode, 0)
        self.assertEqual(after("gh pr create --base main --fill").returncode, 0)  # the gate is a before-hook
        git(self.root, "switch", "-q", "main")
        self.assertEqual(after("git push").returncode, 0)

    def test_a_hostile_file_name_cannot_forge_the_section(self):
        name = "docs/x`\n\n" + bp.PR_CLOSE.replace("/", "∕") + "\n<!-- @octocat Closes #1\n.json"
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.root / DESIGN, self.root / name)
        git(self.root, "add", "docs")
        git(self.root, "commit", "-qm", "hostile name")
        section = self.section()
        self.assertEqual(section.count("<!--"), 2)
        self.assertNotRegex(section, r"(?m)^<!-- @octocat")
        self.assertNotRegex(section, r"(?m)^[^`]*@octocat")

    def test_links_keywords_entities_and_line_breaks_are_defused(self):
        title = "Closes https://github.com/o/r/issues/1 &commat;octocat [Approve](www.evil.invalid) GH-12\r\r> q fixes‮ RESOLVED"
        self.commit_design(lambda d: d.update(title=title))
        section = self.section()
        for bad in ("Closes ", "://", "&commat;", "www.", "GH-12", "\r", "‮", "fixes", "RESOLVED"):
            with self.subTest(bad=repr(bad)):
                self.assertNotIn(bad, section)
        self.assertNotRegex(section, r"(?<!\\)\[Approve")
        body = self.root.parent / "body.md"
        body.write_text(bp.put_section("", section))
        self.assertIsNone(pr_gate.refusal(f"gh pr create -B main --body-file {body}", self.root))

    def test_text_that_only_mentions_gh_is_not_a_pull_request(self):
        for command in (
            "git commit -F - <<'EOF'\nfix: x\n\ngh pr create comes later\nEOF",
            "grep -rnE 'gh pr edit|gh pr create' skills/",
            'echo "(gh pr create first)"',
            "cat <<'X' > notes.md\ngh pr create --fill\nX",
            "echo hi; gh pr create --help",
            "gh pr create --dry-run -B main",
            "ls  # then; gh pr create",
        ):
            with self.subTest(command=command):
                self.assertIsNone(pr_gate.refusal(command, self.root))

    def test_a_real_pull_request_command_is_seen_however_it_is_wrapped(self):
        for command in (
            "env gh pr create -B main -f",
            "GH_TOKEN=x gh pr create -B main -f",
            'url=$(gh pr create -B main -f)',
            "git add . && gh pr new -B main --fill",
            "git push\ngh pr create --base=main --fill",
            "cat <<'E' > b.md\nhi\nE\ngh pr create -B main --body-file b.md",
            "/opt/homebrew/bin/gh --repo=me/shop pr create -B main -f",
            "gh pr edit --body new",
        ):
            with self.subTest(command=command):
                self.assertIsNotNone(pr_gate.refusal(command, self.root))

    def test_an_edit_is_checked_only_when_its_branch_is_known(self):
        self.assertIsNone(pr_gate.refusal("gh pr edit 12 --base main --body new", self.root))
        self.assertIsNone(pr_gate.refusal("gh pr edit https://github.com/o/r/pull/3 --body new", self.root))
        git(self.root, "switch", "-q", "main")
        self.assertIsNotNone(pr_gate.refusal("gh pr edit feat/cancel --base main --body new", self.root))

    def test_a_broken_doc_stops_the_pull_request_instead_of_vanishing(self):
        body_command = "gh pr create -B main --fill"
        self.commit_design(lambda d: d["sections"][1]["blocks"][0]["caption"].pop("takeaway"))
        with self.assertRaisesRegex(bp.BlueprintError, "takeaway"):
            self.section()
        self.assertIn("takeaway", pr_gate.refusal(body_command, self.root))
        self.assertIn("takeaway", pr_gate.connector_refusal("mcp__github__create_pull_request", {"base": "main"}, self.root))
        (self.root / DESIGN).write_text('{"livingBlueprint": 1,,}')
        git(self.root, "commit", "-qam", "break")
        self.assertIn("not valid JSON", pr_gate.refusal(body_command, self.root))

    def test_a_push_with_a_broken_doc_says_so(self):
        self.commit_design(lambda d: d["sections"][1]["blocks"][0]["caption"].pop("takeaway"))
        self.assertIn("takeaway", pr_gate.push_reminder("git push", self.root))
        self.assertIn("takeaway", pr_gate.push_reminder(f"git -C '{self.root}' push", self.root.parent))

    def test_other_json_files_are_not_read_one_by_one(self):
        for number in range(40):
            (self.root / f"data{number}.json").write_text("{}")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "data")
        with mock.patch.object(bp, "git_text", wraps=bp.git_text) as spy:
            self.section()
        self.assertEqual([c for c in spy.call_args_list if "show" in c.args and "data1.json" in str(c.args)], [])

    def test_the_hook_matcher_covers_connector_spellings(self):
        matcher = json.loads((ROOT / "hooks/hooks.json").read_text())["hooks"]["PreToolUse"][0]["matcher"]
        for tool in ("Bash", "mcp__claude_ai_GitHub__create_pull_request", "mcp__plugin_github_github__create_pull_request"):
            self.assertRegex(tool, f"^(?:{matcher})$")
        self.assertIsNone(pr_gate.connector_refusal("mcp__github__create_pull_request_with_copilot", {}, self.root))

    def test_updating_a_body_replaces_the_old_section_only(self):
        first = bp.put_section("intro\n", self.section()) + "## After\nkept\n"
        self.commit_design(lambda d: d["sections"][1]["blocks"][0]["steps"][0].update(title="Cancel link"))
        second = bp.put_section(first, self.section())
        self.assertEqual(second.count(bp.PR_CLOSE), 1)
        for kept in ("intro", "## After\nkept", "Cancel link"):
            self.assertIn(kept, second)

    def test_the_hook_blocks_with_exit_2_and_allows_when_it_cannot_tell(self):
        def hook(command, cwd):
            event = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})
            return subprocess.run([sys.executable, str(ROOT / "scripts/pr_gate.py")], input=event, capture_output=True, text=True)
        self.assertEqual(hook("gh pr create --base main --fill", self.root).returncode, 2)
        outside = hook("gh pr create --fill", self.root.parent)
        self.assertEqual(outside.returncode, 0)
        self.assertIn("skipped", outside.stderr)
        self.assertEqual(hook("ls", self.root).returncode, 0)


if __name__ == "__main__":
    unittest.main()
