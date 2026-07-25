# Orange Pi 3B 语音与墨水屏网关运行手册

批准的演示拓扑：

```text
电脑麦克风 → 浏览器 → Cloudflare → StepFun Realtime → 电脑扬声器

Zilo 长按录音 → 松开保存 → BLE 完整录音 → Orange Pi
                                        └→ StepFun Realtime → 电脑扬声器

OC Gateway → 本机 ADVX Task Server → 本机 Agent
                                      └→ RFCOMM → ESP32 → 墨水屏
```

电脑端是实时全双工；Zilo 当前是录完上传，不是连续实时流。StepFun Key 只保存在 Cloudflare，Orange Pi 只使用独立 `OC_DEVICE_TOKEN`。

公开语音/字幕和墨水屏 Private OS 是两条独立通路。公开回答继续到电脑；云端另行
下发最多 24 字的 `oc.inner_os`，Orange Pi 再把它映射为现有文字+动画任务。
Private OS 失败不得让实时语音重连或中止。

本仓库保留网关、协议和现场运行步骤；厂商 Task Server、Agent 与屏幕资产由硬件负责人另行安装。

## 系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
  bluez bluez-tools ffmpeg fonts-noto-cjk rfkill git
sudo rfkill unblock bluetooth
sudo usermod -aG dialout,bluetooth orangepi
```

重新登录后安装 Gateway：

```bash
cd /opt/oocc/hardware/orange-pi/gateway
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test,zilo]"
python -m pytest -q
```

安装固定版本 Zilo SDK：

```bash
cd /opt
git clone https://github.com/AdvxPlora2026/zilo-whisper-ring-sdk.git
cd zilo-whisper-ring-sdk
git checkout 94b342e1300c584020c84650321ceed1ad22b33a
```

## 环境文件

复制示例：

```bash
sudo cp /opt/oocc/hardware/orange-pi/gateway/.env.example /etc/oc-gatewayd.env
sudo chown orangepi:orangepi /etc/oc-gatewayd.env
sudo chmod 600 /etc/oc-gatewayd.env
```

真实硬件配置：

```dotenv
OC_VOICE_PROVIDER=cloud
OC_CLOUD_BASE_URL=https://oc-voice.open.smn.icu
OC_DEVICE_TOKEN=replace-with-device-only-token
OC_DEVICE_ID=orangepi-3b-01
OC_CHARACTER=devil
OC_BIND_HOST=0.0.0.0
OC_BIND_PORT=8787

OC_DISPLAY_TRANSPORT=advx
OC_HARDWARE_SERVER_URL=http://127.0.0.1:8781
OC_HARDWARE_SERVER_TOKEN=replace-with-advx-server-token
OC_HARDWARE_AGENT_ID=orangepi-3b-01
OC_HARDWARE_TARGETS=["left","right"]
OC_HARDWARE_SCREEN_TOKENS={"left":"","right":""}
OC_HARDWARE_ASSET_DIR=/opt/oc-hardware-gateway/assets

OC_RING_SOURCE=zilo-recorded
OC_ZILO_ADDRESS=<ZILO_BLE_MAC>
OC_ZILO_SDK_PATH=/opt/zilo-whisper-ring-sdk
OC_FFMPEG_PATH=/usr/bin/ffmpeg
```

要求：

- `OC_HARDWARE_TARGETS` 是非空 JSON 字符串数组；
- `OC_HARDWARE_SCREEN_TOKENS` 的 key 必须属于 targets；
- 如果 ADVX `screens.json` 中某屏 Token 非空，这里必须填相同值；
- `OC_HARDWARE_ASSET_DIR` 必须已经存在；
- Zilo 模式启动前会检查 `ring_sound.py` 和 ffmpeg；
- 真实 Token 不进入 Git、群聊、日志或截图。

## 资产

```text
/opt/oc-hardware-gateway/assets/
  devil_idle/v1/frame_000.bmp
  devil_listening/v1/frame_000.bmp
  devil_thinking/v1/frame_000.bmp
  devil_speaking/v1/frame_000.bmp
  angel_idle/v1/frame_000.bmp
