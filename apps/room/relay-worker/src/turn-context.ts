export interface TurnSnapshot {
  revision: number;
  userText: string;
}

type Waiter = (value: string | undefined) => void;

export class RealtimeTurnContext {
  private revision = 0;
  private itemId = "";
  private userText = "";
  private readonly waiters = new Set<Waiter>();

  observeClient(event: Record<string, unknown>): void {
    if (event.type !== "conversation.item.create") return;
    const item = event.item;
    if (!item || typeof item !== "object") return;
    const value = item as Record<string, unknown>;
    if (value.role !== "user" || !Array.isArray(value.content)) return;
    const textPart = value.content.find((part) => {
      if (!part || typeof part !== "object") return false;
      const content = part as Record<string, unknown>;
      return content.type === "input_text"
        && typeof content.text === "string";
    }) as Record<string, unknown> | undefined;
    const text =
      typeof textPart?.text === "string" ? textPart.text.trim() : "";
    if (text) this.begin("", text);
  }

  observeServer(event: Record<string, unknown>): void {
    if (event.type === "input_audio_buffer.speech_started") {
      this.begin(
        typeof event.item_id === "string" ? event.item_id : "",
        "",
      );
      return;
    }
    if (
      event.type
        !== "conversation.item.input_audio_transcription.completed"
      || typeof event.transcript !== "string"
    ) {
      return;
    }
    const eventItemId =
      typeof event.item_id === "string" ? event.item_id : "";
    if (this.revision === 0) {
      this.begin(eventItemId, "");
    }
    if (this.itemId && eventItemId && this.itemId !== eventItemId) {
      return;
    }
    if (!this.itemId) this.itemId = eventItemId;
    this.userText = event.transcript.trim();
    this.resolveWaiters(this.userText);
  }

  snapshot(): TurnSnapshot {
    return {
      revision: this.revision,
      userText: this.userText,
    };
  }

  waitForUserText(
    snapshot: TurnSnapshot,
    timeoutMs = 750,
  ): Promise<string | undefined> {
    if (snapshot.revision !== this.revision) {
      return Promise.resolve(undefined);
    }
    if (this.userText) return Promise.resolve(this.userText);
    if (snapshot.revision === 0) return Promise.resolve("");

    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      const waiter: Waiter = (value) => {
        if (timer) clearTimeout(timer);
        this.waiters.delete(waiter);
        resolve(value);
      };
      this.waiters.add(waiter);
      timer = setTimeout(() => {
        this.waiters.delete(waiter);
        if (snapshot.revision !== this.revision) {
          resolve(undefined);
        } else {
          resolve(this.userText);
        }
      }, timeoutMs);
    });
  }

  private begin(itemId: string, userText: string): void {
    this.resolveWaiters(undefined);
    this.revision += 1;
    this.itemId = itemId;
    this.userText = userText;
  }

  private resolveWaiters(value: string | undefined): void {
    const waiters = [...this.waiters];
    this.waiters.clear();
    waiters.forEach((resolve) => resolve(value));
  }
}
