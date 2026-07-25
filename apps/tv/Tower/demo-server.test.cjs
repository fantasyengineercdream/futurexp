const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const { createDemoServer } = require("./demo-server.cjs");

function listen(server) {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

test("serves the tower and proxies the day-loop endpoint on one origin", async () => {
  const upstream = http.createServer((request, response) => {
    assert.equal(request.method, "POST");
    assert.equal(request.url, "/api/living-world/day-loop-runs");
    response.writeHead(201, { "content-type": "application/json" });
    response.end(JSON.stringify({ schemaVersion: "0.1", runId: "proxied" }));
  });
  const upstreamPort = await listen(upstream);
  const demo = createDemoServer({
    rootDir: path.join(__dirname),
    apiBaseUrl: `http://127.0.0.1:${upstreamPort}`
  });
  const demoPort = await listen(demo);

  try {
    const page = await fetch(`http://127.0.0.1:${demoPort}/`);
    assert.equal(page.status, 200);
    assert.match(await page.text(), /OC TV TOWER/);

    const api = await fetch(
      `http://127.0.0.1:${demoPort}/api/living-world/day-loop-runs`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          origin: "http://127.0.0.1:4174"
        },
        body: JSON.stringify({ seed: "frontend-day-loop" })
      }
    );
    assert.equal(api.status, 201);
    assert.equal(
      api.headers.get("access-control-allow-origin"),
      "http://127.0.0.1:4174"
    );
    assert.deepEqual(await api.json(), {
      schemaVersion: "0.1",
      runId: "proxied"
    });
  } finally {
    await close(demo);
    await close(upstream);
  }
});

test("production worker permits the locked Room app to call the owner API", () => {
  const workerPath = path.join(__dirname, "_worker.js");
  const serverPath = path.join(__dirname, "demo-server.cjs");
  assert.ok(
    fs.existsSync(workerPath),
    "Tower/_worker.js must be the versioned production proxy source"
  );
  const worker = fs.readFileSync(workerPath, "utf8");
  const server = fs.readFileSync(serverPath, "utf8");

  assert.match(worker, /https:\/\/oc-voice\.open\.smn\.icu/);
  assert.doesNotMatch(worker, /https:\/\/oocc-room-demo\.pages\.dev/);
  assert.match(server, /https:\/\/oc-voice\.open\.smn\.icu/);
  assert.doesNotMatch(server, /https:\/\/oocc-room-demo\.pages\.dev/);
  assert.match(worker, /request\.method === "OPTIONS"/);
  assert.match(worker, /url\.pathname\.startsWith\("\/api\/"\)/);
  assert.doesNotMatch(worker, /url\.pathname\.startsWith\("\/api\/living-world\/"\)/);
  assert.match(worker, /access-control-allow-origin/);
  assert.match(worker, /access-control-allow-methods/);
});
