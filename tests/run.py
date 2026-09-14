#!/usr/bin/env python3
"""Small dependency-free regression suite for the collector and dashboard."""
import argparse
import ast
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace


# server.py chooses its cache location while it is imported.
TEST_HOME = tempfile.mkdtemp(prefix="claude-usage-tests-")
os.environ["USERPROFILE"] = TEST_HOME
os.environ["HOME"] = TEST_HOME
os.environ["CODEX_HOME"] = os.path.join(TEST_HOME, "dot-codex")
ROOT = Path(__file__).resolve().parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def syntax_check():
    paths = [ROOT / "claude-usage.py", ROOT / "src" / "collect.py", ROOT / "src" / "merge.py"]
    if sys.version_info[:2] == (3, 6):
        for path in paths:
            py_compile.compile(str(path), doraise=True)
        return "3.6 compile"
    for path in paths:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 6))
    return "best-effort 3.6 AST"


def names_units():
    collect = load("names_collect", ROOT / "src" / "collect.py")
    root = Path(tempfile.mkdtemp(prefix="names-", dir=TEST_HOME))

    def mk(dirname, files):
        folder = root / dirname
        folder.mkdir()
        for name, rows in files.items():
            write_jsonl(folder / name, rows)

    a = "ssh-1bdbfb89-5eec-4c86-a159-7cecce4e94f9"
    b = "ssh-0cdc618f-cfd6-406a-a1b6-3f1de7ef486d"
    c = "ssh-5914ea90-61c4-404b-8832-ed306450e669"
    d = "ssh-96496501-f296-43f3-b2d6-c013090ceaa2"
    mk(a, {"a.jsonl": [{"type": "summary"}, {"cwd": "/usr/service/bookapp/reels"}],
           "b.jsonl": [{"cwd": "/usr/service/bookapp"}]})
    mk(b, {"a.jsonl": [{"cwd": "/usr/service/bookapp/.claude/worktrees/affectionate-wright-7f1e3b"}]})
    mk(c, {"a.jsonl": [{"cwd": "C:\\Users\\alice\\work\\myproj"}]})
    mk(d, {"a.jsonl": [{"type": "summary"}]})
    mk("D--Claude-new-blog-app", {"a.jsonl": [{"cwd": "D:\\Claude\\new_blog_app"}]})
    mk("D--Claude---app", {"a.jsonl": [{"cwd": "D:\\Claude\\구독app"}]})
    mk("D--Claude-claude-usage", {"a.jsonl": [{"cwd": "D:\\Claude\\claude-usage\\src"}],
                                    "b.jsonl": [{"cwd": "D:\\Claude\\claude-usage"}]})
    cases = {a: "bookapp", b: "bookapp", c: "myproj", d: "c013090ceaa2",
             "D--Claude-new-blog-app": "new_blog_app", "D--Claude---app": "구독app",
             "D--Claude-claude-usage": "claude-usage", "-home-alice-work-myapp": "myapp"}
    for dirname, want in cases.items():
        got = collect.project_name(root, dirname)
        assert got == want, (dirname, got, want)
    units = [(0, "0"), (995, "995"), (999, "999"), (999.6, "1천"), (1000, "1천"),
             (4380, "4.38천"), (9996, "1만"), (100000, "10만"), (438514, "43.9만"),
             (5000000, "500만"), (11734555, "1,173만"), (55296268, "5,530만"),
             (578143623, "5.78억"), (26968689307, "270억"), (1.2e12, "1.2조"),
             (12345678901234, "12.3조"), (None, "0")]
    for number, want in units:
        got = collect.human(number)
        assert got == want, (number, got, want)
    assert collect.parse_ts("2026-09-14T00:00:00+99:99") is None
    assert collect.parse_ts("2026-09-14T00:00:00+09:00").utcoffset() == timedelta(hours=9)
    return "8 project_name + 17 human + parse_ts offset"


