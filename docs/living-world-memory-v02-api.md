# Living World Memory v0.2（Demo）

一句话：世界只提交一份 Canon；每个 OC 只把自己观察到的部分沉淀为 Episode，再形成可修订的 Belief 和需要重复证据才能成立的 Personality Pattern。

这套实现借鉴 ReverieMem 的三层记忆思想，但不是复用论文代码，也不声称完整复现论文。Demo 刻意不使用向量数据库：

```text
Canonical Event
→ per-OC Observation
→ EpisodicMemory（亲历）
→ SubjectiveBelief（带来源、置信度、可修订）
→ PersonalityPattern（3 次同类证据后才 established）
→ bounded planning context（最近 3 条）
→ 第二天 OCA Plan
```

代码：

```text
services/api/app/domain/living_memory.py
services/api/app/domain/day_cycle.py
services/api/tests/test_living_memory_v02.py
```

## 主人建议

建议不会修改世界，也不会替 OC 决策。OC 的建议决策只有三种：

```text
accepted | partiallyAccepted | rejected
```

只有 `accepted` 和 `partiallyAccepted` 会进入第二天 OCA 的规划上下文；`rejected` 只留在该 OC 的私有记忆中。

```http
POST /api/living-world/day-loop-runs/{runId}/owner/actors/{actorId}/counsel
Content-Type: application/json

{
  "episodeRef": "memory:day-1:oc-angel",
  "adviceId": "verify-before-judging",
  "adviceText": "明天先核对证据，再判断别人。",
  "recommendationKind": "verifyEvidence"
}
```

`recommendationKind` 当前 Demo 支持：

```text
verifyEvidence | seekDialogue | avoidConflict |
takeRisk | breakWorldRules | other
```

真实 deterministic runtime 响应示例：

```json
{
  "counselId": "counsel:c8c0089609339307",
  "actorId": "oc-angel",
  "episodeRef": "memory:day-1:oc-angel",
  "adviceId": "verify-before-judging",
  "disposition": "accepted",
  "reason": "这与我重视亲历证据的判断方式一致。",
  "publicReply": "我会把这句话带到明天，再自己做决定。",
  "privateOsAvailable": true,
  "privateOsRef": "private-os-context:counsel:c8c0089609339307",
  "decisionProvider": "deterministic-counsel-v1"
}
```

前端只消费该响应，不读取内部 Memory Store。

## Owner-safe 对话记忆

只在用户明确确认“这句话值得 OC 记住”、且语音链路已经生成本轮真实
Private OS 后调用：

```http
POST /api/living-world/day-loop-runs/{runId}/owner/actors/{actorId}/conversation-memory
Content-Type: application/json

{
  "episodeRef": "memory:day-1:oc-angel",
  "counselId": "counsel:c8c0089609339307",
  "userText": "明天先确认自己亲眼看到的证据。",
  "publicReply": "我会认真考虑。",
  "privateInnerOs": "他说得对，但最后仍由我自己判断。"
}
```

响应不会回传心声正文：

```json
{
  "conversationId": "conversation:6b92cf6ad8f1cc2b",
  "actorId": "oc-angel",
  "episodeRef": "memory:day-1:oc-angel",
  "counselId": "counsel:c8c0089609339307",
  "recorded": true
}
```

约束：

- `counselId` 必须属于 URL 中的 actor，并绑定同一个 `episodeRef`。
- 同一个 counsel 重复提交是幂等的，不会重复生成日记段落。
- 该记录只进入当前 actor 的 owner-safe 日志；不进入 Canon、World
  Projection 或其他 OC 的日志。
- 日志正文会增加“昨夜与主人”：主人原话、OC 对外回答、当时真正的
  想法。Private OS 仍不得出现在公共页面。
- 次日规划不直接服从对话文本，而是继续读取 counsel disposition：接受或
  部分接受才可能影响计划，拒绝时与无建议组保持一致。

## Owner-safe 日志

```http
GET /api/living-world/day-loop-runs/{runId}/owner/actors/{actorId}/journal
```

只返回：

```text
episodeRef / dayIndex / title / story / changes[] / sections[]
```

`story` 与 `changes[]` 保持兼容。新增 `sections[]` 供产品按语义分区，前端
不得通过正则拆 `story`，也不得自行计算检定或推断他人 POV：

```json
{
  "kind": "check",
  "text": "认真检定：D20 12 +2 = 14，对抗 DC 13，成功。"
}
```

`kind` 仅允许：

```text
scene | intent | check | observation | consequence |
reflection | ownerConversation
```

