# OC 墨水屏显示接口 v1

这份文档是 Orange Pi 与 ESP32/墨水屏之间的冻结契约。ESP32 **不处理语音事件、StepFun 鉴权或角色推理**；它只接收下面四种显示任务，并按同一个 `task_id` 返回 ACK。

机器可读文件位于 `protocol/scene-task.schema.json`、`display-ack.schema.json` 和 `asset-manifest.schema.json`。

## 已实现的传输适配器

`src/oc_gateway/hardware_api.py` 已实现 `HardwareServerDisplayTransport`，硬件负责人不需要再从零实现 Orange Pi 到现有 ADVX 代码的适配。实际链路是：

```text
SceneTask
  → HardwareServerDisplayTransport
  → POST /api/server/tasks
  → ADVX Task Server
  → Orange Pi Agent
  → BluetoothRenderer
  → /dev/rfcomm*
  → ESP32 EPD1
```

内部仍遵守下面两个异步方法，因此 Mock 和未来其他传输可以继续替换：

```python
class DisplayTransport(Protocol):
    async def send_task(self, task: SceneTask) -> None: ...
    async def wait_for_ack(
        self, task_id: str, timeout: float
    ) -> DisplayAck | None: ...
```

参考 Mock 位于 `src/oc_gateway/transports.py`。当前真实适配器使用 ADVX HTTP/WS，不要求 ESP32 解析这一层 JSON。

## 通用任务信封

```json
{
  "version": 1,
  "task_id": "demo-text-001",
  "type": "scene.render",
  "priority": 50,
  "ttl_ms": 10000,
  "interrupt": "replace",
  "duration_ms": 5000,
  "created_at": "2026-07-24T10:00:00Z",
  "scene": {}
}
```

| 字段 | 类型 | 约束 / 默认 |
|---|---|---|
| `version` | integer | 固定为 `1` |
| `task_id` | string | 非空、最长 128；用于去重和 ACK |
| `type` | string | 固定为 `scene.render` |
| `priority` | integer | `0..100`；默认 `50`，越大越优先 |
| `ttl_ms` | integer | 正整数；默认 `10000` |
| `interrupt` | enum | `replace` / `queue` / `ignore`；默认 `replace` |
| `duration_ms` | integer | 正整数；建议显示时长，默认 `5000` |
| `created_at` | string | 带时区的 ISO 8601 UTC 时间 |
| `scene` | object | 只能是下面四种形状之一，不允许额外字段 |

## 四种且仅四种任务

### 1. 文字

```json
{
  "version": 1,
  "task_id": "demo-text-001",
  "type": "scene.render",
  "priority": 50,
  "ttl_ms": 10000,
  "interrupt": "replace",
  "duration_ms": 5000,
  "created_at": "2026-07-24T10:00:00Z",
  "scene": {
    "text": {
      "content": "主人，该喝水了。",
      "style": "devil_reminder"
    }
  }
}
```

`content` 为 1–120 个 Unicode 字符；`style` 是硬件端样式 ID。

### 2. 动画

```json
{
  "version": 1,
  "task_id": "demo-animation-001",
  "type": "scene.render",
  "priority": 50,
  "ttl_ms": 10000,
  "interrupt": "replace",
  "duration_ms": 3000,
  "created_at": "2026-07-24T10:00:00Z",
  "scene": {
    "animation": {
      "asset_id": "devil_wave",
      "asset_version": 1,
      "loop": 2
    }
  }
}
```

`asset_id` 非空；`asset_version >= 1`；`loop` 为 `1..100`。

### 3. 图片

```json
{
  "version": 1,
  "task_id": "demo-image-001",
  "type": "scene.render",
  "priority": 50,
  "ttl_ms": 10000,
  "interrupt": "replace",
  "duration_ms": 5000,
  "created_at": "2026-07-24T10:00:00Z",
  "scene": {
    "image": {
      "asset_id": "devil_low_battery",
      "asset_version": 1
    }
  }
}
```

### 4. 文字 + 动画（原子场景）

