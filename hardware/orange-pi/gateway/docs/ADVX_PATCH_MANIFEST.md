# ADVX / OC Hardware Patch Manifest

生成日期：2026-07-24

## 输入与恢复点

- 硬件方输入：现场提供的 Web UI 与显示接口源码
- 原始源码备份：仅保留在开发机器，不进入公开仓库
- 真实 `screens.json` 未修改，也不属于交付文档或 Git 文件。

| 文件 | 原始 SHA-256 | 交付 SHA-256 |
|---|---|---|
| `server.py` | `7A80B4FE6B69DE3EA6A4FD603AF46C690CD48E11C24A3A2FA3D43EA54537D549` | `FF9C0798DA014CE4C6BB5DA600961A6F8321EAFDEAFA14D9DCDC52747327B8C2` |
| `orangepi_agent.py` | `6DF1F072D9EC3B73CEEC7F756218718975074E846A0EEFF6A7F39FD3DB5BFAF4` | `2843CD55909DA3001779C9647E4981D09FFC7B999112455C16E4829EF378C61B` |
| `bluetooth_renderer.py` | `1081DF8B04176ED2CDBDDF3234F8D3536B1900070CE954DA93824C37600EEEBC` | `39597AA8336365D99CBA31E92949769F30E1D40EAEDE8E42E578598AF6884329` |

## ADVX 修改

修改：

- `server.py`：鉴权 fail-closed、常量时间比较、Job 幂等、逐屏聚合。
- `orangepi_agent.py`：屏幕配置回退、逐屏鉴权、结果 LRU 缓存。
- `bluetooth_renderer.py`：目标预校验、多屏并发、错误隔离、完整文字模式。
- `API.md`：新增字段、逐屏结果、幂等与安全说明。
- `agent.env.example`：说明环境变量 key 就是逻辑屏幕 ID。

新增：

- `requirements-test.txt`
- `server.env.example`
- `CHANGELOG_OC.md`
- `HARDWARE_HANDOFF.md`
- `systemd/quote0-task-server.service`
- `systemd/quote0-agent.service`
- `tests/conftest.py`
- `tests/test_server.py`
- `tests/test_agent.py`
- `tests/test_bluetooth_renderer.py`
- `tests/test_systemd_units.py`

## OC Hardware Kit 修改

修改：

- `hardware-kit/pyproject.toml`
- `hardware-kit/.env.example`
- `hardware-kit/src/oc_gateway/__main__.py`
- `hardware-kit/src/oc_gateway/service.py`
- `hardware-kit/tests/test_package.py`
- `hardware-kit/tests/test_service.py`
- `hardware-kit/docs/HARDWARE_DISPLAY_API.md`
- `hardware-kit/docs/ORANGE_PI_RUNBOOK.md`

新增：

- `hardware-kit/src/oc_gateway/hardware_api.py`
- `hardware-kit/src/oc_gateway/zilo.py`
- `hardware-kit/tests/test_hardware_api.py`
- `hardware-kit/tests/test_zilo.py`
- `hardware-kit/docs/ADVX_PATCH_MANIFEST.md`

设计与计划同步：

- `docs/superpowers/specs/2026-07-24-advx-multiscreen-compat-design.md`
- `docs/superpowers/plans/2026-07-24-advx-multiscreen-zilo-integration.md`

另清理了旧计划中一条可识别的密钥签名，不更改任何运行 Secret。

## 自动验证

ADVX：

```bash
python -m pytest -q
python -m compileall -q server.py orangepi_agent.py bluetooth_renderer.py
```

结果：`20 passed`，编译检查退出码 0。

Hardware Kit：

```bash
python -m pytest -q
python -m compileall -q src
```

结果：`84 passed`，编译检查退出码 0。

网页实时语音回归：

```bash
npm.cmd test -- --run
npm.cmd run build
```

结果：`22 passed`，Vite 生产构建成功。

文档和仓库：

- `git diff --check` 通过；
- 占位标记扫描通过；
- 已知 StepFun Key 签名和常见长密钥模式扫描通过；
- 没有新增真实 Token、MAC、日志、录音、缓存或编译产物。

## Zilo 上游

- 仓库：`https://github.com/AdvxPlora2026/zilo-whisper-ring-sdk`
- 固定 commit：`94b342e1300c584020c84650321ceed1ad22b33a`
- 使用的公开接口：`RingSoundClient`、`receive_auto_audio_file`、`decode_speex_to_pcm`、`wait_sensor_key_double_press_event`
- SDK 不复制进当前仓库，Orange Pi 部署时单独 clone 并 checkout 固定 commit。

## 硬件负责人现场验收

下列项目未在本开发主机执行，不能宣称已经真机通过：

- ESP32 Bluetooth MAC、SPP channel 与 `/dev/rfcomm*` 绑定；
- EPD1 清屏、帧发送和实际 `EPD OK`；
- 两块墨水屏同时刷新和人为断开一屏；
- Zilo 真机完整录音、BLE 重连和双击事件；
- Orange Pi 同时运行 BLE 与两路 RFCOMM；
- 电脑临时扬声器和未来内置扬声器。

现场步骤、预期结果和排障见 ADVX 包中的 `HARDWARE_HANDOFF.md`。
