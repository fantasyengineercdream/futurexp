const fs = require("node:fs");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png"
};

const roomOrigins = new Set([
  "http://127.0.0.1:4174",
  "http://localhost:4174",
  "https://oc-voice.open.smn.icu"
]);

function corsHeaders(request) {
  const origin = request.headers.origin;
  if (!roomOrigins.has(origin)) return {};
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-headers": "content-type",
    "access-control-allow-methods": "GET, POST, OPTIONS",
    vary: "Origin"
  };
}

function proxyApi(request, response, apiBaseUrl) {
  const target = new URL(request.url, apiBaseUrl);
  const client = target.protocol === "https:" ? https : http;
  const upstream = client.request(
    target,
    {
      method: request.method,
      headers: { ...request.headers, host: target.host }
    },
    (upstreamResponse) => {
      response.writeHead(
        upstreamResponse.statusCode || 502,
        { ...upstreamResponse.headers, ...corsHeaders(request) }
      );
      upstreamResponse.pipe(response);
    }
  );
  upstream.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "text/plain; charset=utf-8" });
    }
    response.end("Living World API unavailable");
  });
  request.pipe(upstream);
}

function serveStatic(request, response, rootDir) {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url, "http://demo.local").pathname);
  } catch {
    response.writeHead(400).end();
    return;
  }
  const relativePath = pathname === "/" ? "index.html" : pathname.slice(1);
  const resolvedRoot = path.resolve(rootDir);
  const filePath = path.resolve(resolvedRoot, relativePath);
  if (!filePath.startsWith(`${resolvedRoot}${path.sep}`)) {
    response.writeHead(403).end();
    return;
  }
  fs.stat(filePath, (error, stats) => {
    if (error || !stats.isFile()) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, {
      "content-type":
        contentTypes[path.extname(filePath).toLowerCase()] ||
        "application/octet-stream"
    });
    fs.createReadStream(filePath).pipe(response);
  });
}

function createDemoServer({
  rootDir = __dirname,
  apiBaseUrl = "http://127.0.0.1:8000"
} = {}) {
  return http.createServer((request, response) => {
    if (request.url.startsWith("/api/")) {
      if (request.method === "OPTIONS") {
        response.writeHead(204, corsHeaders(request)).end();
        return;
      }
      proxyApi(request, response, apiBaseUrl);
      return;
    }
    serveStatic(request, response, rootDir);
  });
}

if (require.main === module) {
  const port = Number(process.env.PORT || 5177);
  const apiBaseUrl =
    process.env.TV_DEMO_API_BASE ||
    "http://127.0.0.1:8000";
  createDemoServer({ apiBaseUrl }).listen(port, "127.0.0.1", () => {
    console.log(`TV Demo: http://127.0.0.1:${port}`);
    console.log(`Living World API: ${apiBaseUrl}`);
  });
}

module.exports = { createDemoServer };
