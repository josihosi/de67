// Browser integration proof. Requires playwright-core and an installed Chromium.
import assert from "node:assert/strict";
import {spawn} from "node:child_process";
import {mkdtemp, mkdir, writeFile, readFile, rm} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join, dirname} from "node:path";
import {fileURLToPath} from "node:url";
import {createRequire} from "node:module";
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.DE67_PLAYWRIGHT || "playwright-core");
const root = await mkdtemp(join(tmpdir(), "de67-refresh-"));
const de67 = join(root, ".de67");
await mkdir(de67);
await mkdir(join(root, "sessions"));
await writeFile(join(de67, "DFS.md"), "# DFS\nStatus: Frozen\n");
const ledger = join(de67, "work-ledger.md");
const content = title => "# Ledger\n\n## Active work\n\n- [ ] R-1 — " + title +
  "\n\n" + Array.from({length: 35}, (_, i) => `Paragraph ${i}: Some readable project detail.`).join("\n\n") +
  "\n\n## Waiting work\n\n## Blocked work\n";
await writeFile(ledger, content("Original work"));
const server = spawn(process.env.PYTHON || "python3", ["-u",
  join(dirname(fileURLToPath(import.meta.url)), "de67_dashboard.py"),
  "--workspace", root, "--port", "0", "--refresh-seconds", "1",
  "--codex-sessions", join(root, "sessions")], {stdio: ["ignore", "pipe", "pipe"]});
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    let output = "";
    const timeout = setTimeout(() => reject(new Error("Server did not start")), 10000);
    server.stdout.on("data", chunk => {
      output += chunk;
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) {clearTimeout(timeout); resolve(match[0]);}
    });
    server.once("exit", code => {clearTimeout(timeout); reject(new Error(`Server exit ${code}`));});
  });
  browser = await chromium.launch({headless: true, executablePath: process.env.DE67_CHROMIUM});
  const page = await browser.newPage({viewport: {width: 1200, height: 700}});
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  let navigations = 0;
  page.on("framenavigated", frame => {if (frame === page.mainFrame()) navigations++;});
  const response = await page.goto(url + "/ledger");
  assert.match(response.headers()["content-security-policy"], /script-src 'self'; connect-src 'self'/);
  await page.evaluate(() => {
    window.originalMain = document.querySelector("main");
    window.originalParagraph = [...document.querySelectorAll("p")].find(p => p.textContent.includes("Paragraph 15:"));
    originalParagraph.scrollIntoView();
    window.originalTop = originalParagraph.getBoundingClientRect().top;
  });
  await writeFile(ledger, content("Changed work") + "\nA later note.\n");
  await page.waitForFunction(() => document.body.textContent.includes("Changed work"));
  assert(await page.evaluate(() => originalMain === document.querySelector("main")));
  assert(await page.evaluate(() => originalParagraph.isConnected));
  assert(Math.abs(await page.evaluate(() => originalParagraph.getBoundingClientRect().top - originalTop)) <= 1);
  assert.equal(navigations, 1);
  // Adding substantial text above the reading position preserves the same line.
  const growth = content("Changed work").replace("Paragraph 0:", "Extra material above. ".repeat(120) + "\n\nParagraph 0:");
  await writeFile(ledger, growth);
  await page.waitForFunction(() => document.body.textContent.includes("Extra material above."));
  // Text nodes after an insertion may be matched positionally; check the actual
  // paragraph the reader was viewing, not just an unchanged numeric scrollY.
  const top = await page.locator("p").filter({hasText: /^Paragraph 15:/}).evaluate(node => node.getBoundingClientRect().top);
  assert(Math.abs(top) <= 1, `Reading position moved by ${top}px`);
  await page.evaluate(() => {
    const range = document.createRange(); range.selectNodeContents(document.querySelector("h2"));
    window.getSelection().removeAllRanges(); window.getSelection().addRange(range);
  });
  await writeFile(ledger, content("Selected text stays"));
  await page.waitForTimeout(1300);
  assert(!(await page.textContent("body")).includes("Selected text stays"));
  await page.evaluate(() => window.getSelection().removeAllRanges());
  await page.waitForFunction(() => document.body.textContent.includes("Selected text stays"));
  // Exercise the visibility event gate deterministically in a headless browser.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {configurable: true, get: () => true});
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await writeFile(ledger, content("Visible again"));
  await page.waitForTimeout(1300);
  assert(!(await page.textContent("body")).includes("Visible again"));
  await page.evaluate(() => {
    delete document.hidden; document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForFunction(() => document.body.textContent.includes("Visible again"));
  await page.route("**/ledger", route => route.fulfill({status: 503, body: "offline"}));
  await page.waitForFunction(() => document.getElementById("refresh-status").textContent.includes("unavailable"));
  assert((await page.textContent("body")).includes("Visible again"));
  await page.unroute("**/ledger");
  await writeFile(ledger, content("Recovered snapshot"));
  await page.locator("[data-refresh]").click();
  await page.waitForFunction(() => document.body.textContent.includes("Recovered snapshot"));
  assert.equal(navigations, 1);
  assert.equal(await readFile(ledger, "utf8"), content("Recovered snapshot"));
  await page.goto(url + "/");
  await page.evaluate(() => {
    window.originalStars = document.querySelector(".galaxy svg");
    window.originalFocus = document.getElementById("panel-focus");
  });
  await writeFile(ledger, content("New overview work").replace("## Waiting work\n", "## Waiting work\n\n- [ ] R-2 — Waiting for an event.\n"));
  await page.waitForFunction(() => document.getElementById("panel-waiting"));
  assert((await page.textContent("#panel-focus")).includes("New overview work"));
  assert(await page.evaluate(() => originalStars === document.querySelector(".galaxy svg")));
  assert(await page.evaluate(() => originalFocus === document.getElementById("panel-focus")));
  await writeFile(ledger, content("New overview work"));
  await page.waitForFunction(() => !document.getElementById("panel-waiting"));
  assert(await page.evaluate(() => originalFocus === document.getElementById("panel-focus")));
  assert.equal(navigations, 2);
  assert.deepEqual(errors, []);
  console.log("PASS: real HTTP/CSP, automatic updates, stable DOM and scroll, text-selection/hidden-tab pauses, failure retention, recovery and manual refresh without navigation");
} finally {
  await browser?.close();
  server.kill();
  await new Promise(resolve => server.exitCode !== null ? resolve() : server.once("exit", resolve));
  await rm(root, {recursive: true, force: true});
}
