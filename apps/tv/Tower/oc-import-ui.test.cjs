const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = __dirname;
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");

test("tower exposes one accessible paste-or-text-file import dialog", () => {
  assert.match(html, /id="ocImportOpen"/);
  assert.match(html, /id="ocImportDialog"/);
  assert.match(html, /id="ocImportSourceText"/);
  assert.match(html, /accept="\.txt,\.md,text\/plain,text\/markdown"/);
  assert.doesNotMatch(html, /application\/pdf|image\/png|image\/jpeg/);
});

test("import stays draft-only until the user explicitly confirms it", () => {
  assert.match(html, /id="ocImportPreview"/);
  assert.match(html, /id="ocImportConfirm"/);
  assert.match(app, /OcImportClient\.previewOcImport/);
  assert.match(app, /OcImportClient\.confirmOcImport/);
  assert.match(app, /pendingOcDraft/);
  assert.match(app, /seriousness:\s*"认真"/);
  assert.match(app, /rebellion:\s*"叛逆"/);
  assert.match(app, /fitness:\s*"体能"/);
  assert.match(app, /inspiration:\s*"灵感"/);
  assert.doesNotMatch(app, /deterministicFixture|preview-import-/);
});

test("confirmed imported actors receive their own Room handoff", () => {
  assert.match(
    app,
    /residentId:\s*userOc\.actorId,[\s\S]*roomId:\s*"room-demo-user"/
  );
  assert.match(app, /episodeRef:\s*userMemory\?\.memoryRef/);
  assert.match(app, /roomUrl:\s*window\.TvRoomBridge\.buildRoomUrl/);
});
