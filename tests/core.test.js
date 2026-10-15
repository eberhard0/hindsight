// Core behavior of the web app (no server, no Capacitor): logging, history,
// editing, reminders, sorting, CSV. Run: node core.test.js
const fs = require("fs"), path = require("path"), { JSDOM } = require("jsdom");
const html = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
const KEY = "since.items.v3", d = 86400000;
let fails = 0;
const check = (l, c, x = "") => { console.log((c ? "  PASS  " : "  FAIL  ") + l + (x ? "  → " + x : "")); if (!c) fails++; };

function boot(items) {
  const dom = new JSDOM(html, { runScripts: "dangerously", url: "https://hindsight.test/", pretendToBeVisual: true, beforeParse(w) {
    if (items) w.localStorage.setItem(KEY, JSON.stringify(items));
    // no w.fetch: sync layer disables itself, tests run purely local
  }});
  return dom;
}
const stored = (dom) => JSON.parse(dom.window.localStorage.getItem(KEY) || "[]");
const click = (dom, el) => el.dispatchEvent(new dom.window.Event("click", { bubbles: true }));
const change = (dom, el) => el.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
const submit = (dom, name) => {
  dom.window.document.getElementById("fName").value = name;
  dom.window.document.getElementById("logForm").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
};
const iso = (ts) => { const z = new Date(ts), p = (n) => String(n).padStart(2, "0"); return z.getFullYear() + "-" + p(z.getMonth() + 1) + "-" + p(z.getDate()); };

console.log("--- 1. Quick log ---");
let dom = boot();
submit(dom, "Haircut");
let s = stored(dom);
check("item created with 1 entry", s.length === 1 && s[0].log.length === 1);
check("stamped now", Math.abs(s[0].log[0].ts - Date.now()) < 5000);
check("icon guessed", s[0].icon === "✂️", s[0].icon);
check("no reminder by default", s[0].every === null);

console.log("--- 2. Same name appends, case-insensitive ---");
submit(dom, "haircut");
s = stored(dom);
check("still one item, two entries", s.length === 1 && s[0].log.length === 2);

console.log("--- 3. Log again button ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null,
  log: [{ id: "1", ts: Date.now() - 47 * d, note: "" }] }]);
check("counter 47 before", dom.window.document.querySelector(".big").textContent === "47");
click(dom, dom.window.document.querySelector(".again"));
s = stored(dom);
check("counter 0 after, 2 entries, newest first on disk",
  dom.window.document.querySelector(".big").textContent === "0" &&
  s[0].log.length === 2 && s[0].log[0].ts > s[0].log[1].ts);

console.log("--- 4. Edit last log (forgot to log) ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null,
  log: [{ id: "1", ts: Date.now(), note: "" }] }]);
click(dom, dom.window.document.querySelector(".edit"));
let ed = dom.window.document.querySelector(".editor");
ed.querySelector(".e-date").value = iso(Date.now() - 5 * d);
ed.querySelector(".e-time").value = "14:30";
ed.querySelector(".e-note").value = "Joe's";
click(dom, ed.querySelector(".save"));
s = stored(dom);
check("backdated to 5 days, 14:30, note kept",
  dom.window.document.querySelector(".big").textContent === "5" &&
  new Date(s[0].log[0].ts).getHours() === 14 && s[0].log[0].note === "Joe's");

console.log("--- 5. Reminder modes ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: 42, dueOn: null, cat: null,
  log: [{ id: "1", ts: Date.now() - 55 * d, note: "" }] }]);
check("interval overdue", dom.window.document.querySelector(".card").classList.contains("s-over") &&
  /13d over/.test(dom.window.document.querySelector(".cadence").textContent));
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: Date.now() + 4 * d, cat: null,
  log: [{ id: "1", ts: Date.now() - 30 * d, note: "" }] }]);
check("date reminder due soon", dom.window.document.querySelector(".card").classList.contains("s-soon") &&
  /4d left/.test(dom.window.document.querySelector(".cadence").textContent));
click(dom, dom.window.document.querySelector(".again"));
check("future dueOn survives logging", stored(dom)[0].dueOn !== null);
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: Date.now() - 2 * d, cat: null,
  log: [{ id: "1", ts: Date.now() - 30 * d, note: "" }] }]);
click(dom, dom.window.document.querySelector(".again"));
check("met dueOn clears on logging", stored(dom)[0].dueOn === null);

console.log("--- 6. Latest-logged sorts first ---");
dom = boot([
  { id: "1", name: "Old", icon: "•", every: null, dueOn: null, cat: null, log: [{ id: "a", ts: Date.now() - 40 * d, note: "" }] },
  { id: "2", name: "New", icon: "•", every: null, dueOn: null, cat: null, log: [{ id: "b", ts: Date.now() - 1 * d, note: "" }] },
]);
const order = [...dom.window.document.querySelectorAll(".card h3")].map((h) => h.textContent);
check("order New, Old", JSON.stringify(order) === JSON.stringify(["New", "Old"]), order.join(","));

console.log("--- 7. History panel ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null,
  log: [{ id: "a", ts: Date.now(), note: "" }, { id: "b", ts: Date.now() - 40 * d, note: "" }, { id: "c", ts: Date.now() - 82 * d, note: "" }] }]);
click(dom, dom.window.document.querySelector(".hist"));
const rows = [...dom.window.document.querySelectorAll(".hentry")];
check("3 rows, gaps +40d/+42d/first",
  rows.length === 3 && rows[0].querySelector(".gap").textContent === "+40d" &&
  rows[1].querySelector(".gap").textContent === "+42d" && rows[2].querySelector(".gap").textContent === "first");
