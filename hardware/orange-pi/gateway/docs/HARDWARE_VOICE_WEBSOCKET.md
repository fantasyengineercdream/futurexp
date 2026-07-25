# OC 硬件语音 WebSocket 接口 v1

这份文档是硬件端连接云端实时语音的冻结契约。Orange Pi 连接本接口；
ESP32 和墨水屏不直接连接云端，也不持有 StepFun Key。

## 1. 连接

```text
wss://oc-voice-lab.pages.dev/api/device/realtime?character=devil&deviceId=orangepi-3b-01
wss://oc-voice-lab.pages.dev/api/device/realtime?character=angel&deviceId=orangepi-3b-01
```

WebSocket 握手必须携带：

```http
Authorization: Bearer <OC_DEVICE_TOKEN>
```

`OC_DEVICE_TOKEN` 是设备专用令牌，只在 Orange Pi 的私密环境文件中现场注入。
`OC_DEVICE_ID` 默认是 `orangepi-3b-01`，用于让云端把设备连接与 Room View
连接路由到同一个 Durable Object。
不得使用 StepFun Key，不得把令牌写入 Git、固件、群聊、日志或截图。

收到单独发送的 `oc-hardware-device.generated.env` 后，放到 Orange Pi：

```bash
sudo cp oc-hardware-device.generated.env /etc/oc-gatewayd.env
sudo chown orangepi:orangepi /etc/oc-gatewayd.env
sudo chmod 600 /etc/oc-gatewayd.env
```

参考网关直接读取其中的 `OC_CLOUD_BASE_URL` 和 `OC_DEVICE_TOKEN`。如果使用自写
客户端，则用 `OC_CLOUD_BASE_URL` 拼接本文的 WebSocket 路径，并把
`OC_DEVICE_TOKEN` 放入上面的 `Authorization` Header。

服务端返回：

- `401`：令牌错误或缺失；
- `400`：角色不是 `devil` 或 `angel`；
- `429`：并发已满；
- `101`：WebSocket 升级成功。

演示服务当前最多 8 个并发会话，单次连接最长 10 分钟。断线后创建新会话，
不要重放旧麦克风数据。

## 2. 传输与音频格式

云端连接的上下行均为 **WebSocket 文本帧中的 JSON**。音频字段使用 Base64：

```text
signed PCM16 little-endian
24,000 Hz
mono
无 WAV 文件头
```

上行建议每 20 ms 一帧：

- 480 samples；
- 960 raw bytes；
- Base64 后通常为 1,280 个 ASCII 字符。

下行 `response.audio.delta` 的分片长度由云端决定，可能不是 20 ms。
客户端必须按到达顺序解码和排队，不能假定每个 `delta` 都是 960 字节；
解码后的字节数必须为偶数。

## 3. Orange Pi → 云端

### 3.1 持续上传麦克风音频

```json
{
  "event_id": "audio_001",
  "type": "input_audio_buffer.append",
  "audio": "<base64 PCM16 bytes>"
}
```

戒指音频必须先在 Orange Pi 解码和重采样。当前 Zilo 流程是长按录音、松开后
取得完整 Speex 录音，再解码为 16 kHz mono PCM16，重采样成上述 24 kHz 格式
并按 20 ms 上传；它不是连续实时麦克风流。

### 3.2 打断当前回复

```json
{
  "event_id": "cancel_001",
  "type": "response.cancel"
}
```

发送前先清空本地播放队列。不要为了打断而重建 WebSocket。

### 3.3 主动请求回复

```json
{
  "event_id": "response_001",
  "type": "response.create",
  "response": {
    "modalities": ["text", "audio"]
  }
}
```

服务端只允许以下上行事件：

- `input_audio_buffer.append`
- `input_audio_buffer.clear`
- `conversation.item.create`
- `response.create`
- `response.cancel`

角色人设、Voice ID、VAD、采样格式和 StepFun Key 由服务器注入，设备端不发送。

### 3.4 声明 Private OS 能力

每次设备 WebSocket 建立成功后，Orange Pi 立即发送：

```json
{
  "type": "oc.capabilities",
  "capabilities": ["inner_os.v1"]
}
```

该帧只由 Cloudflare 设备中继消费，不会转发给 StepFun。云端只有收到这项能力后，
才会向本设备生成和下发 Private OS。旧版网关不发送该帧时，实时语音仍可用，
Room View 只会显示“内心 OS 暂未接通”。

## 4. 云端 → Orange Pi

### 4.1 会话就绪

依次可能收到：

```json
{"type":"session.created"}
{"type":"session.updated"}
```

收到 `session.updated` 后才把会话标记为可用。

### 4.2 角色语音

```json
{
  "type": "response.audio.delta",
  "delta": "<base64 PCM16 bytes>"
}
```

处理顺序：

1. Base64 解码；
2. 验证字节数为偶数；
3. 构造 24 kHz mono PCM16 播放帧；
4. 立即按序送入 `AudioSink`。

当前临时扬声器由 Orange Pi 的 `/v1/audio-sink` 转发给电脑。该局域网接口发送
**二进制 PCM WebSocket 帧**，不是 Base64 JSON；未来内置扬声器直接消费相同
`PcmFrame`，不修改云端协议。

`/v1/audio-sink` 只保留局域网电脑扬声器和本地调试占用。公网 Room View
改由 `/api/device/view?deviceId=orangepi-3b-01` 连接 Cloudflare，公网单戒指
占用由云端 Durable Object 判断。本地接口仍只允许一个网页持有：