```json
{
  "version": 1,
  "task_id": "demo-scene-001",
  "type": "scene.render",
  "priority": 80,
  "ttl_ms": 10000,
  "interrupt": "replace",
  "duration_ms": 5000,
  "created_at": "2026-07-24T10:00:00Z",
  "scene": {
    "text": {
      "content": "我在想啦。",
      "style": "devil_thinking"
    },
    "animation": {
      "asset_id": "devil_thinking",
      "asset_version": 1,
      "loop": 1
    }
  }
}
```

两部分必须在一次渲染提交中生效，不能拆成两个任务；这样字幕与表情不会错帧。文字 + 图片、图片 + 动画等第五种组合必须拒绝。

## 优先级、打断与过期

- `replace`：目标应停止当前可中断任务并渲染新任务。
- `queue`：进入优先级队列；同优先级按 `created_at` 先后执行。
- `ignore`：显示端忙时丢弃，并返回 `cancelled`。
- Orange Pi 在下发前检查 `created_at + ttl_ms`，过期任务不再发送。
- `task_id` 重复时不重复渲染。

## ACK

```json
{
  "version": 1,
  "task_id": "demo-text-001",
  "status": "completed",
  "error_code": null
}
```

`status` 只能是：

| 状态 | 含义 |
|---|---|
| `accepted` | 已解析并进入显示队列 |
| `rendering` | 已开始刷新 |
| `completed` | 本次显示完成 |
| `failed` | 失败；`error_code` 给出机器可读原因 |
| `cancelled` | 被替换、忽略或主动取消 |

Orange Pi 等待 `accepted` 超时后重发一次相同 `task_id`；仍无 ACK 时记录失败，不无限重试。因此 ESP32 必须按 `task_id` 幂等。

本地联调可查询最终状态：

```bash
curl http://127.0.0.1:8787/v1/display/tasks/<task_id>
```

未收到 ACK 时返回 HTTP 202 和 `pending`；收到后返回上面的完整 ACK。

## 资产清单

每个预置资源提供：

| 字段 | 说明 |
|---|---|
| `asset_id` / `asset_version` | 稳定资源标识与正整数版本 |
| `width` / `height` | 像素尺寸 |
| `bit_depth` | `1`、`2`、`4` 或 `8` |
| `frame_count` | 帧数，静态图为 `1` |
| `frame_duration_ms` | 单帧时长 |
| `loopable` | 是否允许循环 |
| `sha256` | 64 位小写十六进制内容摘要 |

OC Scene 本身不携带图片二进制。`HardwareServerDisplayTransport` 从以下目录读取精确版本，并转换为 ADVX 所需 Base64：

```text
assets/<asset_id>/v<asset_version>/image.bmp
assets/<asset_id>/v<asset_version>/frame_000.bmp
assets/<asset_id>/v<asset_version>/frame_001.png
```

图片只读取 `image.bmp/png`；动画只读取 `frame_*.bmp/png` 并按文件名排序。

## 多屏路由和结果

Orange Pi 环境配置固定路由，模型不能选择物理设备：

```dotenv
OC_HARDWARE_AGENT_ID=orangepi-3b-01
OC_HARDWARE_TARGETS=["left","right"]
OC_HARDWARE_SCREEN_TOKENS={"left":"","right":""}
```

`target_results` 会保留每块屏幕状态。任一屏失败时聚合 ACK 为 `failed`，`error_code` 形如 `targets_failed:right`；其他屏幕的成功不会被抹掉。

## 硬件一致性验收

- [ ] 文字任务解析、显示并返回 `completed`
- [ ] 动画任务解析、按 `loop` 播放并返回 `completed`
- [ ] 图片任务按 `asset_version` 显示并返回 `completed`
- [ ] 文字 + 动画原子生效并返回 `completed`
- [ ] 重复 `task_id` 不重复刷新，但重发最近 ACK
- [ ] 过期任务不会显示
- [ ] `replace`、`queue`、`ignore` 行为符合定义
- [ ] 非法第五种组合返回 `failed`
- [ ] ESP32 固件内没有 StepFun Key 或设备云令牌
- [ ] 一屏断开时另一屏仍完成，Job 返回正确 `target_results`
- [ ] `screens.json` 启用逐屏 Token 后，OC 映射与其一致
