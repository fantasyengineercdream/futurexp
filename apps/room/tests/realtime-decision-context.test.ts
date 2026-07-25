import { describe, expect, it } from "vitest";
import { buildDecisionContextEvent } from "../src/realtime";

describe("owner decision context handoff", () => {
  it("sends only the frozen one-shot context to the active voice session", () => {
    expect(
      buildDecisionContextEvent({
        disposition: "partiallyAccepted",
        reason: "建议有用，但决定权仍属于她。",
        relevantMemorySummaries: ["我记得主人上一次提醒过我。"],
        episodeRef: "memory:day-1:oc-angel",
      }),
    ).toEqual({
      type: "oc.decision_context",
      decisionContext: {
        disposition: "partiallyAccepted",
        reason: "建议有用，但决定权仍属于她。",
        relevantMemorySummaries: ["我记得主人上一次提醒过我。"],
        episodeRef: "memory:day-1:oc-angel",
      },
    });
  });
});
