// Capacitor-specific behavior with a mocked native bridge: remote API base
// and local-notification scheduling. Run: node native.test.js
const fs = require("fs"), path = require("path"), { JSDOM } = require("jsdom");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const KEY = "since.items.v3", d = 86400000;
let fails = 0;
const check = (l, c, x = "") => { console.log((c ? "  PASS  " : "  FAIL  ") + l + (x ? "  → " + x : "")); if (!c) fails++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function boot(items, { native = true } = {}) {
  const calls = { perm: 0, scheduled: [], cancelled: [], fetches: [] };
  const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://localhost/", pretendToBeVisual: true, beforeParse(w) {
    w.localStorage.setItem(KEY, JSON.stringify(items));
    w.localStorage.setItem("since.synced.v1", "1");
    w.fetch = (url, opts) => {
      calls.fetches.push({ url: String(url), method: (opts && opts.method) || "GET" });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ items: items }) });
    };
    if (native) {
      w.Capacitor = {
        isNativePlatform: () => true,
        Plugins: {
          LocalNotifications: {
            requestPermissions: () => { calls.perm++; return Promise.resolve({ display: "granted" }); },
            getPending: () => Promise.resolve({ notifications: [{ id: 42 }] }),
            cancel: (o) => { calls.cancelled.push(o); return Promise.resolve(); },
            schedule: (o) => { calls.scheduled.push(o); return Promise.resolve(); },
          },
        },
      };
    }
  }});
  return { dom, calls };
}

const now = Date.now();
const items = [
  // interval reminder, next due in ~32 days -> should schedule
  { id: "int", icon: "✂️", name: "Haircut", every: 42, dueOn: null, cat: null,
    log: [{ id: "a", ts: now - 10 * d, note: "" }] },
  // fixed-date reminder 20 days out -> should schedule at that date
  { id: "date", icon: "🦷", name: "Dentist", every: null, dueOn: now + 20 * d, cat: null,
    log: [{ id: "b", ts: now - 100 * d, note: "" }] },
  // interval already overdue -> nothing to schedule (past)
  { id: "over", icon: "⛽", name: "Gas", every: 5, dueOn: null, cat: null,
    log: [{ id: "c", ts: now - 10 * d, note: "" }] },
  // no reminder -> nothing
  { id: "none", icon: "•", name: "Plain", every: null, dueOn: null, cat: null,
    log: [{ id: "e", ts: now - 3 * d, note: "" }] },
];

(async () => {
  console.log("--- A. Native app uses the remote API ---");
  let { dom, calls } = boot(items);
  await sleep(250);
  check("fetches go to hindsight.iameberhard.com",
    calls.fetches.length > 0 && calls.fetches.every((f) => f.url.startsWith("https://hindsight.iameberhard.com/api/items")),
    JSON.stringify(calls.fetches.map((f) => f.url).slice(0, 2)));
  check("notification permission requested", calls.perm >= 1);

  console.log("--- B. Scheduling: future reminders only ---");
  check("pending notifications cleared first",
    calls.cancelled.length > 0 && calls.cancelled[0].notifications[0].id === 42);
  const last = calls.scheduled[calls.scheduled.length - 1];
  check("a schedule call happened", !!last);
  const names = last ? last.notifications.map((n) => n.title) : [];
  check("exactly the two future reminders scheduled",
    last && last.notifications.length === 2 &&
    names.some((n) => /Haircut/.test(n)) && names.some((n) => /Dentist/.test(n)),
    names.join(" | "));
  if (last) {
    const dentist = last.notifications.find((n) => /Dentist/.test(n.title));
    const haircut = last.notifications.find((n) => /Haircut/.test(n.title));
    check("dentist fires on its dueOn date",
      Math.abs(dentist.schedule.at.getTime() - (now + 20 * d)) < 1000,
      dentist.schedule.at.toISOString());
    const expect = new Date(new Date(now - 10 * d).setHours(0, 0, 0, 0) + 42 * d).setHours(9, 0, 0, 0);
    check("haircut fires at 9am on last+42d",
      haircut.schedule.at.getTime() === expect, haircut.schedule.at.toISOString());
    check("ids are positive ints", last.notifications.every((n) => Number.isInteger(n.id) && n.id > 0));
    check("body mentions cadence", /last done \d+ days ago/.test(haircut.body), haircut.body);
  }

  console.log("--- C. Logging reschedules ---");
  const before = calls.scheduled.length;
  const card = [...dom.window.document.querySelectorAll(".card")].find((c) => c.querySelector("h3").textContent === "Gas");
  card.querySelector(".again").dispatchEvent(new dom.window.Event("click", { bubbles: true }));
  await sleep(150);
  const newLast = calls.scheduled[calls.scheduled.length - 1];
  check("new schedule call after logging", calls.scheduled.length > before);
  check("Gas now scheduled too (no longer overdue)",
    newLast && newLast.notifications.some((n) => /Gas/.test(n.title)), newLast && newLast.notifications.length);

  console.log("--- D. Plain web stays unchanged ---");
  ({ dom, calls } = boot(items, { native: false }));
  await sleep(250);
  check("fetches stay relative", calls.fetches.length > 0 && calls.fetches.every((f) => f.url === "/api/items"),
    JSON.stringify(calls.fetches.map((f) => f.url).slice(0, 2)));
  check("no notification calls", calls.perm === 0 && calls.scheduled.length === 0);
  check("page renders normally", dom.window.document.querySelectorAll(".card").length === 4);

  console.log("\n" + (fails === 0 ? "ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"));
  process.exit(fails ? 1 : 0);
})();
