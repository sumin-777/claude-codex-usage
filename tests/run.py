#!/usr/bin/env python3
"""Small dependency-free regression suite for the collector and dashboard."""
import argparse
import ast
import importlib.util
import io
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta
from contextlib import redirect_stdout
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


def statusline_check():
    server = load("statusline_server", ROOT / "claude-usage.py")
    # 하네스가 import 전에 HOME 을 TEST_HOME 으로 바꿔 두어, 쓰는 쪽·읽는 쪽이 함께 보는 경로가 TEST_HOME 아래다.
    path = server.CLAUDE_LIMITS_FILE
    assert str(path).startswith(TEST_HOME), path
    try:
        return _statusline_cases(server, path)
    finally:
        if path.exists():
            path.unlink()


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True

    def read(self, *args):
        raise AssertionError("터미널 stdin 을 읽으려 했다 (입력을 기다리며 멈춘다)")


def _statusline_cases(server, path):
    def run(raw, stdin_type=io.StringIO):
        previous = server._sys.stdin
        output = io.BytesIO()
        wrapper = io.TextIOWrapper(output, encoding="utf-8")
        try:
            server._sys.stdin = stdin_type(raw)
            with redirect_stdout(wrapper):
                server.do_statusline()
            wrapper.flush()
        finally:
            server._sys.stdin = previous
        return output.getvalue().decode("utf-8").strip()

    # 손으로 실행(터미널 stdin)하면 읽지 않고 안내만 한다
    assert "상태줄" in run("", _TtyStdin)
    assert not path.exists()
    for raw in ("", "{broken", "{}"):
        if path.exists():
            path.unlink()
        assert run(raw) == "Claude 한도 -"
        assert not path.exists()
    sample = {"rate_limits": {
        "five_hour": {"used_percentage": 65, "resets_at": 1789642200, "ignored": "x"},
        "seven_day": {"used_percentage": 64, "resets_at": 1789711200},
        "other": {"used_percentage": 99, "resets_at": 1}}}
    assert run(json.dumps(sample)) == "Claude 5시간 65% · 주간 64%"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert set(saved) == {"recorded_at", "five_hour", "seven_day"}
    assert saved["five_hour"] == {"used_percentage": 65, "resets_at": 1789642200}
    assert saved["seven_day"] == {"used_percentage": 64, "resets_at": 1789711200}
    assert datetime.strptime(saved["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
    # 한도를 넘긴 값(100 초과)도 기록한다 ― 버리면 옛 값이 '실제'로 남는다
    over = {"rate_limits": {"seven_day": {"used_percentage": 105, "resets_at": 1789711200}}}
    assert run(json.dumps(over)) == "Claude 주간 105%"
    assert json.loads(path.read_text(encoding="utf-8"))["seven_day"]["used_percentage"] == 105

    # 상태줄 출력은 콘솔 인코딩이 아니라 UTF-8 이어야 한다 (cp949 로 내보내면 Claude Code 화면에서 깨진다).
    # 하위 프로세스는 하네스가 바꿔 둔 HOME(TEST_HOME)을 그대로 물려받는다.
    proc = subprocess.run([sys.executable, str(ROOT / "claude-usage.py"), "--statusline"],
                          input=json.dumps(sample).encode("utf-8"), stdout=subprocess.PIPE)
    assert proc.stdout.decode("utf-8").strip() == "Claude 5시간 65% · 주간 64%", proc.stdout
    return "tty 안내 + valid write + 3 quiet invalid + 100 초과 + UTF-8 stdout"


def codex_limits_check():
    """한도에 걸린 순간의 빈 보고가 마지막 한도 값을 지우면 안 된다 (미터가 통째로 사라진다)."""
    collect = load("codex_limits_collect", ROOT / "src" / "collect.py")
    path = Path(tempfile.mkdtemp(prefix="codex-", dir=TEST_HOME)) / "rollout.jsonl"

    # 한도에 걸린 순간의 진짜 기록은 info 가 dict 이고 rate_limits 의 primary/secondary 만 null 이다
    # (2026-09-18 실측). info 를 None 으로 두면 앞 조건에서 걸러져 이 경로를 못 밟는다.
    usage = {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5, "total_tokens": 15}

    def report(ts, limits, tokens):
        info = {"total_token_usage": dict(usage, total_tokens=tokens),
                "last_token_usage": usage}
        return {"timestamp": ts, "type": "event_msg",
                "payload": {"type": "token_count", "info": info, "rate_limits": limits}}

    full = {"primary": {"used_percent": 90.0, "window_minutes": 300, "resets_at": 1789700000},
            "secondary": {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 1790000000},
            "plan_type": "plus"}
    write_jsonl(path, [report("2026-09-18T01:00:00.000Z", full, 15),
                       report("2026-09-18T01:05:00.000Z",
                              {"limit_id": "premium", "primary": None, "secondary": None,
                               "plan_type": None}, 30)])
    _, _, limits, _ = collect.parse_codex_file(path)
    assert limits, "빈 보고가 마지막 한도 값을 지웠다"
    assert [w["used_percent"] for w in limits["windows"]] == [90.0, 40.0], limits
    assert limits["plan"] == "plus", limits

    # 빈 보고만 있는 파일은 한도를 만들지 않는다.
    only_empty = Path(str(path) + ".empty")
    write_jsonl(only_empty, [report("2026-09-18T02:00:00.000Z",
                                    {"primary": None, "secondary": None}, 15)])
    _, _, none_limits, _ = collect.parse_codex_file(only_empty)
    assert none_limits is None, none_limits

    # 옛 수집기가 보낸 빈 한도(창 없음)는 받는 쪽 정규화에서 뺀다 ― 서버(save_snapshot/load_remote)와 merge.py 둘 다.
    merge = load("codex_limits_merge", ROOT / "src" / "merge.py")

    def remote(windows):
        return {"codex": {"daily": {}, "totals": {},
                          "limits": {"at": "2026-09-18T09:00:00.000Z", "plan": "plus", "windows": windows}}}

    for normalize in (collect.normalize_payload_usage, merge.normalize_machine):
        empty = normalize(remote([]))
        assert "limits" not in empty["codex"], (normalize.__name__, empty)
        assert "daily" in empty["codex"], empty
        kept = normalize(remote(limits["windows"]))
        assert kept["codex"]["limits"]["windows"] == limits["windows"], (normalize.__name__, kept)

    # Claude 한도도 100 초과를 버리지 않는다 (collect 쪽은 statusline 검사가 본다)
    over = merge.normalize_claude_limits({"recorded_at": "2026-09-17T01:02:03+00:00",
                                          "seven_day": {"used_percentage": 105, "resets_at": 1789711200}})
    assert over and over["seven_day"]["used_percentage"] == 105, over
    return "빈 한도 보고 무시 (파일·받는 쪽 정규화) + merge 100 초과"


def response_limits_check():
    """claude_limits 는 재스캔을 기다리지 않고 응답할 때마다 새로 붙는다 (재스캔은 트랜스크립트가 바뀔 때만 돈다)."""
    server = load("response_server", ROOT / "claude-usage.py")
    cached = {"machine": {"id": "local", "label": "local"}, "totals": {}}
    with server._scan_lock:
        # busy 로 두면 collect_all 이 재스캔을 시작하지 않는다 (started=0 이면 경과 시간도 계산하지 않는다)
        server._scan.update(payload=cached, busy=True, at=0.0, fp=None, started=0.0, secs=0.0)
    args = SimpleNamespace(claude_dir=str(Path(TEST_HOME) / "no-claude"))
    path = server.CLAUDE_LIMITS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"recorded_at": "2026-09-22T01:00:00+00:00",
                                    "seven_day": {"used_percentage": 40, "resets_at": 1790000000}}), encoding="utf-8")
        first = server.collect_all(args)["machines"][0]
        assert first["claude_limits"]["seven_day"]["used_percentage"] == 40, first
        path.write_text(json.dumps({"recorded_at": "2026-09-22T01:05:00+00:00",
                                    "seven_day": {"used_percentage": 41, "resets_at": 1790000000}}), encoding="utf-8")
        second = server.collect_all(args)["machines"][0]
        assert second["claude_limits"]["seven_day"]["used_percentage"] == 41, second
        assert "claude_limits" not in cached, "스캔 결과 객체를 고쳐 썼다"
    finally:
        if path.exists():
            path.unlink()
        with server._scan_lock:
            server._scan.update(payload=None, busy=False)
    return "응답마다 새 값 + 스캔 결과 보존"


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
    assert "claude_limits" not in full and "claude_limits" not in incremental
    assert full.get("recent_sessions") == expected
    assert incremental.get("recent_sessions") == expected
    strip = lambda payload: dict((key, value) for key, value in payload.items() if key not in ("generated_at", "source"))
    assert strip(full) == strip(incremental)
    limits = {"recorded_at": "2026-09-17T01:02:03+00:00",
              "five_hour": {"used_percentage": 65, "resets_at": 1789642200},
              "seven_day": {"used_percentage": 64, "resets_at": 1789711200}}
    server.CLAUDE_LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
    server.CLAUDE_LIMITS_FILE.write_text(json.dumps(limits), encoding="utf-8")
    full_limits, incremental_limits = collect.build_payload(args), server.build_payload_incremental(args)
    assert full_limits.get("claude_limits") == limits
    assert incremental_limits.get("claude_limits") == limits
    assert strip(full_limits) == strip(incremental_limits)
    server.CLAUDE_LIMITS_FILE.unlink()
    assert "claude_limits" not in collect.build_payload(args)
    assert "claude_limits" not in server.build_payload_incremental(args)
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
    return "full = incremental with/without limits; one-record growth; mid-scan append"


