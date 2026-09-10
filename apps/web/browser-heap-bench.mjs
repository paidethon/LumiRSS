// Browser heap benchmark against REAL BFF data (46 feeds / 4.3k entries).
// Research-only tool. Phases: load, paginated deep scroll (inner container),
// searches, 20 article opens + back, settle. JS heap / DOM / listeners.
// Run: node browser-heap-bench.mjs
import { chromium } from "@playwright/test";

const BASE = "http://127.0.0.1:4174";
const scrollList = () =>
  page.evaluate(() => {
    const els = [...document.querySelectorAll("*")].filter(
      (e) => e.scrollHeight > e.clientHeight + 50,
    );
    els.sort((a, b) => b.scrollHeight - a.scrollHeight);
    if (els[0]) els[0].scrollTop += 2500;
    return els[0] ? els[0].scrollTop : 0;
  });

let page, cdp;
const sample = async () => {
  const m = (await cdp.send("Performance.getMetrics")).metrics;
  const get = (n) => m.find((x) => x.name === n)?.value ?? 0;
  return {
    jsHeapMB: Math.round((get("JSHeapUsedSize") / 1048576) * 10) / 10,
    domNodes: get("Nodes"),
    listeners: get("JSEventListeners"),
  };
};

async function main() {
  const browser = await chromium.launch();
  page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");

  const log = [];
  const mark = async (phase) => {
    const s = await sample();
    log.push({ phase, ...s });
    console.log(`${phase.padEnd(24)} heap=${s.jsHeapMB}MB dom=${s.domNodes} listeners=${s.listeners}`);
  };

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(2500);
  await mark("M0 loaded(real 46 feeds)");

  // deep scroll inside the timeline container (pagination fires)
  for (let i = 0; i < 15; i++) {
    await scrollList();
    await page.waitForTimeout(400);
  }
  await page.waitForTimeout(1500);
  await mark("M1 deep-scroll(paginated)");

  // search flow
  try {
    await page.locator("button", { hasText: "搜索" }).first().click();
    await page.waitForTimeout(800);
    const input = page.locator("input:visible").first();
    if ((await input.count()) > 0) {
      for (const q of ["AI", "LLM", "agent", "model", "research"]) {
        await input.fill(q);
        await page.waitForTimeout(700);
      }
      await input.fill("");
      await page.waitForTimeout(600);
      await page.keyboard.press("Escape");
    }
  } catch { /* honest skip */ }
  await page.waitForTimeout(800);
  await mark("M2 after-5-searches");

  // open 20 articles via real clicks on visible cards
  let opened = 0;
  for (let i = 0; i < 20; i++) {
    try {
      const card = page
        .locator("button:visible")
        .filter({ hasText: /·/ })
        .filter({ hasText: /2026\/|2025\// })
        .first();
      await card.click({ timeout: 4000 });
      await page.waitForTimeout(700);
      const url = page.url();
      const readerVisible = await page
        .locator("article, [class*=reader], h1")
        .first()
        .isVisible()
        .catch(() => false);
      if (readerVisible || /entry|article/i.test(url)) {
        opened++;
        await page.keyboard.press("Escape");
        await page.waitForTimeout(200);
        const back = page.locator("button:visible", { hasText: /返回|back/i }).first();
        if ((await back.count()) > 0) await back.click({ timeout: 1500 }).catch(() => {});
        else await page.goBack().catch(() => {});
        await page.waitForTimeout(500);
      }
    } catch { break; }
  }
  await page.waitForTimeout(1500);
  console.log(`articles opened: ${opened}`);
  await mark(`M3 after-${opened}-articles`);

  await page.waitForTimeout(5000);
  await cdp.send("HeapProfiler.collectGarbage").catch(() => {});
  await page.waitForTimeout(1000);
  await mark("M4 settled(GC)");
  console.log("\nJSON:", JSON.stringify(log));
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
