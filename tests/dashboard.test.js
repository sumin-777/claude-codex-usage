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

const weekly = sandbox(["dayKey", "dayParse", "dayAdd", "weekdayOf", "two", "localDayKey", "hourKey", "claudeWindowStart", "claudeBucketUnits", "claudeUnits", "median", "estimateClaudeWeekly"]);
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
const cal1 = { at: L(2026, 9, 12, 10, 20).getTime(), pct: 10 };
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1] });
near(result.estimate, 2500 / 150); near(result.low, 2500 / (1500 / 9.5)); near(result.high, 2500 / (1500 / 10.5));
const cal2 = { at: L(2026, 9, 13, 8, 40).getTime(), pct: 12 }, old = { at: L(2026, 9, 3, 10, 0).getTime(), pct: 5 };
result = weekly.estimateClaudeWeekly(now, { resetDow: 4, resetHour: 15, calibrations: [cal1, cal2, old] });
assert.strictEqual(result.calibrations.length, 2); near(result.estimate, 2500 / ((150 + 1850 / 12) / 2));
near(result.low, 2500 / Math.max(1500 / 9.5, 1850 / 11.5)); near(result.high, 2500 / Math.min(1500 / 10.5, 1850 / 12.5));
console.log(tz + " OK");
