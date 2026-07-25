import { describe, expect, it, vi } from "vitest";
import {
  OwnerAdviceConfirmation,
  OwnerConversationMemoryRecorder,
  advanceLivingWorldDay,
  adviceCandidateFromTranscript,
  counselCurrentOwner,
  loadCurrentOwnerJournal,
  ownerJournalSectionTitle,
  loadCurrentOwnerPrivateOsContext,
  recordOwnerConversationMemory,
  resolveOwnerLivingWorldContext,
  returnUrlWithDayLoopResume,
} from "../src/living-world";

const context = {
  apiBaseUrl: "http://127.0.0.1:5177/",
  runId: "living-day-demo",
  actorId: "oc-angel" as const,
  episodeRef: "memory:day-1:oc-angel",
  dayIndex: 1,
};

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("owner-safe living-world room loop", () => {
  it("accepts one imported owner only when its episode identity matches", () => {
    expect(
      resolveOwnerLivingWorldContext(
        "?residentId=oc-imported-lan&runId=living-day-demo"
          + "&episodeRef=memory%3Aday-1%3Aoc-imported-lan"
          + "&dayIndex=1"
          + "&livingWorldApi=https%3A%2F%2Fworld.example%2F",
      ),
    ).toMatchObject({
      actorId: "oc-imported-lan",
      episodeRef: "memory:day-1:oc-imported-lan",
    });
    expect(
      resolveOwnerLivingWorldContext(
        "?residentId=oc-imported-lan&runId=living-day-demo"
          + "&episodeRef=memory%3Aday-1%3Aoc-imported-other"
          + "&dayIndex=1"
          + "&livingWorldApi=https%3A%2F%2Fworld.example%2F",
      ),
    ).toBeNull();
  });

  it("accepts complete OO and CC owner contexts while rejecting crossed episodes", () => {
    expect(
      resolveOwnerLivingWorldContext(
        "?residentId=oc-angel&runId=living-day-demo" +
          "&episodeRef=memory%3Aday-1%3Aoc-angel" +
          "&dayIndex=1" +
          "&livingWorldApi=http%3A%2F%2F127.0.0.1%3A5177%2F",
      ),
    ).toEqual(context);
    expect(
      resolveOwnerLivingWorldContext(
        "?residentId=oc-devil&runId=living-day-demo" +
          "&episodeRef=memory%3Aday-1%3Aoc-devil" +
          "&dayIndex=1" +
          "&livingWorldApi=http%3A%2F%2F127.0.0.1%3A5177%2F",
      ),
    ).toEqual({
      ...context,
      actorId: "oc-devil",
      episodeRef: "memory:day-1:oc-devil",
    });
    expect(
      resolveOwnerLivingWorldContext(
        "?residentId=oc-angel&runId=living-day-demo" +
          "&episodeRef=memory%3Aday-1%3Aoc-devil" +
          "&dayIndex=1" +
          "&livingWorldApi=http%3A%2F%2F127.0.0.1%3A5177%2F",
      ),
    ).toBeNull();
  });

  it("recognizes only the narrow evidence-checking demo script", () => {
    expect(
      adviceCandidateFromTranscript(
        "明天先核对我真正看到的事实，再判断要不要相信他们。",
      ),
    ).toEqual({
      adviceText: "明天先核对我真正看到的事实，再判断要不要相信他们。",
      recommendationKind: "verifyEvidence",
    });
    expect(adviceCandidateFromTranscript("明天早点回来。")).toBeNull();
    expect(adviceCandidateFromTranscript("")).toBeNull();
  });

  it("posts the confirmed user wording and returns only the current owner's public disposition", async () => {
    const fetcher = vi.fn(async () =>
      response(
        {
          counselId: "counsel:demo",
          actorId: "oc-angel",
          episodeRef: "memory:day-1:oc-angel",
          adviceId: "conversation-day-1-verify-evidence",
          disposition: "accepted",
          reason: "internal",
          publicReply: "我会把这句话带到明天，再自己做决定。",
          privateOsAvailable: true,
          privateOsRef: "private-os-context:demo",
        },
        201,
      ),
    );

    await expect(
      counselCurrentOwner(fetcher, context, {
        adviceText: "先核对证据，再判断别人。",
        recommendationKind: "verifyEvidence",
      }),
    ).resolves.toEqual({
        counselId: "counsel:demo",
        disposition: "accepted",
        publicReply: "我会把这句话带到明天，再自己做决定。",
        privateOsRef: "private-os-context:demo",
      });
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/counsel",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          episodeRef: "memory:day-1:oc-angel",
          adviceId: "conversation-day-1-verify-evidence",
          adviceText: "先核对证据，再判断别人。",
          recommendationKind: "verifyEvidence",
        }),
      },
    );
  });

  it("records the confirmed owner's actual public and delivered private reply", async () => {
    const fetcher = vi.fn(async () =>
      response(
        {
          conversationId: "conversation:demo",
          actorId: "oc-angel",
          episodeRef: "memory:day-1:oc-angel",
          counselId: "counsel:demo",
          recorded: true,
        },
        201,
      ),
    );

    await expect(
      recordOwnerConversationMemory(fetcher, context, {
        counselId: "counsel:demo",
        userText: "明天先核对证据，再判断别人。",
        publicReply: "我会认真考虑。",
        privateInnerOs: "他说得对，但最后仍由我自己判断。",
      }),
    ).resolves.toEqual({
      conversationId: "conversation:demo",
      recorded: true,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/conversation-memory",
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          episodeRef: "memory:day-1:oc-angel",
          counselId: "counsel:demo",
          userText: "明天先核对证据，再判断别人。",
          publicReply: "我会认真考虑。",
          privateInnerOs: "他说得对，但最后仍由我自己判断。",
        }),
      },
    );
  });

  it("writes memory only after the current owner's delivered private OS", async () => {
    const recorder = new OwnerConversationMemoryRecorder(context);
    expect(recorder.awaitingDelivery).toBe(false);
    recorder.arm("counsel:demo", "明天先核对证据，再判断别人。");
    expect(recorder.awaitingDelivery).toBe(true);
    const submit = vi.fn(async () => ({
      conversationId: "conversation:demo",
      recorded: true as const,
    }));

    await expect(
      recorder.recordDelivery(
        {
          character: "devil",
          publicReply: "我会认真考虑。",
          privateInnerOs: "最后仍由我自己判断。",
        },
        submit,
      ),
    ).rejects.toThrow("Owner conversation memory actor mismatch");
    expect(submit).not.toHaveBeenCalled();

    await expect(
      recorder.recordDelivery(
        {
          character: "angel",
          publicReply: "我会认真考虑。",
          privateInnerOs: "最后仍由我自己判断。",
        },
        submit,
      ),
    ).resolves.toBe("recorded");
    expect(submit).toHaveBeenCalledWith({
      counselId: "counsel:demo",
      userText: "明天先核对证据，再判断别人。",
      publicReply: "我会认真考虑。",
      privateInnerOs: "最后仍由我自己判断。",
    });
    await expect(
      recorder.recordDelivery(
        {
          character: "angel",
          publicReply: "第二次回答",
          privateInnerOs: "第二次心声",
        },
        submit,
      ),
    ).resolves.toBe("ignored");
    expect(submit).toHaveBeenCalledTimes(1);
    expect(recorder.awaitingDelivery).toBe(false);
  });

  it("loads only the current owner's private decision context", async () => {
    const fetcher = vi.fn(async () =>
      response({
        actorId: context.actorId,
        episodeRef: context.episodeRef,
        disposition: "accepted",
        decisionReason: "这与她重视亲历证据的人设一致。",
        relevantMemorySummaries: ["我只记下自己亲眼看到的部分。"],
      }),
    );

    await expect(
      loadCurrentOwnerPrivateOsContext(
        fetcher,
        context,
        "private-os-context:counsel:demo",
      ),
    ).resolves.toEqual({
      disposition: "accepted",
      reason: "这与她重视亲历证据的人设一致。",
      relevantMemorySummaries: ["我只记下自己亲眼看到的部分。"],
      episodeRef: context.episodeRef,
    });
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/private-os-context?ref=private-os-context%3Acounsel%3Ademo",
      { method: "GET" },
    );
  });

  it("loads only the latest owner-safe journal entry", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: "oc-angel",
        runId: "living-day-demo",
        updatedDayIndex: 1,
        entries: [
          {
            episodeRef: "memory:day-1:oc-angel",
            dayIndex: 1,
            title: "第一天",
            story: "我只记下自己真正经历的部分。",
            changes: ["我接受了主人的建议。"],
            sourceEventIds: ["must-not-leak"],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toEqual({
      updatedDayIndex: 1,
      entries: [{
        episodeRef: "memory:day-1:oc-angel",
        dayIndex: 1,
        title: "第一天",
        story: "我只记下自己真正经历的部分。",
        changes: ["我接受了主人的建议。"],
        sections: [],
      }],
    });
  });

  it("keeps structured owner-safe journal sections without parsing the legacy story", async () => {
    const sections = [
      { kind: "scene", text: "公寓图书馆出现了一件需要共同处理的小插曲。" },
      { kind: "intent", text: "我决定优先保护同伴。" },
      { kind: "check", text: "灵感检定：D20 6 +4 = 10，对抗 DC 11，失败。" },
      { kind: "observation", text: "我亲眼看见恶魔 OC 的检定成功。" },
      { kind: "consequence", text: "我对恶魔 OC 的紧张增加了。" },
      { kind: "reflection", text: "我开始怀疑原来的判断。" },
      { kind: "ownerConversation", text: "昨夜，主人提醒我要先核对事实。" },
    ] as const;
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: context.actorId,
        runId: context.runId,
        updatedDayIndex: 1,
        entries: [{
          episodeRef: context.episodeRef,
          dayIndex: 1,
          title: "第一天",
          story: "兼容旧版本的完整故事，不用于前端拆句。",
          changes: ["我对恶魔 OC 的紧张增加了。"],
          sections,
        }],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toMatchObject({
      entries: [{ sections }],
    });
    expect(ownerJournalSectionTitle("intent")).toBe("我的行动");
    expect(ownerJournalSectionTitle("check")).toBe("规则判定");
    expect(ownerJournalSectionTitle("observation")).toBe("我所看见");
    expect(ownerJournalSectionTitle("ownerConversation")).toBe("昨夜与主人");
  });

  it("rejects unknown or internally tagged journal sections", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: context.actorId,
        runId: context.runId,
        updatedDayIndex: 1,
        entries: [{
          episodeRef: context.episodeRef,
          dayIndex: 1,
          title: "第一天",
          story: "只保留当前角色的版本。",
          changes: [],
          sections: [{ kind: "omniscient", text: "goal-angel-protect" }],
        }],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).rejects.toThrow(
      "Owner journal identity mismatch",
    );
  });

  it("loads every owner-safe day for the current actor and sorts newest first", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        runId: context.runId,
        actorId: context.actorId,
        updatedDayIndex: 2,
        entries: [
          {
            episodeRef: "memory:day-1:oc-angel",
            dayIndex: 1,
            title: "第一天",
            story: "我记得第一天自己真正经历的部分。",
            changes: ["我开始重新判断自己看见的事实。"],
          },
          {
            episodeRef: "memory:day-2:oc-angel",
            dayIndex: 2,
            title: "第二天",
            story: "我把昨天的经历带进了今天的选择。",
            changes: ["昨天留下的记忆改变了今天的计划。"],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toEqual({
      updatedDayIndex: 2,
      entries: [
        {
          episodeRef: "memory:day-2:oc-angel",
          dayIndex: 2,
          title: "第二天",
          story: "我把昨天的经历带进了今天的选择。",
          changes: ["昨天留下的记忆改变了今天的计划。"],
          sections: [],
        },
        {
          episodeRef: "memory:day-1:oc-angel",
          dayIndex: 1,
          title: "第一天",
          story: "我记得第一天自己真正经历的部分。",
          changes: ["我开始重新判断自己看见的事实。"],
          sections: [],
        },
      ],
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/owner/actors/oc-angel/journal",
      { method: "GET" },
    );
  });

  it("rejects a journal payload containing another actor episode", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        runId: context.runId,
        actorId: context.actorId,
        updatedDayIndex: 2,
        entries: [
          {
            episodeRef: "memory:day-2:oc-angel",
            dayIndex: 2,
            title: "第二天",
            story: "这是 OO 自己的经历。",
            changes: [],
          },
          {
            episodeRef: "memory:day-1:oc-devil",
            dayIndex: 1,
            title: "越界日志",
            story: "这里不允许出现 CC 的经历。",
            changes: [],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).rejects.toThrow(
      "Owner journal identity mismatch",
    );
  });

  it("drops internal tokens at the owner-facing journal boundary", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: context.actorId,
        runId: context.runId,
        updatedDayIndex: 1,
        entries: [
          {
            episodeRef: context.episodeRef,
            dayIndex: context.dayIndex,
            title: "第一天",
            story: "我只记下自己真正经历的部分。",
            changes: [
              "信念 suspected: belief-before-judging",
              "主人建议 verify-before-judging: accepted",
            ],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toMatchObject({
      entries: [{ episodeRef: context.episodeRef, changes: [] }],
    });
  });

  it("drops internal behaviour ids without hiding the owner-safe story", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: context.actorId,
        runId: context.runId,
        updatedDayIndex: 1,
        entries: [
          {
            episodeRef: context.episodeRef,
            dayIndex: context.dayIndex,
            title: "第一天",
            story: "我只记下自己真正经历的部分。",
            changes: [
              "我逐渐形成了 shared-event / use-insight 的行为倾向",
              "我决定采纳主人的建议",
            ],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toMatchObject({
      entries: [{
        story: "我只记下自己真正经历的部分。",
        changes: ["我决定采纳主人的建议"],
      }],
    });
  });

  it("keeps every exact actor episode even when the Room URL started on Day 1", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.2",
        actorId: "oc-angel",
        runId: "living-day-demo",
        updatedDayIndex: 2,
        entries: [
          {
            episodeRef: "memory:day-2:oc-angel",
            dayIndex: 2,
            title: "第二天",
            story: "这是 OO 第二天自己的经历。",
            changes: [],
          },
          {
            episodeRef: context.episodeRef,
            dayIndex: 1,
            title: "第一天",
            story: "这是当前 OO 自己的经历。",
            changes: [],
          },
        ],
      }),
    );

    await expect(loadCurrentOwnerJournal(fetcher, context)).resolves.toMatchObject({
      updatedDayIndex: 2,
      entries: [
        { episodeRef: "memory:day-2:oc-angel", dayIndex: 2, title: "第二天" },
        { episodeRef: context.episodeRef, dayIndex: 1, title: "第一天" },
      ],
    });
  });

  it("advances the same run and exposes only OO's next activity", async () => {
    const fetcher = vi.fn(async () =>
      response({
        schemaVersion: "0.1",
        runId: "living-day-demo",
        dayIndex: 2,
        actors: [
          {
            actorId: "oc-angel",
            activityLabel:
              "守住“先核对亲历证据”，参考主人建议调整调查门厅异响",
          },
          { actorId: "oc-devil", activityLabel: "继续自己的计划" },
        ],
      }),
    );

    await expect(advanceLivingWorldDay(fetcher, context)).resolves.toEqual({
      dayIndex: 2,
      activityLabel:
        "守住“先核对亲历证据”，参考主人建议调整调查门厅异响",
    });
    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-demo/advance",
      { method: "POST" },
    );
  });

  it("rejects internal goal ids at the next-day activity boundary", async () => {
    const fetcher = vi.fn(async () =>
      response({
        runId: context.runId,
        dayIndex: 2,
        actors: [
          {
            actorId: context.actorId,
            activityLabel:
              "守住“保护同伴优先”，参考主人建议调整 goal-angel-protect",
          },
        ],
      }),
    );

    await expect(advanceLivingWorldDay(fetcher, context)).rejects.toThrow(
      "Owner next-day activity contains internal tokens",
    );
  });

  it("rejects a non-consecutive projection even when the run and actor match", async () => {
    const fetcher = vi.fn(async () =>
      response({
        runId: context.runId,
        dayIndex: 3,
        actors: [
          {
            actorId: context.actorId,
            activityLabel: "不应跳过 Day 2",
          },
        ],
      }),
    );

    await expect(advanceLivingWorldDay(fetcher, context)).rejects.toThrow(
      "Living World advance identity mismatch",
    );
  });

  it("submits one confirmed suggestion exactly once without advancing the world", async () => {
    const confirmation = new OwnerAdviceConfirmation();
    const candidate = confirmation.offerTranscript(
      "先确认自己真正看见的事实，再决定是否相信。",
    );
    expect(candidate).not.toBeNull();

    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const submit = vi.fn(async () => {
      await pending;
      return { disposition: "accepted" as const };
    });

    const first = confirmation.confirm(submit);
    const duplicate = confirmation.confirm(submit);
    expect(await duplicate).toBeNull();
    expect(submit).toHaveBeenCalledTimes(1);
    expect(String(submit.mock.calls[0]?.[0])).not.toContain("advance");
    release();
    await expect(first).resolves.toEqual({ disposition: "accepted" });

    await expect(confirmation.confirm(submit)).resolves.toBeNull();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it("returns to TV with the exact public projection produced inside Room", () => {
    const projection = {
      schemaVersion: "0.1",
      runId: context.runId,
      dayIndex: 2,
      actors: [],
      timeline: [],
      event: {},
      memoryRefs: [],
      worldVersion: 2,
      worldHash: "hash",
      replayVerified: true,
    };
    const url = new URL(
      returnUrlWithDayLoopResume(
        "http://127.0.0.1:5177/?roomApp=http://127.0.0.1:4174/",
        projection,
      ),
    );

    expect(JSON.parse(url.searchParams.get("dayLoopResume") ?? "")).toEqual(
      projection,
    );
  });
});
