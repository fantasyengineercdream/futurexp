const assert = require("node:assert/strict");
const test = require("node:test");

const {
  confirmOcImport,
  previewOcImport
} = require("./oc-import-client.js");

const uiRpgStats = {
  seriousness: 2,
  rebellion: 0,
  fitness: 5,
  inspiration: 1
};

const apiRpgStats = {
  intellect: 2,
  presence: 0,
  athletics: 5,
  insight: 1
};

const draft = {
  schemaVersion: "0.1",
  draftId: "oc-import-lan",
  suggestedOcId: "oc-imported-lan",
  status: "pendingConfirmation",
  canonical: false,
  source: {
    sourceName: "lan.md",
    contentHash: "a".repeat(64),
    excerpt: "岚会先核对证据。"
  },
  roleplayConfig: {
    displayName: "岚",
    role: "无限公寓住客",
    persona: "她会先核对证据。",
    publicStyle: "只说自己确认过的事"
  },
  livingWorldProfile: {
    personaConstraints: ["先核对证据"],
    goals: ["查明回声来源"],
    initialMemories: [],
    homeLocationId: "mirror-curtain",
    dailyLocationPreferences: ["apartment-library"]
  },
  rpgStats: uiRpgStats,
  compilerId: "deterministic-creator-source-v01",
  auditNotices: ["待用户确认"]
};

const registered = {
  schemaVersion: "0.1",
  ocId: "oc-imported-lan",
  status: "registered",
  source: draft.source,
  character: {
    ocId: "oc-imported-lan",
    name: "岚",
    role: "无限公寓住客",
    persona: "她会先核对证据。",
    publicStyle: "只说自己确认过的事",
    locationId: "mirror-curtain",
    goals: [{ goalId: "goal-oc-user-1", text: "查明回声来源" }],
    secrets: [],
    senses: ["sight", "hearing"],
    relationships: {}
  },
  runtimeProfile: {
    ocId: "oc-imported-lan",
    personaConstraints: ["先核对证据"],
    goalRefs: ["goal-oc-user-1"],
    initialMemories: [],
    actionPreferences: ["WAIT", "UTTERANCE", "MOVE"],
    homeLocationId: "mirror-curtain",
    dailyLocationPreferences: ["apartment-library"],
    rpgStats: apiRpgStats
  }
};

test("previews creator text through the real API without fixture fallback", async () => {
  const calls = [];
  const result = await previewOcImport(
    async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        json: async () => ({ ...draft, rpgStats: apiRpgStats })
      };
    },
    "https://demo.example/",
    { sourceName: "lan.md", sourceText: "岚\n她会先核对证据。" }
  );

  assert.equal(calls[0].url, "https://demo.example/api/oc-imports/preview");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    sourceName: "lan.md",
    sourceText: "岚\n她会先核对证据。"
  });
  assert.equal(result.draftId, "oc-import-lan");
  assert.equal(result.canonical, false);
  assert.deepEqual(result.rpgStats, uiRpgStats);
  assert.equal("intellect" in result.rpgStats, false);
});

test("rejects malformed preview responses instead of inventing a card", async () => {
  await assert.rejects(
    previewOcImport(
      async () => ({ ok: true, json: async () => ({ ...draft, canonical: true }) }),
      "https://demo.example/",
      { sourceName: "lan.md", sourceText: "岚" }
    ),
    /Invalid OC import preview/
  );
});

test("confirms exactly the reviewed draft and validates the registered slot", async () => {
  const calls = [];
  const result = await confirmOcImport(
    async (url, init) => {
      calls.push({ url, init });
      return {
        ok: true,
        json: async () => registered
      };
    },
    "https://demo.example/",
    draft
  );

  assert.equal(
    calls[0].url,
    "https://demo.example/api/oc-imports/oc-import-lan/confirm"
  );
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    roleplayConfig: draft.roleplayConfig,
    livingWorldProfile: draft.livingWorldProfile,
    rpgStats: apiRpgStats
  });
  assert.equal(result.ocId, "oc-imported-lan");
  assert.deepEqual(result.runtimeProfile.rpgStats, uiRpgStats);
  assert.equal("intellect" in result.runtimeProfile.rpgStats, false);
  assert.equal(result.character.name, "岚");
});

test("surfaces API errors and does not retry against a fixture", async () => {
  let callCount = 0;
  await assert.rejects(
    previewOcImport(
      async () => {
        callCount += 1;
        return {
          ok: false,
          status: 422,
          json: async () => ({
            code: "INVALID_REQUEST",
            message: "资料不能为空"
          })
        };
      },
      "https://demo.example/",
      { sourceName: "invalid.txt", sourceText: "内容由服务端判定无效" }
    ),
    /资料不能为空/
  );
  assert.equal(callCount, 1);
});
