// PoC 11-tags-graph: Cytoscape.js knowledge-graph rendering benchmark at
// 100 / 500 / 2000 nodes — initial layout time, interaction FPS, JS heap.
// Run: node poc_graph.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
const require = createRequire("/home/zephyr/projects/LumiRSS/apps/web/package.json");
const { chromium } = require("@playwright/test");

const CYTO_JS = readFileSync(new URL("./cytoscape.min.js", import.meta.url), "utf-8");
const SIZES = [100, 500, 2000];

const pageHtml = `<!doctype html><html><head><script src="http://poc.local/cy.js"><\/script></head>
<body><div id="cy" style="width:900px;height:700px"></div></body></html>`;

function graphJson(n) {
  const els = [];
  for (let i = 0; i < n; i++) els.push({ data: { id: `n${i}`, label: `Note ${i}` } });
  for (let i = 0; i < n; i++) {
    els.push({ data: { id: `e${i}a`, source: `n${i}`, target: `n${(i + 1) % n}` } });
    els.push({ data: { id: `e${i}b`, source: `n${i}`, target: `n${(i * 7 + 3) % n}` } });
  }
  return els;
}

const b = await chromium.launch();
const pg = await (await b.newContext()).newPage();
await pg.route("http://poc.local/cy.js", (route) =>
  route.fulfill({ contentType: "application/javascript", body: CYTO_JS }));
await pg.route("http://poc.local/", (route) =>
  route.fulfill({ contentType: "text/html", body: pageHtml }));
await pg.goto("http://poc.local/");
await pg.waitForFunction(() => typeof window.cytoscape === "function", null, { timeout: 30000 });

const results = [];
for (const n of SIZES) {
  const els = graphJson(n);
  const r = await pg.evaluate(async (graph) => {
    const n = graph.nodes;
    const t0 = performance.now();
    const cy = cytoscape({
      container: document.getElementById("cy"),
      elements: graph.els,
      style: [{ selector: "node", style: { label: "data(label)", "font-size": 6, width: 12, height: 12 } },
              { selector: "edge", style: { width: 1, "line-color": "#bbb" } }],
      layout: { name: "grid", rows: Math.ceil(Math.sqrt(n)) },
    });
    const layoutMs = Math.round(performance.now() - t0);
    let frames = 0;
    const start = performance.now();
    const tick = () => { frames++; if (performance.now() - start < 2500) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    for (let z = 0; z < 25; z++) { cy.zoom(z % 2 ? 1.15 : 0.87); cy.panBy({ x: 8, y: -5 }); await new Promise(r => setTimeout(r, 80)); }
    await new Promise(r => setTimeout(r, 800));
    const fps = Math.round(frames / ((performance.now() - start) / 1000));
    const mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null;
    cy.destroy();
    return { n: graph.nodes, layoutMs, fps, heapMB: mem };
  }, { els, nodes: n });
  results.push(r);
  console.log(`nodes=${r.n}  layout=${r.layoutMs}ms  interactionFPS=${r.fps}  heap=${r.heapMB}MB`);
}
console.log("\nJSON:", JSON.stringify(results));
await b.close();