def fixture():
    collect = load("fixture_collect", ROOT / "src" / "collect.py")
    server = load("fixture_server", ROOT / "claude-usage.py")
    case = Path(tempfile.mkdtemp(prefix="fixture-", dir=TEST_HOME))
    claude, projects = case / "dot-claude", case / "dot-claude" / "projects"
    projects.mkdir(parents=True)
    today = datetime.now().astimezone().date()
    tz = datetime.now().astimezone().tzinfo

    def stamp(days, hour, minute, second=0):
        return datetime.combine(today + timedelta(days=days), time(hour, minute, second)).replace(tzinfo=tz).isoformat()

    def record(ts, session, mid, request, ctx, sidechain=False):
        value = {"timestamp": ts, "requestId": request, "isSidechain": sidechain,
                 "message": {"id": mid, "model": "claude-sonnet-4", "usage": {
                     "input_tokens": ctx[0], "output_tokens": 7,
                     "cache_creation_input_tokens": ctx[1], "cache_read_input_tokens": ctx[2]}}}
        if session is not None:
            value["sessionId"] = session
        return value

    alpha, beta = projects / "-tmp-alpha", projects / "-tmp-beta"
    a1 = record(stamp(0, 10, 0), "alpha-new", "msg-a1", "req-a1", (10, 20, 30))
    a2 = record(stamp(0, 13, 59, 1), "alpha-new", "msg-a2", "req-a2", (100, 200, 300))
    write_jsonl(alpha / "a-main.jsonl", [a1, a2])
    write_jsonl(alpha / "b-resumed.jsonl", [a2])
    write_jsonl(alpha / "c-older.jsonl", [record(stamp(-1, 12, 30), "alpha-older", "msg-b1", "req-b1", (300, 300, 300))])
    write_jsonl(alpha / "fallback.jsonl", [record(stamp(-4, 8, 0), None, "msg-c1", "req-c1", (400, 400, 400)),
                                              record(stamp(-4, 9, 0), None, "msg-c2", "req-c2", (500, 500, 500))])
    write_jsonl(alpha / "side.jsonl", [record(stamp(0, 14, 30), "side", "msg-side", "req-side", (999, 999, 999), True)])
    write_jsonl(alpha / "subagents" / "worker.jsonl", [record(stamp(0, 14, 40), "subagent", "msg-sub", "req-sub", (888, 888, 888))])
    write_jsonl(alpha / "old.jsonl", [record(stamp(-10, 9, 0), "old", "msg-old", "req-old", (777, 777, 777))])
    write_jsonl(beta / "main.jsonl", [record(stamp(-2, 17, 15), "beta-main", "msg-d1", "req-d1", (11, 22, 33))])
    args = SimpleNamespace(claude_dir=str(claude), since=None, until=None, verbose=False,
                           pricing=None, machine="fixture-machine")
    expected = {"alpha": [{"last": a2["timestamp"], "ctx": 600, "m": 2},
                          {"last": stamp(-1, 12, 30), "ctx": 900, "m": 1},
                          {"last": stamp(-4, 9, 0), "ctx": 1500, "m": 2}],
                "beta": [{"last": stamp(-2, 17, 15), "ctx": 66, "m": 1}]}
    full, incremental = collect.build_payload(args), server.build_payload_incremental(args)
    assert full.get("recent_sessions") == expected
    assert incremental.get("recent_sessions") == expected
    strip = lambda payload: dict((key, value) for key, value in payload.items() if key not in ("generated_at", "source"))
    assert strip(full) == strip(incremental)
    serialized = json.dumps(full["recent_sessions"])
    for forbidden in ("alpha-new", "alpha-older", "beta-main", "fallback.jsonl", "subagents", str(case)):
        assert forbidden not in serialized
    extra = (19, 23, 29)
    with (alpha / "a-main.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record(stamp(0, 15, 0), "alpha-new", "msg-extra", "req-extra", extra)) + "\n")
    grown = server.build_payload_incremental(args)
    for key, amount in zip(("i", "o", "cw", "cr"), (extra[0], 7, extra[1], extra[2])):
        assert grown["totals"][key] - incremental["totals"][key] == amount, key

    def appending_scan(scan_args):             # 스캔 도중 기록이 붙는 경우
        with (beta / "main.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record(stamp(0, 16, 0), "beta-main", "msg-mid", "req-mid", extra)) + "\n")
        return {}
    server.scan_local = appending_scan
    server._do_scan(args)
    assert server._scan["fp"] != server._fingerprint(projects), "mid-scan append must trigger a rescan"
    return "full = incremental; one-record growth; mid-scan append"


def merge_check():
    merge = load("merge_check", ROOT / "src" / "merge.py")
    entries = [{"last": "2026-09-%02dT12:00:00+09:00" % day, "ctx": day * 1000, "m": day}
               for day in (9, 14, 10, 13, 11, 12)]
    base = {"schema": 2, "machine": {"id": "a", "label": "machine-a"}, "totals": {}, "daily": {},
            "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "recent_sessions": {"project": entries}}
    old = {"schema": 2, "machine": {"id": "b", "label": "machine-b"}, "totals": {}, "daily": {},
           "models": {}, "projects": {}, "hours": [], "weekday_hour": []}
    out = merge.merge([merge.normalize_machine(base), merge.normalize_machine(old)])
    assert all(m.get("schema") in (1, 2) and m["machine"]["id"] for m in out["machines"])   # dashboard ingest() 계약
    kept = out["recent_sessions"]["project"]
    assert [entry["last"][8:10] for entry in kept] == ["14", "13", "12", "11", "10"]
    assert all(entry["machine"] == "machine-a" for entry in kept)
    assert "recent_sessions" not in old
    first = {"schema": 2, "machine": {"id": "c", "label": "c"}, "totals": {}, "daily": {}, "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "hourly": {"2026-09-14T10": {"i": 1, "o": 2}}}
    second = {"schema": 2, "machine": {"id": "d", "label": "d"}, "totals": {}, "daily": {}, "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "hourly": {"2026-09-14T10": {"i": 3, "o": 4, "cw": 5}}}
    hourly = merge.merge([merge.normalize_machine(first), merge.normalize_machine(second)])["hourly"]["2026-09-14T10"]
    assert hourly["i"] == 4 and hourly["o"] == 6 and hourly["cw"] == 5
    return "recent top-5 + hourly sum"


def js_check(no_js):
    if no_js:
        return None, "--no-js"
    node = shutil.which("node")
    if not node:
        return None, "node not found"
    for zone in ("Asia/Seoul", "UTC", "America/Los_Angeles", "Pacific/Kiritimati"):
        env = os.environ.copy()
        env["TZ"] = zone
        process = subprocess.Popen([node, str(ROOT / "tests" / "dashboard.test.js")], cwd=str(ROOT), env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                                   encoding="utf-8")
        output = process.communicate()[0]
        if process.returncode != 0 or zone + " OK" not in output:
            raise AssertionError("%s:\n%s" % (zone, output))
    return "4 timezones", None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-js", action="store_true")
    options = parser.parse_args()
    checks = [("syntax", syntax_check), ("names_units", names_units), ("fixture", fixture), ("merge", merge_check)]
    failed = 0
    try:
        for label, check in checks:
            try:
                print("PASS %s: %s" % (label, check()))
            except BaseException as error:
                failed += 1
                print("FAIL %s: %s" % (label, error))
        try:
            result, skipped = js_check(options.no_js)
            print("%s js: %s" % ("SKIP" if skipped else "PASS", skipped or result))
        except BaseException as error:
            failed += 1
            print("FAIL js: %s" % error)
        print("SUMMARY: %d failed" % failed)
        return 1 if failed else 0
    finally:
        shutil.rmtree(TEST_HOME, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