check("average shown", /3 logs · averages every 41 days/.test(dom.window.document.querySelector(".avg").textContent));

console.log("--- 9. Trash: delete is recoverable ---");
dom = boot([
  { id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null, deleted: null,
    log: [{ id: "1", ts: Date.now() - 3 * d, note: "" }] },
  { id: "g", icon: "⛽", name: "Gas", every: null, dueOn: null, cat: null, deleted: null,
    log: [{ id: "2", ts: Date.now() - 1 * d, note: "" }] },
]);
const D9 = () => dom.window.document;
const cardNamed = (n) => [...D9().querySelectorAll(".card")].find((c) => c.querySelector("h3").textContent === n);
check("delete button is a trash can", cardNamed("Haircut").querySelector(".del").textContent === "\uD83D\uDDD1");
click(dom, cardNamed("Haircut").querySelector(".del"));
s = stored(dom);
check("tombstoned, not erased", s.length === 2 && !!s.find((i) => i.name === "Haircut").deleted);
check("card hidden from grid", !cardNamed("Haircut"));
check("chip counts only live things", /1 tracked/.test(D9().querySelector(".summary").textContent));
check("undo toast offered", /moved to trash/.test(D9().querySelector(".toast").textContent) && !!D9().querySelector(".toast-undo"));
click(dom, D9().querySelector(".toast-undo"));
check("undo brings it back", !!cardNamed("Haircut") && stored(dom).find((i) => i.name === "Haircut").deleted == null);

console.log("--- 10. Trash panel: restore and delete-forever ---");
click(dom, cardNamed("Haircut").querySelector(".del"));
let tb = D9().getElementById("trashBtn");
check("trash button appears with count", !tb.hidden && /Trash \(1\)/.test(tb.textContent));
click(dom, tb);
check("panel lists the item with log count", /Haircut/.test(D9().getElementById("trashList").textContent) && /1 logs/.test(D9().getElementById("trashList").textContent));
click(dom, D9().querySelector(".t-restore"));
check("restore from panel works", !!cardNamed("Haircut") && stored(dom).every((i) => !i.deleted));
check("empty trash hides button", D9().getElementById("trashBtn").hidden);
// delete forever needs two clicks
click(dom, cardNamed("Gas").querySelector(".del"));
click(dom, D9().getElementById("trashBtn"));
let kill = D9().querySelector(".t-kill");
click(dom, kill);
check("first click only arms", stored(dom).length === 2 && /again/.test(D9().querySelector(".t-kill").textContent));
click(dom, D9().querySelector(".t-kill"));
check("second click erases for real", stored(dom).length === 1 && !stored(dom).find((i) => i.name === "Gas"));

console.log("--- 11. Typing a trashed name revives it ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null, deleted: Date.now(),
  log: [{ id: "1", ts: Date.now() - 9 * d, note: "" }] }]);
check("starts hidden", dom.window.document.querySelectorAll(".card").length === 0);
submit(dom, "haircut");
s = stored(dom);
check("revived with history intact + new log", s.length === 1 && s[0].deleted == null && s[0].log.length === 2);
check("toast says restored", /restored from trash/.test(dom.window.document.querySelector(".toast").textContent));

console.log("--- 8. CSV import merge + dedupe, export round-trip ---");
dom = boot([{ id: "h", icon: "✂️", name: "Haircut", every: null, dueOn: null, cat: null,
  log: [{ id: "a", ts: new Date(2026, 6, 1, 10, 0, 0).getTime(), note: "" }] }]);
const csvText = 'Category,Event,Occurrence,Note\n"Health","Hair Cut","2026-07-01 10:00:00",""\n"Health","Hair Cut","2026-05-01 09:00:00","salon"\n"Cars","Gas","2026-06-15 08:00:00",""';
// call the page's importer through the hidden file-input path is heavy; drive importCSV via a crafted event is not exposed — so re-run through DataTransfer-free route:
// simulate by dispatching change with a stubbed FileReader
dom.window.FileReader = function () {
  const self = this;
  this.readAsText = function () { setTimeout(function () { self.result = csvText; self.onload(); }, 0); };
};
const fi = dom.window.document.getElementById("importFile");
Object.defineProperty(fi, "files", { value: [{}] });
fi.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
setTimeout(() => {
  s = stored(dom);
  const hc = s.find((i) => i.name === "Haircut");
  check("merged into Haircut, deduped identical ts: 2 entries", hc && hc.log.length === 2, hc && hc.log.length);
  check("note came through", hc && hc.log.some((e) => e.note === "salon"));
  check("Gas created with category", s.some((i) => i.name === "Gas" && i.cat === "Cars"));
  let blob = null;
  dom.window.URL.createObjectURL = (b) => { blob = b; return "blob:x"; };
  dom.window.HTMLAnchorElement.prototype.click = function () {};
  click(dom, dom.window.document.getElementById("exportBtn"));
  blob.text().then((t) => {
    const lines = t.trim().split("\n");
    check("export: header + 3 rows", lines.length === 4 && lines[0] === "Category,Event,Occurrence,Note", lines.length);
    console.log("\n" + (fails === 0 ? "ALL CHECKS PASSED" : fails + " CHECK(S) FAILED"));
    process.exit(fails ? 1 : 0);
  });
}, 50);
