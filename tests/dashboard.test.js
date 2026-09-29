const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const tz = process.env.TZ;
if (Intl.DateTimeFormat().resolvedOptions().timeZone !== tz) {
  throw new Error("TZ was not applied: expected " + tz + ", got " + Intl.DateTimeFormat().resolvedOptions().timeZone);
}
const html = fs.readFileSync(require("path").join(__dirname, "..", "src", "dashboard.html"), "utf8");
const scripts = [];
const scriptRe = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let match;
while ((match = scriptRe.exec(html))) {
  new Function(match[1]);
  scripts.push(match[1]);
}
const source = scripts.join("\n");

function extract(name) {
  const patterns = ["function " + name + "(", name + " = function("];
  let at = -1;
  for (const pattern of patterns) {
    at = source.indexOf(pattern);
    if (at >= 0) break;
  }
  if (at < 0) throw new Error("missing function " + name);
  let start = source.indexOf("{", at), depth = 0;
  if (start < 0) throw new Error("missing body for " + name);
  for (let i = start; i < source.length; i++) {
    if (source[i] === "{") depth++;
    else if (source[i] === "}" && --depth === 0) return source.slice(at, i + 1);
  }
  throw new Error("unclosed body for " + name);
}

function sandbox(names) {
  const state = { machines: {} };
  const context = { Date, Intl, Math, Number, Object, String, isFinite, isNaN, state };
  vm.runInNewContext(names.map(extract).join("\n"), context);
  return context;
}

const recent = sandbox(["fmt", "relativeTime", "recentSessionWarning", "recentSessionCellText"]);
[[0, "0"], [995, "995"], [999, "999"], [999.6, "1천"], [1000, "1천"], [4380, "4.38천"],
 [9996, "1만"], [9999.6, "1만"], [100000, "10만"], [412345, "41.2만"], [438514, "43.9만"],
 [5000000, "500만"], [11734555, "1,173만"], [55296268, "5,530만"], [99995000, "1억"],
 [578143623, "5.78억"], [26968689307, "270억"], [1.2e12, "1.2조"], [12345678901234, "12.3조"], [null, "0"]]
  .forEach(pair => assert.strictEqual(recent.fmt(pair[0]), pair[1], "fmt(" + pair[0] + ")"));
const nowMs = Date.UTC(2026, 8, 14, 6, 0, 0), iso = ms => new Date(ms).toISOString();
assert.strictEqual(recent.relativeTime(iso(nowMs - 30e3), nowMs), "방금");
assert.strictEqual(recent.relativeTime(iso(nowMs - 59 * 60e3), nowMs), "59분 전");
assert.strictEqual(recent.relativeTime(iso(nowMs - 61 * 60e3), nowMs), "1시간 전");
assert.strictEqual(recent.relativeTime(iso(nowMs - 25 * 3600e3), nowMs), "1일 전");
assert.strictEqual(recent.relativeTime("2026-09-14T14:59:00+09:00", nowMs), "1분 전");
assert.strictEqual(recent.recentSessionWarning({ last: iso(nowMs - 61 * 60e3), ctx: 100000 }, nowMs), true);
assert.strictEqual(recent.recentSessionWarning({ last: iso(nowMs - 60 * 60e3), ctx: 100000 }, nowMs), false);
assert.strictEqual(recent.recentSessionWarning({ last: iso(nowMs - 2 * 3600e3), ctx: 99999 }, nowMs), false);
let cell = recent.recentSessionCellText([{ last: iso(nowMs - 2 * 3600e3), ctx: 412345 }, { last: iso(nowMs - 5 * 3600e3), ctx: 1000 }], nowMs);
assert.strictEqual(cell.main, "2시간 전 · 컨텍스트 41.2만 · 이전 세션 1개");
assert.strictEqual(cell.warning, "재개하면 약 41.2만 다시 씀");
cell = recent.recentSessionCellText([{ last: iso(nowMs - 10 * 60e3), ctx: 5000000 }], nowMs);
assert.strictEqual(cell.main, "10분 전 · 컨텍스트 500만");
assert.strictEqual(cell.warning, "");
cell = recent.recentSessionCellText([], nowMs);
assert.strictEqual(cell.main, "—");
assert.strictEqual(cell.warning, "");