```

图片使用 `image.bmp/png`，动画使用 `frame_*.bmp/png`。目录版本必须匹配 Scene 中的 `asset_version`。

## 启动

在 Task Server 和 Agent 已经运行后：

```bash
set -a
. /etc/oc-gatewayd.env
set +a
oc-gateway
```

健康检查：

```bash
curl http://127.0.0.1:8787/health
```

局域网电脑打开：

```text
http://orangepi.local:8787/speaker/
```

点击“连接并允许播放”。演示期建议戴耳机，避免电脑扬声器被戒指再次录入。

## systemd

```bash
sudo cp systemd/oc-gatewayd.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oc-gatewayd
sudo systemctl status oc-gatewayd
journalctl -u oc-gatewayd -f
```

修改环境文件后：

```bash
sudo systemctl restart oc-gatewayd
```

Task Server、Agent、RFCOMM 与屏幕资产由硬件负责人按照现场设备版本配置；本 Gateway 只依赖本文列出的 HTTP/任务协议。

## 四任务本地联调

仍可通过 Orange Pi 本地入口提交四种 Scene：

```bash
oc-display text "主人，该喝水了" --style devil_reminder
oc-display animation devil_thinking --loop 2
oc-display image devil_low_battery
oc-display scene "我在想啦" devil_thinking \
  --style devil_thinking --loop 1
```

设置 `OC_DISPLAY_TRANSPORT=mock` 可以在没有 ESP32 时做软件冒烟；设置为 `advx` 才会进入真实多屏链路。鉴权失败不会静默回退到 Mock。

## 无戒指 WAV 冒烟

```dotenv
OC_RING_SOURCE=wav
OC_WAV_INPUT=/opt/oc-hardware-gateway/smoke.wav
```

WAV 必须为单声道 PCM16，采样率可以不是 24 kHz。它会线性重采样并添加 500 ms 前静音、1,000 ms 后静音。

不使用任何戒指输入：

```dotenv
OC_RING_SOURCE=none
```

## Zilo 行为

软件调用固定 commit 的公开接口：

- `RingSoundClient(address=...)`；
- `receive_auto_audio_file(client)`；
- `decode_speex_to_pcm(...)`；
- `wait_sensor_key_double_press_event(client)`。

录音保存后才会收到完整 Speex 数据。Gateway 验证 16 kHz/mono/PCM16，重采样到 24 kHz，按 20 ms/960 字节发送给 StepFun。文件索引去重缓存上限为 256；BLE 断开后每 5 秒重连；坏录音只丢当前一段。

双击戒指会清空电脑播放队列并发送 `response.cancel`，但这不是语音 VAD 插话。

## 云模式和直连排障

推荐：

```dotenv
OC_VOICE_PROVIDER=cloud
```

只有排查云网关时才临时直连：

```dotenv
OC_VOICE_PROVIDER=direct
OC_STEPFUN_API_KEY=replace-with-temporary-test-key
```

排障结束恢复 cloud 并删除本地 Key。不得复用其他项目 Token。

## 排障

| 症状 | 检查与处理 |
|---|---|
| Zilo 没有录音 | MAC、BlueZ 权限、是否完成“长按→松开→保存”；当前不是按下即流式传输 |
| Zilo 解码失败 | `/usr/bin/ffmpeg`、SDK commit、Speex 文件完整性 |
| 显示鉴权失败 | Server Token、逐屏 Token 和 targets 是否一致；不会回退 Mock |
| 无屏幕 ACK | Agent 日志、`/dev/rfcomm*`、SPP channel、ESP32 EPD1 |
| 只有一屏失败 | 查 Job `target_results`；另一屏仍可成功 |
| 电脑没有声音 | speaker 页面授权、8787 端口、浏览器 AudioContext |
| 公网页面提示戒指已被占用 | 云端已有另一个 Room View 持有相同 `OC_DEVICE_ID`；关闭原页面或点击结束，云端会自动释放 |
| 本地 speaker 提示已被占用 | 已有另一个局域网页面持有 `/v1/audio-sink`；关闭原页面后自动释放 |
| 回声或模型自言自语 | 使用耳机；未来内置扬声器需要 AEC far-end reference |
| WSS 很快关闭 | `OC_DEVICE_TOKEN`、系统时间、DNS/TLS；401 为鉴权，429 为并发 |
| 网页显示“内心 OS 暂未接通” | 确认本版 `voice.py` 连接后发送 `oc.capabilities`；检查设备 WSS 是否在线 |
| 网页一直显示“已接通”但不显示“已下发” | 检查是否收到 `oc.inner_os`、显示任务是否被编排器接受、是否回传 `oc.inner_os.ack` |

## 真机验收边界

自动测试覆盖四任务映射、资产版本、多屏结果、Zilo 解码/重采样/去重/重连和双击取消。以下只能由现场硬件负责人确认：

- ESP32 MAC、SPP channel 和 `/dev/rfcomm*`；
- 实际 EPD ACK 和屏幕刷新；
- Orange Pi 同时运行 BLE 与多路 RFCOMM；
- Zilo 真机录音质量；
- 电脑临时扬声器和未来硬件扬声器。
- Private OS 在真实墨水屏上的换行、残影、停留时间和逐屏 ACK。