def merge_check():
    merge = load("merge_check", ROOT / "src" / "merge.py")
    entries = [{"last": "2026-09-%02dT12:00:00+09:00" % day, "ctx": day * 1000, "m": day}
               for day in (9, 14, 10, 13, 11, 12)]
    base = {"schema": 2, "machine": {"id": "a", "label": "machine-a"}, "totals": {}, "daily": {},
            "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "recent_sessions": {"project": entries},
            "claude_limits": {"recorded_at": "2026-09-17T02:00:00+00:00",
                              "seven_day": {"used_percentage": 64, "resets_at": 1789711200}}}
    old = {"schema": 2, "machine": {"id": "b", "label": "machine-b"}, "totals": {}, "daily": {},
           "models": {}, "projects": {}, "hours": [], "weekday_hour": [],
           "claude_limits": {"recorded_at": "2026-09-17T01:00:00+00:00",
                             "seven_day": {"used_percentage": 60, "resets_at": 1789711200}}}
    out = merge.merge([merge.normalize_machine(base), merge.normalize_machine(old)])
    assert all(m.get("schema") in (1, 2) and m["machine"]["id"] for m in out["machines"])   # dashboard ingest() 계약
    kept = out["recent_sessions"]["project"]
    assert [entry["last"][8:10] for entry in kept] == ["14", "13", "12", "11", "10"]
    assert all(entry["machine"] == "machine-a" for entry in kept)
    assert "recent_sessions" not in old
    assert out["claude_limits"] == base["claude_limits"]
    first = {"schema": 2, "machine": {"id": "c", "label": "c"}, "totals": {}, "daily": {}, "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "hourly": {"2026-09-14T10": {"i": 1, "o": 2}}}
    second = {"schema": 2, "machine": {"id": "d", "label": "d"}, "totals": {}, "daily": {}, "models": {}, "projects": {}, "hours": [], "weekday_hour": [], "hourly": {"2026-09-14T10": {"i": 3, "o": 4, "cw": 5}}}
    hourly = merge.merge([merge.normalize_machine(first), merge.normalize_machine(second)])["hourly"]["2026-09-14T10"]
    assert hourly["i"] == 4 and hourly["o"] == 6 and hourly["cw"] == 5
    return "recent top-5 + hourly sum + newest Claude limits"


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
    checks = [("syntax", syntax_check), ("names_units", names_units), ("statusline", statusline_check),
              ("codex_limits", codex_limits_check), ("response_limits", response_limits_check),
              ("fixture", fixture), ("merge", merge_check)]
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
