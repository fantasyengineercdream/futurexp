(function exposeLivingMemoryClient(root, factory) {
  const client = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = client;
  }
  if (root) {
    root.LivingMemoryClient = client;
  }
})(
  typeof window === "undefined" ? globalThis : window,
  function createLivingMemoryClient() {
    const counselDispositions = new Set([
      "accepted",
      "partiallyAccepted",
      "rejected"
    ]);
    const recommendationKinds = new Set([
      "verifyEvidence",
      "seekDialogue",
      "avoidConflict",
      "takeRisk",
      "breakWorldRules",
      "other"
    ]);

    function requiredString(value, label) {
      if (typeof value !== "string" || value.trim() === "") {
        throw new Error(`Invalid ${label}`);
      }
      return value;
    }

    function endpoint(apiBaseUrl, runId, actorId, action) {
      const run = encodeURIComponent(requiredString(runId, "runId"));
      const actor = encodeURIComponent(requiredString(actorId, "actorId"));
      return new URL(
        `/api/living-world/day-loop-runs/${run}/owner/actors/${actor}/${action}`,
        apiBaseUrl
      );
    }

    async function responseJson(response, label) {
      if (!response || !response.ok) {
        throw new Error(
          `${label} failed (${response?.status || "unknown"})`
        );
      }
      return response.json();
    }

    function episodeRefForActor(dayLoopProjection, actorId) {
      requiredString(actorId, "actorId");
      if (!Array.isArray(dayLoopProjection?.memoryRefs)) {
        throw new Error("Invalid Day Loop memoryRefs");
      }
      const memory = dayLoopProjection.memoryRefs.find(
        (item) =>
          item?.actorId === actorId &&
          item.available === true &&
          typeof item.memoryRef === "string" &&
          item.memoryRef.length > 0
      );
      if (!memory) {
        throw new Error(`No available episode for actor: ${actorId}`);
      }
      return memory.memoryRef;
    }

    function validateCounselInput(input) {
      const result = {
        episodeRef: requiredString(input?.episodeRef, "episodeRef"),
        adviceId: requiredString(input?.adviceId, "adviceId"),
        adviceText: requiredString(input?.adviceText, "adviceText"),
        recommendationKind: requiredString(
          input?.recommendationKind,
          "recommendationKind"
        )
      };
      if (!recommendationKinds.has(result.recommendationKind)) {
        throw new Error("Invalid recommendationKind");
      }
      return result;
    }

    async function counselActor(
      fetchImpl,
      apiBaseUrl,
      runId,
      actorId,
      input
    ) {
      if (typeof fetchImpl !== "function") {
        throw new Error("A fetch implementation is required");
      }
      const request = validateCounselInput(input);
      const response = await fetchImpl(
        endpoint(apiBaseUrl, runId, actorId, "counsel"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request)
        }
      );
      const receipt = await responseJson(response, "Owner counsel");
      if (
        receipt?.actorId !== actorId ||
        receipt.episodeRef !== request.episodeRef ||
        receipt.adviceId !== request.adviceId
      ) {
        throw new Error("Counsel identity mismatch");
      }
      if (!counselDispositions.has(receipt.disposition)) {
        throw new Error("Invalid counsel disposition");
      }
      return {
        actorId,
        episodeRef: request.episodeRef,
        adviceId: request.adviceId,
        disposition: receipt.disposition,
        publicReply: requiredString(receipt.publicReply, "publicReply")
      };
    }

    function publicJournalEntry(entry) {
      if (
        !Number.isInteger(entry?.dayIndex) ||
        entry.dayIndex < 1 ||
        !Array.isArray(entry.changes) ||
        !entry.changes.every((change) => typeof change === "string")
      ) {
        throw new Error("Invalid owner journal entry");
      }
      return {
        episodeRef: requiredString(entry.episodeRef, "episodeRef"),
        dayIndex: entry.dayIndex,
        title: requiredString(entry.title, "journal title"),
        story: requiredString(entry.story, "journal story"),
        changes: [...entry.changes]
      };
    }

    async function fetchActorJournal(
      fetchImpl,
      apiBaseUrl,
      runId,
      actorId
    ) {
      if (typeof fetchImpl !== "function") {
        throw new Error("A fetch implementation is required");
      }
      const response = await fetchImpl(
        endpoint(apiBaseUrl, runId, actorId, "journal"),
        { method: "GET" }
      );
      const journal = await responseJson(response, "Owner journal");
      if (journal?.runId !== runId || journal.actorId !== actorId) {
        throw new Error("Journal identity mismatch");
      }
      if (!Array.isArray(journal.entries)) {
        throw new Error("Invalid owner journal");
      }
      return journal.entries.map(publicJournalEntry);
    }

    return {
      counselActor,
      episodeRefForActor,
      fetchActorJournal
    };
  }
);