- `check` 只读取当前 OC 的真实 Rule Kernel check。
- `observation` 只包含当前 OC Observation 中确实见到的行动结果，不包含
  对方目标、做法、内心理由、RPG 属性、骰点、加值、总计或 DC。它只会
  描述可见行为及结果，例如“我看见 CC 上前尝试处理，成功推动了局面”。
- `consequence` 只包含 effects 投影到当前 OC 的关系或状态后果。
- `reflection` 只读取当前 OC 的 Belief / Personality Pattern。
- `ownerConversation` 只存在于当前主人鉴权后的日记。

其中 `story` 是该 OC 的第一人称 Episode；`changes[]` 是产品级的关系后果、信念、稳定倾向或建议态度摘要。接口结构没有变化，前端无需解析内部事件。

当前正文至少包含：

```text
实际地点 + 事件 hook / stakes
+ 当前 OC 自己的目标、做法与 D20 / DC 结果
+ 该 OC 亲眼观察到的其他行动结果
+ 只属于该 OC 的关系后果与信念变化
+ 主人建议原话，以及 accepted / partiallyAccepted / rejected 的产品级表达
```

日志生成器不会读取其他 OC 的目标、内心理由、未观察行动或私有 Episode。预设世界中的钥匙技术 fixture 也不会进入 Day Loop 日志正文。

以下字段只保留在算法内部，不进入日志：

```text
sourceEventIds / sourceObservationIds / perceivedFactCodes
evidenceBalance / sourceMemoryIds / evidenceMemoryIds
Canonical Event / Rule effects / 其他 OC 的 Episode
```

以下字段只供 Private OS LLM 使用，不进入日志：

```text
decisionReason / relevantMemorySummaries / privateOsRef 对应的上下文
```

## Private OS 接线

正常产品路径不是后端写死台词：

```text
主人建议
→ OCA disposition + reason + relevant memories
→ owner-safe privateOsRef
→ Owner Room 按 actor + episode 校验上下文
→ 作为一次性 oc.decision_context 交给当前语音会话
→ 语音服务把它与下一轮 userText/publicText 一起交给 Private OS LLM
→ 墨水屏显示生成结果
```

供语音服务读取的 owner-safe 上下文：

```http
GET /api/living-world/day-loop-runs/{runId}/owner/actors/{actorId}/private-os-context?ref={privateOsRef}
```

返回：

```json
{
  "actorId": "oc-angel",
  "episodeRef": "memory:day-1:oc-angel",
  "disposition": "accepted",
  "decisionReason": "这与我重视亲历证据的判断方式一致。",
  "relevantMemorySummaries": [
    "我只记下自己亲眼见到的行动结果。"
  ]
}
```

该接口不能跨 actor 读取。Private OS 正文不进入 Canon，也不进入 World Projection。语音侧模型失败时才使用 fallback，并必须保留 `source=model|fallback` 标记。

## Demo 怎么证明

1. 运行 Day 1，得到天使自己的 `memoryRef`。
2. 主人提出建议，画面显示 OC 的 `disposition`，不是统一“已收到”。
3. 进入语音后，下一轮 Private OS 消费一次该真实态度，墨水屏显示模型生成的短心声。
4. 运行 Day 2：接受建议组的 `actors[].activityLabel` 会明确显示
   `守住“人设底线”，参考主人建议调整目标`，并与同 seed 无建议组的日程不同。
5. 发送 `breakWorldRules` 建议：OC 拒绝，Day 2 与无建议组相同。

这证明的是“建议被记住并由 OC 自主决定是否采用”，不是主人遥控世界。

## 验证

```powershell
cd M:\code\hackthon\kaleidoroom\services\api
python -m pytest tests/test_living_memory_v02.py -q
python -m pytest -q
```

当前验收覆盖：

- POV 来源隔离；
- Belief 反证修订；
- Personality Pattern 慢变量；
- 建议接受/拒绝的反事实；
- 建议影响次日日程；
- private context 跨角色读取返回 404；
- 全后端回归。

## 日志叙述边界

Owner Journal 的接口结构保持不变，但正文不再由前端 fixture 提供。
`JournalNarratorProvider` 每次只接收当前 OC 的：

```text
persona constraints
+ own Episode（含 POV-safe 的地点、事件、本人检定、所见行动与本人后果）
+ own Belief
+ own established Personality Pattern
+ own Counsel record
```

它不能读取其他 OC 的 Episode、全知 Canon 或 Private OS 正文。模型叙述器可以
通过同一 provider 接口注入；模型不可用或返回非法结果时，Runtime 会回退到
无需 API Key 的确定性第一人称短日志。回退文案仍结合当前 OC 的人设与主观
Episode，不再是跨角色共享的静态故事。
