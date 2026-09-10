// PoC 01-web-clipping: URL -> Readability extraction -> sanitized HTML ->
// Markdown -> LibraryItem draft, on 5 real-world sites of differing shapes.
// Run (from apps/web so node resolves packages): node poc_clipping.mjs
import { createRequire } from "node:module";
const require = createRequire("/home/zephyr/projects/LumiRSS/apps/web/package.json");
const { JSDOM } = require("jsdom");
const { Readability } = require("@mozilla/readability");
const sanitizeHtml = require("sanitize-html");
const TurndownService = require("turndown");

const SITES = [
  { kind: "plain blog", url: "https://lucumr.pocoo.org/2026/9/7/astra-why/" },
  { kind: "code blog", url: "https://simonwillison.net/2026/Sep/10/calif-research/" },
  { kind: "news (heavy)", url: "https://www.theverge.com/ai-artificial-intelligence" },
  { kind: "research listing", url: "https://machinelearning.apple.com/research" },
  { kind: "docs-ish JS site", url: "https://blog.vllm.ai/2025/01/27/v1-alpha-release.html" },
];

const SANITIZE = {
  allowedTags: ["p", "br", "b", "i", "em", "strong", "h1", "h2", "h3", "h4",
    "ul", "ol", "li", "blockquote", "pre", "code", "a", "img", "figure",
    "figcaption", "table", "thead", "tbody", "tr", "th", "td", "hr"],
  allowedAttributes: {
    a: ["href", "title", "rel", "target"],
    img: ["src", "alt", "width", "height", "loading"],
  },
  allowedSchemes: ["http", "https", "mailto"],
  allowedSchemesByTag: { img: ["http", "https", "data"] },
};

async function clip(url) {
  const t0 = performance.now();
  const res = await fetch(url, { headers: { "user-agent": "Mozilla/5.0 (compatible; LumiRSS-PoC/1.0)" } });
  const html = await res.text();
  const fetchMs = Math.round(performance.now() - t0);
  const doc = new JSDOM(html, { url }).window.document;
  const article = new Readability(doc.cloneNode(true)).parse();
  if (!article) throw new Error("readability: no article");
  const clean = sanitizeHtml(article.content || "", SANITIZE);
  const md = new TurndownService({ headingStyle: "atx", codeBlockStyle: "fenced" }).turndown(clean);
  return {
    httpStatus: res.status,
    fetchMs,
    rawKB: Math.round(html.length / 1024),
    title: (article.title || "").slice(0, 70),
    byline: article.byline || null,
    excerpt: (article.excerpt || "").slice(0, 60),
    cleanKB: Math.round(clean.length / 1024),
    mdKB: Math.round(md.length / 1024),
    mdHead: md.slice(0, 110).replace(/\n+/g, " ¶ "),
    links: (clean.match(/<a /g) || []).length,
    images: (clean.match(/<img /g) || []).length,
  };
}

const rows = [];
for (const s of SITES) {
  try {
    const r = await clip(s.url);
    rows.push({ kind: s.kind, url: s.url, ...r });
    console.log(`[${s.kind}] ${r.httpStatus} ${r.fetchMs}ms raw=${r.rawKB}KB clean=${r.cleanKB}KB md=${r.mdKB}KB a=${r.links} img=${r.images} :: ${r.title}`);
  } catch (e) {
    rows.push({ kind: s.kind, url: s.url, error: String(e).slice(0, 140) });
    console.log(`[${s.kind}] FAIL ${String(e).slice(0, 140)}`);
  }
}
console.log("\nJSON:", JSON.stringify(rows, null, 1));
