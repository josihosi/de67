// Real browser proof for wrapping cards, briefing placement and live radar geometry.
// Uses the same optional playwright-core / Chromium setup as test_live_refresh.mjs.
import assert from "node:assert/strict";
import {spawn, execFileSync} from "node:child_process";
import {mkdtemp, mkdir, writeFile, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join, dirname} from "node:path";
import {fileURLToPath} from "node:url";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.DE67_PLAYWRIGHT || "playwright-core");
const root = await mkdtemp(join(tmpdir(), "de67-radar-"));
const state = join(root, ".de67/state"), database = join(state, "deadlines.sqlite3");
await mkdir(state, {recursive: true});
await mkdir(join(root, "sessions"));
function sql(text) {
  execFileSync(process.env.PYTHON || "python3", ["-c",
    "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.executescript(sys.argv[2]); c.close()", database, text]);
}
sql("CREATE TABLE tasks(task_id TEXT, claim_id TEXT, started_at REAL, deadline_at REAL, closure_gap_id TEXT, closure_gap_revision INTEGER); " +
    "INSERT INTO tasks VALUES('R-1-run', 'R-1', 1, 9999999999, 'G-2', 1);");
await writeFile(join(state, "workspace.json"), JSON.stringify({clock: {state: database, lineage: "test"}}));
await writeFile(join(root, ".de67/DFS.md"), "# DFS\nStatus: Frozen\n");
await writeFile(join(root, ".de67/work-ledger.md"), "## Active work\n- [ ] R-1 — Exercise the current work.\n");
const cache = join(root, "briefing.json"), reportPath = join(root, "report.json"), sidecar = join(root, "sidecar.py");
await writeFile(sidecar, "from pathlib import Path\nprint(Path(__file__).with_name('report.json').read_text())\n");
const narrator = join(root, "narrator.py");
await writeFile(narrator, "# This fixture uses the briefing supplied by the test.\n");
const summary = {
  headline: "The team is tracing a signal from the first encounter through a complete save and recovery cycle.",
  changed: "The initial encounter now records its evidence. A repeated attempt will check that the recorded outcome survives a restart without creating a second actor.",
  next: "Follow the same actor across the boundary, reload the save and compare the resulting action with the original request.",
  snag: "The full recovery route still needs evidence from the same run."
};
await writeFile(cache, JSON.stringify({summary}));
const report = {claim: "R-1", latest_task: "R-1-run", latest_task_gap: "G-2", latest_task_result: "active",
  gaps: [
    {gap_id: "G-1", revision: 1, status: "proved", summary: "Confirm that the encounter records the original actor and signal before either one leaves the immediate area."},
    {gap_id: "G-2", revision: 2, status: "open", summary: "Follow the same actor through departure, save, reload, and re-entry while preserving the causal link to the original request."},
    {gap_id: "G-3-" + "longidentifier".repeat(7), revision: 1, status: "open", summary: "AnUnbrokenWorkItemTitle".repeat(8)},
    {gap_id: "G-4", revision: 1, status: "open", summary: "Verify cleanup and replay without <script>markup()</script> becoming executable or losing the complete title."}
  ], attention: [
    {key: "target", label: "Assigned gap", points: [0, 1, 0, 0].map((relative_pull, i) => ({gap_id: "G-" + (i + 1), relative_pull, raw_relation: relative_pull}))},
    {key: "code", label: "Workspace code", points: [0.3, 1, 0.1, 0.5].map((relative_pull, i) => ({gap_id: "G-" + (i + 1), relative_pull, raw_relation: relative_pull / 2}))},
    {key: "test", label: "Workspace tests", points: [0.6, 0.4, 0, 1].map((relative_pull, i) => ({gap_id: "G-" + (i + 1), relative_pull, raw_relation: relative_pull / 2}))}
  ]};
