#!/usr/bin/env python3
"""Render a generated page headlessly at desktop and phone widths and report what is broken.

Exit 0: every width checked and clean. 1: failures. 2: something could not be checked, which is
never to be reported as a pass.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PAGE_DIR = Path(__file__).resolve().parent / "page"
WIDTHS = (1280, 390)
CAPTURE = (
    "<script>window.__errors=[];window.onerror=function(m,s,l,c){__errors.push(m+' @'+l+':'+c)};"
    "console.error=function(){__errors.push([].join.call(arguments,' '))};</script>"
)
CHROMES = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def instrument(page: str) -> str:
    check = (PAGE_DIR / "check.js").read_text(encoding="utf-8")
    if "<head>" not in page or "</body>" not in page:
        raise SystemExit("check_page: expected a full page, not a --fragment")
    page = page.replace("<head>", "<head>" + CAPTURE, 1)
    head, _, tail = page.rpartition("</body>")
    return f"{head}<script>\n{check}</script>\n</body>{tail}"


def find_chrome() -> str | None:
    wanted = os.environ.get("LB_CHROME")
    for name in ([wanted] if wanted else []) + list(CHROMES):
        found = shutil.which(name) or (name if os.path.isfile(name) else None)
        if found:
            return found
    return None


def run_chrome(chrome: str, page: Path, width: int) -> str | None:
    try:
        out = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--dump-dom", f"--window-size={width},900",
             "--virtual-time-budget=8000", page.as_uri()],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r'<pre id="lb-check"[^>]*>([A-Za-z0-9+/=]+)</pre>', out.stdout)
    return found.group(1) if found else None


def build_webkit(work: Path) -> Path | None:
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    binary = work / "webkit_check"
    built = subprocess.run(["swiftc", "-o", str(binary), str(PAGE_DIR / "webkit_check.swift")], capture_output=True, text=True, timeout=300)
    return binary if built.returncode == 0 else None


def run_webkit(binary: Path, page: Path, width: int) -> str | None:
    try:
        out = subprocess.run([str(binary), str(page), str(width)], capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: check_page.py <page.html>", file=sys.stderr)
        return 2
    source = Path(argv[0]).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        page = work / "page.html"
        page.write_text(instrument(source), encoding="utf-8")
        chrome = find_chrome()
        webkit = None if chrome else build_webkit(work)
        if not chrome and not webkit:
            print(json.dumps({"state": "unchecked", "reason": "no Chrome, Chromium or Edge, and no macOS swiftc. Set LB_CHROME to a browser."}))
            return 2
        report = {"engine": "chromium" if chrome else "webkit", "widths": {}}
        # A browser that is installed but cannot run here (a sandbox, no display) has checked
        # nothing. Prove the engine on a trivial page, so that is not reported as a broken doc.
        probe = work / "probe.html"
        probe.write_text('<!doctype html><html><head></head><body><pre id="lb-check">b2s=</pre></body></html>', encoding="utf-8")
        if (run_chrome(chrome, probe, 1280) if chrome else run_webkit(webkit, probe, 1280)) != "b2s=":
            print(json.dumps({"state": "unchecked", "reason": f"the {report['engine']} browser could not run here"}))
            return 2
        worst = 0
        for width in WIDTHS:
            raw = run_chrome(chrome, page, width) if chrome else run_webkit(webkit, page, width)
            if not raw:
                report["widths"][width] = {"state": "failed", "failures": ["no result: the page or the check did not run"]}
                worst = 1
                continue
            result = json.loads(base64.b64decode(raw))
            if result["failures"]:
                result["state"], worst = "failed", 1
            elif abs(result["width"] - width) > 40:
                # Headless browsers may enforce a minimum window width.
                result["state"] = f"unchecked: browser rendered {result['width']}px, not {width}px"
                worst = worst or 2
            else:
                result["state"] = "passed"
            report["widths"][width] = result
        print(json.dumps(report, indent=2))
        return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
