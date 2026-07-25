(function exposeOcImportClient(root, factory) {
  const client = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = client;
  }
  if (root) {
    root.OcImportClient = client;
  }
})(typeof window === "undefined" ? globalThis : window, function createOcImportClient() {
  function isObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function isStringArray(value) {
    return Array.isArray(value) && value.every((item) => typeof item === "string");
  }

  const uiRpgKeys = [
    "seriousness",
    "rebellion",
    "fitness",
    "inspiration"
  ];
  const apiRpgKeyByUiKey = {
    seriousness: "intellect",
    rebellion: "presence",
    fitness: "athletics",
    inspiration: "insight"
  };

  function hasIntegerRpgKeys(value, keys) {
    return (
      isObject(value) &&
      keys.every(
        (key) =>
          Number.isInteger(value[key]) &&
          value[key] >= -2 &&
          value[key] <= 5
      )
    );
  }

  function normalizeRpgStats(value) {
    if (hasIntegerRpgKeys(value, uiRpgKeys)) {
      return Object.fromEntries(uiRpgKeys.map((key) => [key, value[key]]));
    }
    const apiKeys = Object.values(apiRpgKeyByUiKey);
    if (hasIntegerRpgKeys(value, apiKeys)) {
      return Object.fromEntries(
        uiRpgKeys.map((key) => [key, value[apiRpgKeyByUiKey[key]]])
      );
    }
    throw new Error("Invalid OC RPG stats");
  }

  function toApiRpgStats(value) {
    const uiStats = normalizeRpgStats(value);
    return Object.fromEntries(
      uiRpgKeys.map((key) => [apiRpgKeyByUiKey[key], uiStats[key]])
    );
  }

  function isSource(value) {
    return (
      isObject(value) &&
      typeof value.sourceName === "string" &&
      /^[0-9a-f]{64}$/.test(value.contentHash) &&
      typeof value.excerpt === "string"
    );
  }

  function isRoleplayConfig(value) {
    return (
      isObject(value) &&
      ["displayName", "role", "persona", "publicStyle"].every(
        (key) => typeof value[key] === "string" && value[key].trim().length > 0
      )
    );
  }

  function isLivingWorldProfile(value) {
    return (
      isObject(value) &&
      isStringArray(value.personaConstraints) &&
      value.personaConstraints.length > 0 &&
      isStringArray(value.goals) &&
      value.goals.length > 0 &&
      isStringArray(value.initialMemories) &&
      typeof value.homeLocationId === "string" &&
      isStringArray(value.dailyLocationPreferences) &&
      value.dailyLocationPreferences.length > 0
    );
  }

  function assertPreview(value) {
    if (
      !isObject(value) ||
      value.schemaVersion !== "0.1" ||
      typeof value.draftId !== "string" ||
      typeof value.suggestedOcId !== "string" ||
      value.status !== "pendingConfirmation" ||
      value.canonical !== false ||
      !isSource(value.source) ||
      !isRoleplayConfig(value.roleplayConfig) ||
      !isLivingWorldProfile(value.livingWorldProfile) ||
      typeof value.compilerId !== "string" ||
      !isStringArray(value.auditNotices)
    ) {
      throw new Error("Invalid OC import preview");
    }
    let rpgStats;
    try {
      rpgStats = normalizeRpgStats(value.rpgStats);
    } catch {
      throw new Error("Invalid OC import preview");
    }
    return { ...value, rpgStats };
  }

  function assertRegistered(value, expectedOcId) {
    if (
      !isObject(value) ||
      value.schemaVersion !== "0.1" ||
      value.status !== "registered" ||
      value.ocId !== expectedOcId ||
      !isSource(value.source) ||
      !isObject(value.character) ||
      value.character.ocId !== expectedOcId ||
      typeof value.character.name !== "string" ||
      !isObject(value.runtimeProfile) ||
      value.runtimeProfile.ocId !== expectedOcId
    ) {
      throw new Error("Invalid registered OC");
    }
    let rpgStats;
    try {
      rpgStats = normalizeRpgStats(value.runtimeProfile.rpgStats);
    } catch {
      throw new Error("Invalid registered OC");
    }
    return {
      ...value,
      runtimeProfile: {
        ...value.runtimeProfile,
        rpgStats
      }
    };
  }

  async function readError(response, fallback) {
    try {
      const body = await response.json();
      if (isObject(body) && typeof body.message === "string") {
        return body.message;
      }
    } catch {
      // Keep the stable product error below.
    }
    return fallback;
  }

  async function requestJson(fetcher, url, init, fallbackError) {
    let response;
    try {
      response = await fetcher(url, init);
    } catch {
      throw new Error("OC 导入服务暂时不可用，请稍后重试");
    }
    if (!response.ok) {
      throw new Error(await readError(response, fallbackError));
    }
    return response.json();
  }

  async function previewOcImport(fetcher, apiBaseUrl, source) {
    if (
      !source ||
      typeof source.sourceName !== "string" ||
      typeof source.sourceText !== "string" ||
      !source.sourceText.trim()
    ) {
      throw new Error("请粘贴或选择一份文字设定");
    }
    const result = await requestJson(
      fetcher,
      new URL("/api/oc-imports/preview", apiBaseUrl).toString(),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(source)
      },
      "角色草稿生成失败"
    );
    return assertPreview(result);
  }

  async function confirmOcImport(fetcher, apiBaseUrl, draft) {
    const checkedDraft = assertPreview(draft);
    const result = await requestJson(
      fetcher,
      new URL(
        `/api/oc-imports/${encodeURIComponent(checkedDraft.draftId)}/confirm`,
        apiBaseUrl
      ).toString(),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          roleplayConfig: checkedDraft.roleplayConfig,
          livingWorldProfile: checkedDraft.livingWorldProfile,
          rpgStats: toApiRpgStats(checkedDraft.rpgStats)
        })
      },
      "角色确认失败"
    );
    return assertRegistered(result, checkedDraft.suggestedOcId);
  }

  return {
    confirmOcImport,
    previewOcImport
  };
});