const level = sandbox(["limitLevel"]).limitLevel;
[[0, ""], [74.9, ""], [75, "warn"], [89.9, "warn"], [90, "danger"], [105, "danger"]]
  .forEach(pair => assert.strictEqual(level(pair[0]), pair[1], "limitLevel(" + pair[0] + ")"));
const live = sandbox(["latestClaudeLimits"]);
const now = new Date(2026, 8, 14, 13, 30), sec = Math.floor(now.getTime() / 1000);
live.state.machines = {
  a: { claude_limits: { recorded_at: new Date(2026, 8, 14, 13, 0).toISOString(), seven_day: { used_percentage: 64, resets_at: sec + 86400 }, five_hour: { used_percentage: 65, resets_at: sec + 3600 } } },
  b: { machine: { label: "old" }, claude_limits: { recorded_at: new Date(2026, 8, 14, 12, 0).toISOString(), seven_day: { used_percentage: 50, resets_at: sec + 86400 } } },
  c: {}
};
let got = live.latestClaudeLimits(now);   // 머신 여럿이면 가장 새로 기록된 값
assert.strictEqual(got.weekly.machine, "a"); assert.strictEqual(got.weekly.pct, 64); assert.strictEqual(got.fiveHour.pct, 65);
assert.strictEqual(got.weekly.stale, false);
// 리셋이 지난 창도 버리지 않고 stale 로 남긴다(Codex 처럼 '만료됨' 표시). 5시간은 따로 판정
live.state.machines.a.claude_limits.seven_day.resets_at = sec - 1;
got = live.latestClaudeLimits(now);
assert.strictEqual(got.weekly.machine, "a"); assert.strictEqual(got.weekly.stale, true); assert.strictEqual(got.fiveHour.stale, false);
live.state.machines.a = {};
assert.strictEqual(live.latestClaudeLimits(now).weekly.machine, "old");
live.state.machines = {};
assert.strictEqual(live.latestClaudeLimits(now), null);
const limits = sandbox(["normalizeClaudeLimits"]);
let cleanLimits = limits.normalizeClaudeLimits({ recorded_at:"2026-09-17T01:02:03Z", account:"secret", seven_day:{used_percentage:64,resets_at:1789711200,extra:true} });
assert.deepStrictEqual(JSON.parse(JSON.stringify(cleanLimits)), { recorded_at:"2026-09-17T01:02:03Z", seven_day:{used_percentage:64,resets_at:1789711200} });
assert.strictEqual(limits.normalizeClaudeLimits({ recorded_at:"bad", seven_day:{used_percentage:64,resets_at:1} }), null);
// 한도를 넘긴 값(100 초과)도 버리지 않는다 ― 버리면 가장 궁금한 순간에 옛 값이 '실제'로 남는다
assert.strictEqual(limits.normalizeClaudeLimits({ recorded_at:"2026-09-17T01:02:03Z", seven_day:{used_percentage:105,resets_at:1789711200} }).seven_day.used_percentage, 105);
assert.strictEqual(limits.normalizeClaudeLimits({ recorded_at:"2026-09-17T01:02:03Z", seven_day:{used_percentage:-1,resets_at:1789711200} }), null);
// 창이 빈 Codex 한도 보고는 받을 때 뺀다(옛 수집기가 보내올 수 있다). 창이 있으면 그대로 둔다.
const payloads = sandbox(["normalizeBucket", "normalizeClaudeLimits", "normalizePayload"]);
let codexPayload = { totals: {}, codex: { totals: {}, daily: {}, limits: { at: "2026-09-18T07:34:19Z", plan: "plus", windows: [] } } };
payloads.normalizePayload(codexPayload);
assert.strictEqual(codexPayload.codex.limits, undefined); assert.ok(codexPayload.codex.daily);
codexPayload = { totals: {}, codex: { totals: {}, daily: {}, limits: { at: "x", windows: [{ used_percent: 90, window_minutes: 300, resets_at: 1 }] } } };
payloads.normalizePayload(codexPayload);
assert.strictEqual(codexPayload.codex.limits.windows.length, 1);
console.log(tz + " OK");
