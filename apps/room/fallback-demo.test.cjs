const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(
  path.join(__dirname, "public", "fallback-demo", "index.html"),
  "utf8",
);

test("fallback demo is explicit, deterministic, and network independent", () => {
  assert.match(source, /LOCAL FALLBACK · NO LLM/);
  assert.match(source, /SOURCE: DETERMINISTIC FALLBACK/);
  assert.match(source, /说出口的话/);
  assert.match(source, /没说出口的内心 OS/);
  assert.doesNotMatch(source, /fetch\(|WebSocket\(|EventSource\(/);
});

test("fallback demo supports both official OC examples", () => {
  assert.match(source, /value="angel"/);
  assert.match(source, /value="devil"/);
  assert.match(source, /angel-maid-pixel-v2\.webp/);
  assert.match(source, /devil-maid-pixel-v2\.webp/);
});
