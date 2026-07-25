import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

async function readSource(path: string): Promise<string> {
  return readFile(new URL(path, import.meta.url), "utf8");
}

describe("room character staging", () => {
  it("always renders an exit and never renders a cross-resident switcher", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).toContain(
      '<button class="room-exit" id="room-exit" type="button">← 返回无限电视塔</button>',
    );
    expect(main).toContain(
      'roomExitButton.textContent = roomReturnTarget ? "← 返回无限电视塔" : "← 退出房间";',
    );
    expect(main).not.toContain('id="character-switch"');
    expect(main).not.toContain('aria-label="切换角色"');
  });

  it("hard-locks the loaded room to one resident without preloading the other OC", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).toContain(
      "const selected: CharacterId = resolveRoomCharacter(location.search);",
    );
    expect(main).toContain(
      "const roomResidentId = resolveRoomResidentId(location.search);",
    );
    expect(main).not.toContain("let selected: CharacterId");
    expect(main).not.toContain("Object.values(CHARACTERS).flatMap");
    expect(main).toContain("loadRegisteredOc(");
    expect(main).toContain("activeCharacter.roomImage");
    expect(main).toContain("activeCharacter.portraitImage");
    expect(main).toContain("activeCharacter.dynamicVoiceProfile");
    expect(main).not.toContain("CHARACTERS[selected].roomImage");
    expect(main).not.toContain("CHARACTERS[selected].portraitImage");
  });

  it("keeps the tower exit large and readable over every room scene", async () => {
    const css = await readSource("../src/style.css");

    expect(css).toMatch(
      /\.room-exit\s*\{[^}]*min-height:\s*48px;[^}]*background:\s*rgba\(12,\s*9,\s*17,\s*\.94\);[^}]*font-size:\s*clamp\(12px,\s*1\.1vw,\s*16px\);/s,
    );
  });

  it("keeps owner advice out of the journal and confirms the user's exact words in dialogue", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).not.toContain('id="owner-advice"');
    expect(main).not.toContain("completeOoAdviceLoop");
    expect(main).toContain('id="advice-confirmation"');
    expect(main).toContain('id="advice-quote"');
    expect(main).toContain('id="confirm-advice"');
    expect(main).toContain("resolveOwnerLivingWorldContext");
    expect(main).toContain("OwnerAdviceConfirmation");
    expect(main).not.toContain("nextDay.activityLabel");
  });

  it("does not ship static diary entries or fake past-memory controls", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).not.toContain("journalEntries");
    expect(main).not.toContain('data-memory="firstVoice"');
    expect(main).not.toContain('data-memory="quietRoom"');
    expect(main).toContain("日志暂不可读取");
    expect(main).toContain("API ERROR");
  });

  it("renders the current owner's real multi-day journal with minimal day navigation", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).toContain('id="journal-day-label"');
    expect(main).toContain('id="journal-position"');
    expect(main).toContain('data-action="journal-newer"');
    expect(main).toContain('data-action="journal-older"');
    expect(main).toContain('id="journal-changes-heading"');
    expect(main).toContain("留下的变化");
    expect(main).toContain("entry.story");
    expect(main).toContain("entry.changes.map");
    expect(main).toContain("journal.entries");
    expect(main).toContain("selectedJournalIndex = 0");
    expect(main).not.toContain('id="owner-advice"');
    expect(main).not.toContain('id="private-os-content"');
    expect(main).not.toContain("goal-angel-protect");
  });

  it("renders fresh journals as labelled owner-safe sections and keeps story as legacy fallback only", async () => {
    const main = await readSource("../src/main.ts");
    const css = await readSource("../src/style.css");

    expect(main).toContain('id="journal-sections"');
    expect(main).toContain('id="journal-owner-heading"');
    expect(main).toContain('`${journalOwnerLabel()} 所经历的版本`');
    expect(main).toContain("entry.sections.length > 0");
    expect(main).toContain("ownerJournalSectionTitle(section.kind)");
    expect(main).toContain("section.text");
    expect(main).toContain('journalCopy.hidden = true');
    expect(css).toContain(".journal-sections");
    expect(css).toContain(".journal-section-check");
    expect(css).toContain(".journal-section-observation");
  });

  it("records a confirmed suggestion only after the actual private OS reaches the device", async () => {
    const main = await readSource("../src/main.ts");
    expect(main).toContain("OwnerConversationMemoryRecorder");
    expect(main).toContain("recordOwnerConversationMemory");
    expect(main).toContain('event.type === "inner_os.delivered"');
    expect(main).toContain("conversationMemoryRecorder?.arm(");
    expect(main).toContain("conversationMemoryRecorder.recordDelivery(");
    expect(main).toContain("本轮对话与心声已写入她的记忆");
    expect(main).toContain("本轮未写入记忆");
    expect(main).not.toContain('id="private-os-content"');
  });

  it("keeps deterministic Private OS copy off the webpage", async () => {
    const main = await readSource("../src/main.ts");
    const roomState = await readSource("../src/room-state.ts");
    const browserCopy = `${main}\n${roomState}`;

    expect(browserCopy).not.toContain("日常内心 OS");
    expect(browserCopy).not.toContain(
      "主人还没回来。很好，我可以继续假装自己完全没有在等。",
    );
    expect(browserCopy).not.toContain(
      "这里很安静。很好，没有人命令我微笑。",
    );
  });

  it("ships a dedicated decorative sleeping layer", async () => {
    const main = await readSource("../src/main.ts");

    expect(main).toContain(
      '<div class="sleeping-character" aria-hidden="true">',
    );
    expect(main).toContain('<span class="sleeping-head"></span>');
    expect(main).toContain('<span class="sleeping-body"></span>');
    expect(main).toContain('<span class="sleeping-mark"></span>');
  });

  it("uses a large lowered foreground portrait", async () => {
    const css = await readSource("../src/style.css");
    const portraitRule = css.match(/\.character-sprite\s*\{([\s\S]*?)\n\}/)?.[1];

    expect(portraitRule).toContain("left: 22%");
    expect(portraitRule).toContain("bottom: -3%");
    expect(portraitRule).toContain("width: 34%");
    expect(portraitRule).toContain("height: 86%");
  });

  it("compensates for the angel artwork's wider transparent wing area", async () => {
    const css = await readSource("../src/style.css");
    const angelFrameRule = css.match(
      /\.room-stage\[data-character="angel"\]\s+\.character-sprite\s*\{([\s\S]*?)\n\}/,
    )?.[1];
    const angelRule = css.match(
      /\.room-stage\[data-character="angel"\]\s+\.character-sprite img\s*\{([\s\S]*?)\n\}/,
    )?.[1];

    expect(angelFrameRule).toContain("overflow: visible");
    expect(angelRule).toContain("transform: scale(1.35)");
    expect(angelRule).toContain("transform-origin: 50% 70%");
  });

  it("swaps the standing portrait for the bed silhouette while resting", async () => {
    const css = await readSource("../src/style.css");

    expect(css).toMatch(
      /\.sleeping-character\s*\{[\s\S]*?display:\s*none;[\s\S]*?\n\}/,
    );
    expect(css).toMatch(
      /\.room-stage\[data-view="resting"\]\s+\.character-sprite\s*\{[\s\S]*?opacity:\s*0;[\s\S]*?pointer-events:\s*none;[\s\S]*?\n\}/,
    );
    expect(css).toMatch(
      /\.room-stage\[data-view="resting"\]\s+\.sleeping-character\s*\{[\s\S]*?display:\s*block;[\s\S]*?\n\}/,
    );
  });

  it("gives angel and devil distinct sleeping identity marks", async () => {
    const css = await readSource("../src/style.css");

    expect(css).toContain(
      '.room-stage[data-character="angel"] .sleeping-mark',
    );
    expect(css).toContain(
      '.room-stage[data-character="devil"] .sleeping-mark',
    );
    expect(css).toContain(
      '.room-stage[data-character="devil"] .sleeping-character::after',
    );
  });

  it("keeps a late user ASR visible without replacing the character line", async () => {
    const main = await readSource("../src/main.ts");
    const css = await readSource("../src/style.css");

    expect(main).toContain('id="previous-user-line"');
    expect(main).toContain('id="previous-user-text"');
    expect(css).toContain(".previous-user-line");
  });
});
