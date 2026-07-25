import { describe, expect, test } from "vitest";
import {
  buildInnerOsDeviceEvent,
  buildInnerOsRequest,
  fallbackInnerOs,
  generateInnerOs,
  normalizeInnerOs,
  parseInnerOsDecisionContext,
  parseInnerOsCompletion,
  parseInnerOsDecisionFrame,
  PendingInnerOsDecision,
} from "../relay-worker/src/inner-os";

describe("private inner OS generation", () => {
  test("uses the fast Step Plan model with a strict short-output prompt", () => {
    const request = buildInnerOsRequest({
      character: "devil",
      userText: "你是不是一直在等我？",
      publicText: "谁会等你呀，我只是刚好在这里。",
    });

    expect(request.model).toBe("step-3.7-flash");
    expect(request.reasoning_effort).toBe("low");
    expect(request.max_tokens).toBeLessThanOrEqual(64);
    expect(request.messages[0]?.content).toContain("最多 24 个字符");
    expect(request.messages[0]?.content).toContain("不要复述角色公开回答");
    expect(request.messages[1]?.content).toContain("你是不是一直在等我");
    expect(request.messages[1]?.content).toContain("谁会等你呀");
  });

  test("removes labels, quotes and line breaks before enforcing 24 characters", () => {
    expect(
      normalizeInnerOs(
        "内心OS：\n“才、才不是因为担心你才一直留在这里的啦！”",
        "devil",
      ),
    ).toBe("才、才不是因为担心你才一直留在这里的啦");

    expect(
      Array.from(
        normalizeInnerOs("这是一句明显超过墨水屏限制的特别特别特别长的内心独白", "angel"),
      ),
    ).toHaveLength(24);
  });

  test("returns persona fallbacks for empty or malformed completions", () => {
    expect(normalizeInnerOs("", "devil")).toBe(fallbackInnerOs("devil"));
    expect(normalizeInnerOs("内心OS：", "angel")).toBe(
      fallbackInnerOs("angel"),
    );
  });

  test("reads only public message content and never reasoning fields", () => {
    expect(
      parseInnerOsCompletion(
        {
          choices: [
            {
              message: {
                content: "别误会，我只是顺手。",
                reasoning: "private chain of thought",
              },
            },
          ],
        },
        "angel",
      ),
    ).toBe("别误会，我只是顺手。");
  });

  test("uses optional decision context to express the character's true disposition", () => {
    const request = buildInnerOsRequest({
      character: "angel",
      userText: "要不要相信主人这次的建议？",
      publicText: "我会自己判断。",
      decisionContext: {
        disposition: "partiallyAccepted",
        reason: "建议方向有用，但她不愿完全交出决定权。",
        relevantMemorySummaries: [
          "主人上次的建议避免了一次巡查。",
          "她仍介意主人曾替她擅自做决定。",
        ],
        episodeRef: "episode-004",
      },
    });

    expect(request.messages[0]?.content).toContain(
      "不要输出分析、理由或思维过程",
    );
    expect(request.messages[1]?.content).toContain("部分接受");
    expect(request.messages[1]?.content).toContain(
      "不愿完全交出决定权",
    );
    expect(request.messages[1]?.content).toContain("episode-004");
    expect(request.messages[1]?.content).toContain(
      "主人上次的建议避免了一次巡查",
    );
  });

  test("keeps the existing prompt unchanged when decision context is absent", () => {
    const request = buildInnerOsRequest({
      character: "devil",
      userText: "今天要出去吗？",
      publicText: "外面才没什么好怕的。",
    });

    expect(request.messages[0]?.content).not.toContain("可选决策上下文");
    expect(request.messages[1]?.content).not.toContain("主人建议裁定");
    expect(request.messages[1]?.content).not.toContain("关联事件");
  });

  test("accepts only the three frozen advice dispositions", () => {
    expect(
      parseInnerOsDecisionContext({
        disposition: "accepted",
        reason: "她认同这个建议。",
        relevantMemorySummaries: ["主人曾经兑现承诺。"],
        episodeRef: "episode-005",
      }),
    ).toEqual({
      disposition: "accepted",
      reason: "她认同这个建议。",
      relevantMemorySummaries: ["主人曾经兑现承诺。"],
      episodeRef: "episode-005",
    });
    expect(parseInnerOsDecisionContext(undefined)).toBeUndefined();
    expect(() =>
      parseInnerOsDecisionContext({
        disposition: "undecided",
      }),
    ).toThrow("invalid_decision_context");
  });

  test("keeps owner decision context for exactly the next private OS turn", () => {
    const pending = new PendingInnerOsDecision();
    const context = {
      disposition: "rejected" as const,
      reason: "这违背了她的底线。",
      episodeRef: "memory:day-1:oc-angel",
    };

    pending.set(context);

    expect(pending.take()).toEqual(context);
    expect(pending.take()).toBeUndefined();
  });

  test("accepts only the dedicated owner decision websocket frame", () => {
    expect(
      parseInnerOsDecisionFrame({
        type: "oc.decision_context",
        decisionContext: {
          disposition: "accepted",
          episodeRef: "memory:day-1:oc-angel",
        },
      }),
    ).toEqual({
      disposition: "accepted",
      episodeRef: "memory:day-1:oc-angel",
    });
    expect(
      parseInnerOsDecisionFrame({
        type: "conversation.item.create",
        decisionContext: { disposition: "accepted" },
      }),
    ).toBeUndefined();
  });

  test("marks fallback delivery without leaking decision context", () => {
    const event = buildInnerOsDeviceEvent(
      "devil",
      {
        text: fallbackInnerOs("devil"),
        source: "fallback",
      },
      "inner_test",
    );

    expect(event).toEqual({
      type: "oc.inner_os",
      event_id: "inner_test",
      character: "devil",
      text: fallbackInnerOs("devil"),
      max_characters: 24,
      source: "fallback",
    });
    expect(event).not.toHaveProperty("decisionContext");
    expect(event).not.toHaveProperty("reason");
    expect(event).not.toHaveProperty("relevantMemorySummaries");
    expect(event).not.toHaveProperty("episodeRef");
  });

  test("marks a valid model completion as model even when its text matches the fallback phrase", async () => {
    const fetcher = async () =>
      Response.json({
        choices: [
          {
            message: {
              content: fallbackInnerOs("devil"),
            },
          },
        ],
      });

    await expect(
      generateInnerOs(
        "test-key",
        {
          character: "devil",
          userText: "你在等我吗？",
          publicText: "才没有。",
        },
        fetcher,
      ),
    ).resolves.toEqual({
      text: fallbackInnerOs("devil"),
      source: "model",
    });
  });

  test("marks malformed model output as fallback", async () => {
    const fetcher = async () => Response.json({ choices: [] });

    await expect(
      generateInnerOs(
        "test-key",
        {
          character: "angel",
          userText: "接受我的建议吗？",
          publicText: "我会考虑。",
        },
        fetcher,
      ),
    ).resolves.toEqual({
      text: fallbackInnerOs("angel"),
      source: "fallback",
    });
  });
});
