// Playwright driver for the agent PoC: asks, approves, collects the log.
// Run: node agent_driver.mjs
import { createRequire } from "node:module";
const require = createRequire("/home/zephyr/projects/LumiRSS/apps/web/package.json");
const { chromium } = require("@playwright/test");

const b = await chromium.launch();
const pg = await (await b.newContext()).newPage();
await pg.goto("http://127.0.0.1:18901/");
await pg.click("#ask");
await pg.waitForSelector(".approval", { state: "visible", timeout: 60000 });
const buttons = await pg.$$(".approval button");
await buttons[0].click(); // 批准
await pg.waitForFunction(
  "[...document.querySelectorAll('#log div')].some(m=>m.textContent.includes('完成'))",
  null,
  { timeout: 60000 },
);
const log = await pg.$$eval("#log div", (els) => els.map((e) => e.className + ": " + e.textContent));
await b.close();
console.log(JSON.stringify(log, null, 1));
