import { describe, expect, test } from "vitest";
import { RealtimeTurnContext } from "../relay-worker/src/turn-context";

describe("realtime turn context", () => {
  test("waits for a late ASR event from the same audio turn", async () => {
    const context = new RealtimeTurnContext();
    context.observeServer({
      type: "input_audio_buffer.speech_started",
      item_id: "user-1",
    });
    const turn = context.snapshot();
    const waiting = context.waitForUserText(turn, 1_000);

    context.observeServer({
      type:
        "conversation.item.input_audio_transcription.completed",
      item_id: "user-1",
      transcript: "第二轮暗号是松塔",
    });

    await expect(waiting).resolves.toBe("第二轮暗号是松塔");
  });

  test("cancels stale context when the next audio turn starts", async () => {
    const context = new RealtimeTurnContext();
    context.observeServer({
      type: "input_audio_buffer.speech_started",
      item_id: "user-old",
    });
    const oldTurn = context.snapshot();
    const waiting = context.waitForUserText(oldTurn, 1_000);

    context.observeServer({
      type: "input_audio_buffer.speech_started",
      item_id: "user-new",
    });
    context.observeServer({
      type:
        "conversation.item.input_audio_transcription.completed",
      item_id: "user-old",
      transcript: "迟到的旧字幕",
    });

    await expect(waiting).resolves.toBeUndefined();
    expect(context.snapshot().userText).toBe("");
  });

  test("captures an explicit browser text turn immediately", async () => {
    const context = new RealtimeTurnContext();
    context.observeClient({
      type: "conversation.item.create",
      item: {
        type: "message",
        role: "user",
        content: [{ type: "input_text", text: "只回答月桂" }],
      },
    });
    const turn = context.snapshot();

    await expect(context.waitForUserText(turn, 1_000))
      .resolves.toBe("只回答月桂");
  });
});
