const test = require("node:test");
const assert = require("node:assert/strict");

const {
  counselActor,
  episodeRefForActor,
  fetchActorJournal
} = require("./living-memory-client.js");

const dayOne = {
  runId: "living-day-demo",
  dayIndex: 1,
  memoryRefs: [
    {
      actorId: "oc-angel",
      memoryRef: "memory:day-1:oc-angel",
      available: true
    },
    {
      actorId: "oc-devil",
      memoryRef: "memory:day-1:oc-devil",
      available: true
    }
  ]
};

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    }
  };
}

test("selects only the requested actor's available Day 1 episode", () => {
  assert.equal(
    episodeRefForActor(dayOne, "oc-angel"),
    "memory:day-1:oc-angel"
  );
  assert.throws(
    () =>
      episodeRefForActor(
        {
          ...dayOne,
          memoryRefs: [
            {
              actorId: "oc-angel",
              memoryRef: "memory:day-1:oc-angel",
              available: false
            }
          ]
        },
        "oc-angel"
      ),
    /No available episode/
  );
});

test("posts owner counsel and exposes only the public receipt", async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url: String(url), options };
    return jsonResponse(
      {
        counselId: "counsel:demo",
        actorId: "oc-angel",
        episodeRef: "memory:day-1:oc-angel",
        adviceId: "verify-before-judging",
        disposition: "accepted",
        reason: "private decision context",
        publicReply: "我会认真考虑，但仍由我自己决定。",
        privateOsAvailable: true,
        privateOsRef: "private-os-context:counsel:demo",
        decisionProvider: "deterministic-counsel-v1"
      },
      201
    );
  };

  const result = await counselActor(
    fetchImpl,
    "http://127.0.0.1:5177/",
    "living-day-demo",
    "oc-angel",
    {
      episodeRef: "memory:day-1:oc-angel",
      adviceId: "verify-before-judging",
      adviceText: "明天先核对证据，再判断别人。",
      recommendationKind: "verifyEvidence"
    }
  );

  assert.equal(
    request.url,
    "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/counsel"
  );
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(request.options.body), {
    episodeRef: "memory:day-1:oc-angel",
    adviceId: "verify-before-judging",
    adviceText: "明天先核对证据，再判断别人。",
    recommendationKind: "verifyEvidence"
  });
  assert.deepEqual(result, {
    actorId: "oc-angel",
    episodeRef: "memory:day-1:oc-angel",
    adviceId: "verify-before-judging",
    disposition: "accepted",
    publicReply: "我会认真考虑，但仍由我自己决定。"
  });
  assert.equal("privateOsRef" in result, false);
  assert.equal("reason" in result, false);
});

test("rejects a counsel receipt for another actor", async () => {
  const fetchImpl = async () =>
    jsonResponse(
      {
        actorId: "oc-devil",
        episodeRef: "memory:day-1:oc-devil",
        adviceId: "verify-before-judging",
        disposition: "accepted",
        publicReply: "wrong actor"
      },
      201
    );

  await assert.rejects(
    counselActor(
      fetchImpl,
      "http://127.0.0.1:5177/",
      "living-day-demo",
      "oc-angel",
      {
        episodeRef: "memory:day-1:oc-angel",
        adviceId: "verify-before-judging",
        adviceText: "明天先核对证据，再判断别人。",
        recommendationKind: "verifyEvidence"
      }
    ),
    /Counsel identity mismatch/
  );
});

test("fetches one actor journal and strips every non-product field", async () => {
  let request;
  const fetchImpl = async (url, options) => {
    request = { url: String(url), options };
    return jsonResponse({
      schemaVersion: "0.1",
      runId: "living-day-demo",
      actorId: "oc-angel",
      updatedDayIndex: 1,
      entries: [
        {
          episodeRef: "memory:day-1:oc-angel",
          dayIndex: 1,
          title: "第一天",
          story: "我只记下自己真正经历的部分。",
          changes: ["我决定明天先核对证据。"],
          sourceEventIds: ["forbidden"],
          privateOsRef: "forbidden"
        }
      ]
    });
  };

  const result = await fetchActorJournal(
    fetchImpl,
    "http://127.0.0.1:5177/",
    "living-day-demo",
    "oc-angel"
  );

  assert.equal(
    request.url,
    "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/journal"
  );
  assert.equal(request.options.method, "GET");
  assert.deepEqual(result, [
    {
      episodeRef: "memory:day-1:oc-angel",
      dayIndex: 1,
      title: "第一天",
      story: "我只记下自己真正经历的部分。",
      changes: ["我决定明天先核对证据。"]
    }
  ]);
  assert.equal("sourceEventIds" in result[0], false);
  assert.equal("privateOsRef" in result[0], false);
});