```json
{"type":"session.ready","status":"acquired"}
```

第二个网页会收到：

```json
{"type":"session.busy","code":"ring_in_use"}
```

随后以 WebSocket close code `4409` 关闭。持有网页主动断开、关闭页面或心跳失效后，
占用自动释放。只有持有网页会收到 PCM、状态和字幕，避免多网页同时播放同一段语音。

状态和字幕使用文本 JSON：

```json
{"type":"state","phase":"listening"}
{"type":"transcript","role":"assistant","text":"欢迎回来"}
```

### 4.3 字幕

用户最终字幕：

```json
{
  "type": "conversation.item.input_audio_transcription.completed",
  "transcript": "..."
}
```

角色流式字幕：

```json
{
  "type": "response.audio_transcript.delta",
  "delta": "..."
}
```

角色最终字幕：

```json
{
  "type": "response.audio_transcript.done",
  "transcript": "..."
}
```

电脑界面可以显示流式字幕；墨水屏只在 `done` 或完整短句时刷新，避免频繁闪烁。

### 4.4 VAD 与结束

- `input_audio_buffer.speech_started`：用户开始说话；
- `input_audio_buffer.speech_stopped`：用户停止说话；
- `response.done`：本次回复结束；
- `error`：上游或协议错误。

若角色正在播放时收到 `speech_started`：

1. 清空所有 `AudioSink` 播放队列；
2. 发送 `response.cancel`；
3. 墨水屏切换为 listening 状态；
4. 继续上传麦克风音频，不重连。

### 4.5 Private OS（只发给 Orange Pi）

角色公开最终字幕完成后，云端会旁路生成一句短 Private OS：

```json
{
  "type": "oc.inner_os",
  "event_id": "inner_<uuid>",
  "character": "devil",
  "text": "才、才不是特意等你的。",
  "max_characters": 24
}
```

约束：

- `character` 只会是 `devil` 或 `angel`；
- `text` 已由云端限制为单句，最多 24 个 Unicode 字符；
- Orange Pi 必须再次做 24 字符硬限制；
- 该文本不得转发给公网 Room View、电脑字幕或 TTS；
- 它是角色化的“未说出口表达”，不是模型逐步推理；
- 生成失败会使用角色短模板，不影响公开语音和字幕。

Orange Pi 把它提交到现有 `scene.render` 后，必须回传：

```json
{
  "type": "oc.inner_os.ack",
  "event_id": "inner_<uuid>",
  "status": "accepted"
}
```

`status` 只允许 `accepted` 或 `rejected`。这里的 `accepted` 表示显示任务已被
Orange Pi 的显示编排器接受，不等于真实墨水屏已经完成刷新；真机完成状态仍以
现有多屏 Job / per-screen ACK 为准。

## 5. 语音事件 → 墨水屏

墨水屏不接收音频，也不解析 Realtime JSON。Orange Pi 将语音事件转换成现有
四类 `scene.render` 任务：

| 语音事件 | 墨水屏任务 |
|---|---|
| `session.updated` | idle 动画 |
| `speech_started` | listening 动画 |
| `speech_stopped` | thinking 动画 |
| 首个 `response.audio.delta` | speaking 动画 |
| `response.audio_transcript.done` | 只转发公开字幕，不生成墨水屏文字 |
| `oc.inner_os` | 最多 24 字的 Private OS + thinking 动画 |
| `response.done` | idle 动画或保留最后短句 |
| `error` | 错误文字 + 离线动画 |

显示任务、多屏 targets 和逐屏 ACK 继续遵守 `HARDWARE_DISPLAY_API.md`，不新增
第二套显示协议。

## 6. 当前参考实现

Orange Pi 已有可复用实现：

- `src/oc_gateway/voice.py`
  - `CloudVoiceProvider`
  - 鉴权、连接、Base64 上行、Base64 下行解码、重连
- `src/oc_gateway/service.py`
  - 音频路由、打断、公开字幕与 Private OS 分流、Private OS 到显示任务
- `src/oc_gateway/api.py`
  - 局域网电脑扬声器 `/v1/audio-sink`
- `src/oc_gateway/zilo.py`
  - Zilo 录音解码、16 kHz → 24 kHz 重采样和 20 ms 分帧

硬件方无需重新实现云端代理，只需在 Orange Pi 配置设备 Token、Zilo BLE 地址、
实际扬声器 `AudioSink` 和现有显示链路参数。

## 7. 现场验收

- [ ] 使用设备 Token 收到 `session.created` 和 `session.updated`
- [ ] 连续上传 20 ms PCM16 帧不报错
- [ ] 收到并解码非空 `response.audio.delta`
- [ ] 播放顺序正确，无固定 960 字节的错误假设
- [ ] `speech_started` 能清队列并发送 `response.cancel`
- [ ] 公开最终字幕只进入电脑/本地字幕，不成为墨水屏文本
- [ ] 连接后发送 `oc.capabilities / inner_os.v1`
- [ ] 收到 `oc.inner_os` 后生成最多 24 字的文字 + thinking 动画任务
- [ ] 显示编排器接受后回 `oc.inner_os.ack / accepted`
- [ ] WebSocket 断开后指数退避重连
- [ ] ESP32 固件和日志中不存在云端 Token 或 StepFun Key
