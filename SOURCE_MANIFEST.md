# Source manifest

| Module | Source repository / worktree | Frozen revision |
|---|---|---|
| Living World API | `M:\code\hackthon\kaleidoroom`, `feat/owner-conversation-memory` | `06ae52e` |
| Infinite Channel TV | `ReginaXia/TV-Demo`, `agent/bring-your-oc-tv` | `c848e89` |
| Room / realtime voice | `M:\code\ADX\oc-eink-demo`, `feature/fullscreen-room-voice-ui` | `858f4a3` |
| Orange Pi gateway | `M:\code\ADX\oc-eink-demo`, `feature/orange-pi-hardware-kit` | `132fa51` |

Living World `06ae52e` includes the preceding structured-journal and owner-conversation baselines `16c851e` and `f445811`.

Integration-only changes in this repository:

1. The TV defaults to the production Room origin.
2. The VPS TV proxy accepts the production Room origin.
3. Imported OCs enter a dynamic temporary Room under their own identity; they are never silently shown as OO/CC.
4. One deployment layout and one verification entry point replace the former cross-worktree handoff.
5. Room build identifier is `BUILD 2026.07.25.13`, and its test command is scoped to `tests/` so the standalone fallback Node suite is not misclassified as Vitest.
