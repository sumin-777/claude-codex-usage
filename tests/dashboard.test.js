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

const weekly = sandbox(["dayKey", "dayParse", "dayAdd", "weekdayOf", "two", "localDayKey", "hourKey", "claudeWindowStart", "claudeBucketUnits", "claudeUnits", "claudeHourUnits", "claudeUnitsAt", "median", "latestClaudeLimits", "estimateClaudeWeekly"]);
const L = (y, month, day, hour, minute) => new Date(y, month - 1, day, hour, minute || 0);
const fri = now => weekly.claudeWindowStart(now, 4, 15);
assert.strictEqual(fri(L(2026, 9, 18, 15, 0)), "2026-09-18T15");
assert.strictEqual(fri(L(2026, 9, 18, 14, 59)), "2026-09-11T15");
assert.strictEqual(fri(L(2026, 9, 18, 15, 1)), "2026-09-18T15");
assert.strictEqual(fri(L(2026, 9, 14, 13, 0)), "2026-09-11T15");
assert.strictEqual(fri(L(2026, 10, 1, 10, 0)), "2026-09-25T15");
assert.strictEqual(fri(L(2027, 1, 1, 10, 0)), "2026-12-25T15");
assert.strictEqual(weekly.claudeWindowStart(L(2026, 9, 14, 0, 0), 0, 0), "2026-09-14T00");
assert.strictEqual(weekly.claudeWindowStart(L(2026, 9, 13, 23, 59), 0, 0), "2026-09-07T00");
assert.strictEqual(weekly.hourKey(L(2026, 9, 14, 9, 30)), "2026-09-14T09");
weekly.state.machines = { a: { hourly: { "2026-09-11T14": { i: 1000 }, "2026-09-11T15": { o: 100 }, "2026-09-12T10": { cr: 10000 }, "2026-09-14T13": { cw: 400, cw1: 200, cw5: 100 } } }, b: { hourly: { "2026-09-13T08": { i: 350 } } }, c: {} };
const now = L(2026, 9, 14, 13, 30), near = (x, y) => assert(Math.abs(x - y) < 1e-9, x + " != " + y);
let result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [] });
assert.strictEqual(result.estimate, null); near(result.units, 2500); assert.strictEqual(result.nextResetKey, "2026-09-18T15");
const cal1At = L(2026, 9, 12, 10, 20).getTime(), cal2At = L(2026, 9, 13, 8, 40).getTime(), oldAt = L(2026, 9, 3, 10, 0).getTime();
let cal1 = { at: cal1At, pct: 10 };
// 기준점이 속한 시간 버킷은 분 비율만큼만 앞선 사용으로 센다(claudeUnitsAt).
// cal1(09-12 10:20): 창 시작(09-11T15)~10시 = 500+1000, 10시 버킷 1000 중 40/60 은 보정 뒤 → 1500 - 2000/3 = 2500/3, k1 = 250/3
// cal2(09-13 08:40): 1850 - 350*(20/60) = 5200/3, k2 = 1300/9. 전체 사용 2500.
const k1 = 250 / 3, k2 = 1300 / 9;
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1] });
near(result.estimate, 10 + (2500 - 2500 / 3) / k1); near(result.low, result.estimate); near(result.high, result.estimate); assert.strictEqual(result.anchor, cal1); near(cal1.k, k1); assert.strictEqual(result.changed, true);
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1] });
assert.strictEqual(result.changed, false);
// 스캔 중(keepK)이면 계산에는 쓰되 보정 기록의 k 는 건드리지 않는다
let fresh = { at: cal1At, pct: 10 };
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [fresh] }, null, true);
assert.strictEqual(fresh.k, undefined); assert.strictEqual(result.changed, false); near(result.estimate, 10 + (2500 - 2500 / 3) / k1);
cal1 = { at: cal1At, pct: 10 }; let cal2 = { at: cal2At, pct: 12 }, old = { at: oldAt, pct: 5 };
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, old] });
let middle = (k1 + k2) / 2, inc2 = 2500 - 5200 / 3;
assert.strictEqual(result.calibrations.length, 2); assert.strictEqual(result.anchor, cal2); near(result.estimate, 12 + inc2 / middle); near(result.low, 12 + inc2 / k2); near(result.high, 12 + inc2 / k1);
weekly.state.machines.a.claude_limits = { recorded_at: new Date(L(2026, 9, 14, 13, 0).getTime()).toISOString(), seven_day: { used_percentage: 64, resets_at: Math.floor(now.getTime() / 1000) + 86400 }, five_hour: { used_percentage: 65, resets_at: Math.floor(now.getTime() / 1000) + 3600 } };
let live = weekly.latestClaudeLimits(now);
assert.strictEqual(live.weekly.machine, "a"); assert.strictEqual(live.weekly.pct, 64); assert.strictEqual(live.fiveHour.pct, 65);
// 실제값(13:00)이 기준점. 13시 버킷(650)은 전부 그 뒤라 증가분으로 센다.
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, old] }, live);
assert.strictEqual(result.anchor.live, true); near(result.estimate, 64 + 650 / middle);
// 진행 중인 시간(13시, now 13:30)의 버킷은 정각~13:30 을 담는다. 13:20 기준점이면 뒤 1/3 만 증가분이다
// (한 시간으로 나누면 2/3 이 되어 방금 받은 실제값 위에 부풀어 더해진다).
weekly.state.machines.a.claude_limits.recorded_at = new Date(L(2026, 9, 14, 13, 20).getTime()).toISOString();
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, old] }, weekly.latestClaudeLimits(now));
assert.strictEqual(result.anchor.live, true); near(result.estimate, 64 + (650 / 3) / middle);
weekly.state.machines.a.claude_limits.recorded_at = new Date(L(2026, 9, 14, 13, 0).getTime()).toISOString();
// 설정 창 시작(09-11T15)보다 앞서 기록된 실제값은 기준점이 되지 않는다 ― 되면 창 전체 사용량이 64% 위에 더해진다
// (수동 보정은 지난 창 것 하나뿐이라 실제값이 더 새롭다 ― 창 조건만 가려낸다. 되돌리면 64 + 2500/200 = 76.5 가 나온다)
weekly.state.machines.a.claude_limits.recorded_at = new Date(L(2026, 9, 11, 14, 0).getTime()).toISOString();
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [{ at: oldAt, pct: 5, k: 200 }] }, weekly.latestClaudeLimits(now));
assert.strictEqual(result.anchor, null); near(result.estimate, 2500 / 200);
weekly.state.machines.a.claude_limits.recorded_at = new Date(L(2026, 9, 14, 13, 0).getTime()).toISOString();
// 주간이 만료돼도 5시간은 따로 남고, 5시간까지 만료되면 아무것도 없다
weekly.state.machines.a.claude_limits.seven_day.resets_at = Math.floor(now.getTime() / 1000) - 1;
live = weekly.latestClaudeLimits(now);
assert.strictEqual(live.weekly, null); assert.strictEqual(live.fiveHour.pct, 65);
weekly.state.machines.a.claude_limits.five_hour.resets_at = Math.floor(now.getTime() / 1000) - 1;
assert.strictEqual(weekly.latestClaudeLimits(now), null);
delete weekly.state.machines.a.claude_limits;
cal1 = { at: cal1At, pct: 10 }; cal2 = { at: cal2At, pct: 12 }; old = { at: oldAt, pct: 5, k: 200 };
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, old] });
assert.strictEqual(result.calibrations.length, 3); near(result.estimate, 12 + inc2 / k2); near(result.low, 12 + inc2 / 200); near(result.high, 12 + inc2 / k1);
weekly.state.machines.a.hourly["2026-09-19T09"] = { i: 300 };
cal1 = { at: cal1At, pct: 10, k: 140 }; cal2 = { at: cal2At, pct: 12, k: 1850 / 12 };
result = weekly.estimateClaudeWeekly(L(2026, 9, 19, 10, 0), { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, { at: cal2At, pct: 12 }] });
assert.strictEqual(result.anchor, null); near(result.units, 300); near(result.estimate, 300 / ((140 + 1850 / 12) / 2));
assert.strictEqual(cal1.k, 140); assert.strictEqual(result.changed, false);   // 지난 창은 기록이 남아 있어도 다시 계산하지 않고, k 없는 보정은 뺀다
let stored = [100, 200, 300, 400, 500, 600].map(function (k, i) { return { at: L(2026, 8, 20 + i, 10, 0).getTime(), pct: 10, k: k }; });
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: stored });
assert.strictEqual(result.anchor, null); near(result.estimate, 2500 / 400); near(result.low, 2500 / 600); near(result.high, 2500 / 200);
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
