import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("C:/Users/jimygong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");
const root = process.cwd();
const file = pathToFileURL(path.join(root, "docs", "demo", "aoe3-balance-20260917", "index.html")).href;
const browser = await chromium.launch({ headless: true });

async function inspect(name, viewport) {
  const page = await browser.newPage();
  await page.setViewportSize(viewport);
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  await page.goto(file, { waitUntil: "load" });
  await page.waitForTimeout(700);

  const state = await page.evaluate(() => {
    const cards = [...document.querySelectorAll(".change-card")];
    const body = document.body;
    const doc = document.documentElement;
    const rect = body.getBoundingClientRect();
    return {
      title: document.title,
      cards: cards.length,
      kpis: document.querySelectorAll(".kpi").length,
      chartBars: document.querySelectorAll("#delta-chart rect").length,
      addedRows: document.querySelectorAll("#added-body tr").length,
      removedRows: document.querySelectorAll("#removed-body tr").length,
      bodyScrollWidth: body.scrollWidth,
      bodyClientWidth: doc.clientWidth,
      visibleText: body.innerText.slice(0, 120),
      firstCard: cards[0]?.innerText?.slice(0, 180),
      missingIcons: [...document.images].filter(img => !img.complete || img.naturalWidth === 0).length,
      bodyRect: { width: rect.width, height: rect.height },
    };
  });

  await page.locator("#search").fill("利普卡");
  await page.waitForTimeout(80);
  const filtered = await page.locator(".change-card").count();
  const filteredText = await page.locator(".change-card").first().innerText();
  await page.locator("#search").fill("");
  await page.locator("#direction").selectOption("buff");
  await page.waitForTimeout(80);
  const buffs = await page.locator(".change-card").count();
  await page.locator("#direction").selectOption("struct");
  await page.locator("#impact").selectOption("mechanic");
  await page.waitForTimeout(80);
  const mechanicBuffs = await page.locator(".change-card").count();

  await page.screenshot({ path: path.join(root, "docs", "demo", "aoe3-balance-20260917", `${name}.png`), fullPage: true });
  console.log(JSON.stringify({ name, viewport, state, filtered, filteredText: filteredText.slice(0, 120), buffs, mechanicBuffs, errors }, null, 2));
  await page.close();
}

await inspect("desktop", { width: 1440, height: 1000 });
await inspect("mobile", { width: 390, height: 844 });
await browser.close();
