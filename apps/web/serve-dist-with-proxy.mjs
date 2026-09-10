// Minimal static file server for dist/ with /api proxy to the dev BFF.
// Research-only tool: not part of the app build or CI.
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const DIST = new URL("./dist", import.meta.url).pathname;
const BFF = "http://127.0.0.1:8000";
const MIME = {
  ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
  ".svg": "image/svg+xml", ".json": "application/json", ".webmanifest": "application/manifest+json",
  ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
};

http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    if (url.pathname.startsWith("/api/")) {
      const proxied = await fetch(BFF + url.pathname + url.search, {
        method: req.method,
        headers: { accept: req.headers.accept ?? "*/*" },
      });
      res.writeHead(proxied.status, Object.fromEntries(proxied.headers));
      res.end(Buffer.from(await proxied.arrayBuffer()));
      return;
    }
    let p = normalize(url.pathname).replace(/^(\.\.[/\\])+/, "");
    if (p === "/" || p === "\\") p = "/index.html";
    let file = join(DIST, p);
    try {
      await readFile(file);
    } catch {
      file = join(DIST, "index.html"); // SPA fallback
    }
    const body = await readFile(file);
    res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
    res.end(body);
  } catch (e) {
    res.writeHead(500); res.end(String(e));
  }
}).listen(4174, () => console.log("static+proxy on :4174"));