await writeFile(reportPath, JSON.stringify(report));
const server = spawn(process.env.PYTHON || "python3", ["-u", join(dirname(fileURLToPath(import.meta.url)), "de67_dashboard.py"),
  "--workspace", root, "--port", "0", "--refresh-seconds", "1", "--codex-sessions", join(root, "sessions"),
  "--sidecar-script", sidecar, "--fratbro-script", narrator, "--fratbro-cache", cache], {stdio: ["ignore", "pipe", "pipe"]});
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    let output = "", errors = "";
    server.stderr.on("data", chunk => {errors += chunk;});
    const timeout = setTimeout(() => reject(new Error("Server did not start")), 10000);
    server.stdout.on("data", chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) {clearTimeout(timeout); resolve(match[0]);}
    });
    server.once("exit", code => {clearTimeout(timeout); reject(new Error(`Server exit ${code}: ${errors}`));});
  });
  browser = await chromium.launch({headless: true, executablePath: process.env.DE67_CHROMIUM});
  const page = await browser.newPage({viewport: {width: 1200, height: 1000}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(url);
  await page.waitForSelector(".radar-links path");
  assert.equal(await page.locator('.assigned-bearing[data-assigned-index="1"]').count(), 1);
  assert.equal(await page.locator('.assigned-bearing').count(), 1);
  assert.match(await page.locator('.assigned-destination').textContent(), /Assigned to.*G-2/);
  for (const [index, gap] of report.gaps.entries()) {
    assert.equal(await page.locator(`[data-radar-index="${index}"] p`).textContent(), gap.summary);
  }
  await page.evaluate(() => {window.originalRadar = document.getElementById("panel-trajectory");});
  async function checkLayout(width) {
    await page.setViewportSize({width, height: 1000});
    await page.waitForFunction(() => {
      const panel = document.querySelector(".trajectory");
      return panel.scrollWidth <= panel.clientWidth + 1;
    });
    if (width > 800) {
      await page.waitForFunction(count => document.querySelectorAll(".radar-links path").length === count, report.gaps.length);
    }
    const measurements = await page.evaluate(() => {
      const panel = document.querySelector(".trajectory"), map = panel.querySelector(".radar-map");
      const head = panel.querySelector(".radar-briefing"), details = panel.querySelector(".radar-details");
      return {
        viewportFits: document.documentElement.scrollWidth <= innerWidth + 1,
        ordered: head.getBoundingClientRect().bottom <= map.getBoundingClientRect().top &&
          map.getBoundingClientRect().bottom <= details.getBoundingClientRect().top,
        font: getComputedStyle(details.querySelector("p")).fontFamily,
        statusVisible: getComputedStyle(panel.querySelector(".radar-kicker span")).display !== "none",
        cardsFit: [...panel.querySelectorAll(".radar-contact")].every(card =>
          card.scrollWidth <= card.clientWidth + 1 && card.scrollHeight <= card.clientHeight + 1 &&
          [...card.children].every(child => child.getBoundingClientRect().bottom <= card.getBoundingClientRect().bottom)),
        linkCount: panel.querySelectorAll(".radar-links path").length
      };
    });
    assert(measurements.viewportFits, `page overflows at ${width}`);
    assert(measurements.ordered, `briefing order at ${width}`);
    assert(measurements.cardsFit, `title cards overflow at ${width}`);
    assert(measurements.statusVisible, `radar status hidden at ${width}`);
    assert.match(measurements.font, /monospace/);
    if (width > 800) assert.equal(measurements.linkCount, report.gaps.length);
  }
  for (const width of [1200, 820, 768, 390]) {
    await checkLayout(width);
    if (process.env.DE67_RADAR_ARTIFACTS && [1200, 390].includes(width)) {
      await mkdir(process.env.DE67_RADAR_ARTIFACTS, {recursive: true});
      await page.locator(".trajectory").screenshot({path: join(process.env.DE67_RADAR_ARTIFACTS, `radar-${width}.png`)});
    }
  }
  for (let index = 5; index <= 7; index++) {
    report.gaps.push({gap_id: `G-${index}`, revision: 1, status: "open",
      summary: `Check route ${index} across a complete departure and return, including the evidence needed to distinguish the original actor from a replacement.`});
    for (const series of report.attention) {
      series.points.push({gap_id: `G-${index}`, relative_pull: series.key === "target" ? 0 : index / 8,
        raw_relation: series.key === "target" ? 0 : index / 16});
    }
  }
  await writeFile(reportPath, JSON.stringify(report));
  sql("PRAGMA user_version = 1;");
  await page.waitForFunction(() => document.querySelectorAll(".radar-contact").length === 7);
  for (const width of [1200, 820, 768, 390]) {
    await checkLayout(width);
    assert(await page.evaluate(() => {
      const markers = [...document.querySelectorAll("[data-radar-marker]")].map(node => node.getBoundingClientRect());
      return markers.every((a, i) => markers.slice(i + 1).every(b =>
        Math.hypot(a.x + a.width / 2 - b.x - b.width / 2, a.y + a.height / 2 - b.y - b.height / 2) >= (a.width + b.width) / 2));
    }), `seven markers overlap at ${width}`);
    if (process.env.DE67_RADAR_ARTIFACTS && [1200, 390].includes(width)) {
      await page.locator(".trajectory").screenshot({path: join(process.env.DE67_RADAR_ARTIFACTS, `radar-7-${width}.png`)});
    }
  }
  await page.setViewportSize({width: 1200, height: 1000});
  summary.headline = "A shorter follow-up is now active.";
  report.gaps[1].summary = "Confirm the recovered actor.";
  await writeFile(cache, JSON.stringify({summary}));
  await writeFile(reportPath, JSON.stringify(report));
  sql("PRAGMA user_version = 2;");
  await page.waitForFunction(() => document.querySelector(".radar-briefing").textContent.includes("A shorter follow-up"));
  await page.waitForFunction(() => document.querySelectorAll(".radar-links path").length === 7);
  assert(await page.evaluate(() => originalRadar === document.getElementById("panel-trajectory")));
  await checkLayout(1200);
  await writeFile(join(root, ".de67/work-ledger.md"), "");
  sql("DELETE FROM tasks;");
  const before = await readFile(database);
  await page.waitForSelector(".radar-idle");
  assert.equal(await page.locator(".radar-contact").count(), 0);
  assert(await page.locator(".radar-briefing").textContent().then(text => text.includes(summary.headline)));
  assert(await page.locator(".radar-details").textContent().then(text => text.includes(summary.next)));
  assert.deepEqual(await readFile(database), before);
  assert.equal(await page.locator('.assigned-bearing').count(), 0);
  if (process.env.DE67_RADAR_ARTIFACTS) {
    await page.locator(".trajectory").screenshot({path: join(process.env.DE67_RADAR_ARTIFACTS, "radar-idle.png")});
  }
  assert.deepEqual(errors, []);
  console.log("PASS: four and seven spokes, full long titles, responsive layout, joined briefing, live geometry and empty-ledger radar; source database unchanged");
} finally {
  await browser?.close();
  server.kill();
  await new Promise(resolve => server.exitCode !== null ? resolve() : server.once("exit", resolve));
  await rm(root, {recursive: true, force: true});
}
