# OOCC · Chapter 1：无限频道

AdventureX 2026 的统一交付仓库。它把此前分散的前端、Living World 算法、实时语音和硬件网关收进同一目录，队友只需要部署这一份。

> 核心体验：你的 OC 有自己的生命和生活，而不是笼中的金丝雀；但你永远有他们家门的钥匙。

## 已实现的演示链路

```text
粘贴创作者自己的 OC 设定
  → 生成“待确认”的角色卡与四项 RPG 属性
  → 用户确认后注册角色
  → OC 进入 Living World，按人设、目标、记忆和 RPG 属性行动
  → Scheduler 安排日程，DM 编排事件，Rule Kernel 负责检定与事实结果
  → 无限频道展示 OC 的公开位置、行动和事件结果
  → 点击 OC 的 Room，用实时语音和它交流
  → 电脑显示 OC 说出口的话；OC 签证墨水屏显示同一轮交流中没说出口的内心 OS
```

OO、CC 是完整演示角色：有专属房间、美术、实时语音和 OC 签证链路。用户导入 OC 也能以自己的身份进入临时 Room，并加载真实人设；没有素材时不会借用 OO/CC 的立绘，也暂不接指环和墨水屏。

## 仓库结构

```text
apps/tv/Tower/              无限频道、Bring Your OC、Living World 可视化
apps/room/                  Room、动态角色加载、StepFun 实时语音、VPS Relay
services/api/               OC 导入、Day Loop、DM/OCA、Rule Kernel、POV 与记忆
contracts/                  跨模块数据契约
fixtures/                   官方演示世界与角色运行数据
hardware/orange-pi/gateway/ Zilo 指环、Orange Pi、OC 签证/墨水屏网关
deploy/                     VPS 的 systemd 与 Nginx 配置
scripts/verify.ps1          四组件验证入口
```

## 功能状态

| 模块 | 当前状态 |
|---|---|
| OC 文字导入、审阅、确认与注册 | 已实现 |
| 角色卡人设 + RPG 属性 | 已实现；界面为认真、叛逆、体能、灵感，底层兼容既有 Rule Kernel 字段 |
| OCA 独立计划、DM 编排、Scheduler、D20 检定 | 已实现 |
| Canonical Ledger、单角色 POV、记忆、主人建议影响后续行动 | 已实现 |
| 当前 OC 的真实多日日记、默认最新日与前后翻页 | 已实现；严格拒绝跨角色 POV |
| 主人对话与实际 Private OS 经设备 ACK 后写入角色记忆 | 已实现；进入当前 OC 日记并影响次日，网页不暴露 Private OS 正文 |
| 无限频道世界页与公开状态 | 已实现 |
| OO/CC 专属 Room、实时语音、外在回答 / 内心 OS | 已实现 |
| 导入 OC 的动态 Room 与人格加载 | 已实现；无专属立绘、指环和墨水屏 |
| Orange Pi / Zilo / 墨水屏网关 | 已实现软件与协议；现场真机参数由硬件负责人配置 |
| NFC 社交、不同创作者共享世界、用户自建世界 | 展望，不属于本次 Demo |

## 本地启动

要求：Python 3.11+、Node.js 22+。

### 1. Living World API

```powershell
python -m pip install -e ".\services\api[test]"
$env:KALEIDOROOM_DB_PATH = "$env:TEMP\oocc-demo.sqlite3"
Set-Location services/api
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 2. Room 与实时语音

```powershell
Set-Location apps/room
npm ci
$env:STEPFUN_API_KEY = "只在本机环境设置，不写入仓库"
$env:OC_DEVICE_TOKEN = "给 Orange Pi 的独立设备令牌"
npm run dev -- --host 127.0.0.1 --port 4174
```

### 3. 无限频道

```powershell
$env:TV_DEMO_API_BASE = "http://127.0.0.1:8000"
$env:PORT = "5177"
Set-Location apps/tv/Tower
node demo-server.cjs
```

浏览器打开：

```text
http://127.0.0.1:5177/?roomApp=http%3A%2F%2F127.0.0.1%3A4174%2F
```

### 4. Orange Pi 网关

网关部署在 Orange Pi，而不是 Web VPS。见 [hardware/orange-pi/gateway/docs/ORANGE_PI_RUNBOOK.md](hardware/orange-pi/gateway/docs/ORANGE_PI_RUNBOOK.md)。公网地址配置为：

```dotenv
OC_VOICE_PROVIDER=cloud
OC_CLOUD_BASE_URL=https://oc-voice.open.smn.icu
```

## VPS 部署

服务器目录固定为 `/opt/oocc`，公开入口为：

```text
https://oc-voice.open.smn.icu/
```

详细命令见 [deploy/README.md](deploy/README.md)。部署后由同一域名提供：

- `/`：无限频道世界页；
- `/room/`：Room 与实时语音前端；
- `/tower/`：世界页兼容入口；
- `/api/living-world/*`、`/api/oc-imports/*`、`/api/ocs/*`：Living World API；
- `/api/realtime`、`/api/device/*`：语音与硬件 WebSocket。

## 环境变量与秘密

仓库只包含 `.env.example`。真实值只能放在 VPS 的 `/etc/oocc/room.env` 或 Orange Pi 的 `/etc/oc-gatewayd.env`：

```dotenv
STEPFUN_API_KEY=...
OC_DEVICE_TOKEN=...
PORT=8765
OC_STATIC_DIR=/opt/oocc/apps/room/dist
```

不要提交 `.env`、令牌、数据库、日志、聊天记录、截图或 Agent 工作文档。

## 验证

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

部署后验证公网 StepFun 会话、角色化文本和音频返回：

```powershell
Set-Location apps/room
$env:SMOKE_BASE_URL = "https://oc-voice.open.smn.icu"
node scripts/public-voice-smoke.cjs
```

最近冻结基线：

- TV：58/58；
- Room/Voice：155/155，`typecheck:relay` 与 `build:vps` 通过；
- Living World：193 项全量基线通过，Ruff 通过；
- Orange Pi Gateway：全部测试断言通过。

## 已知边界

1. 导入 OC 的角色卡整理当前使用确定性编译器：它只整理用户原文并要求用户确认，不擅自替用户写人设。
2. 导入 OC 的临时 Room 可对话，但没有专属美术、Zilo/墨水屏绑定。
3. 真机 BLE 地址、墨水屏目标、RFCOMM 与设备令牌必须由硬件负责人现场配置。
4. 不要在赛前继续扩张 Studio、自建世界或多人社交；先保证 1 分钟主链稳定。

## LLM 故障降级演示

VPS 构建 Room 后，备用入口为：

```text
https://oc-voice.open.smn.icu/fallback-demo/
```

它完全在浏览器本地运行，不调用 LLM、API 或 WebSocket。用户仍可输入一句话并切换 OO/CC；电脑侧展示确定性外在回答，OC 签证侧展示对应的反差内心 OS，并明确标注 `LOCAL FALLBACK · NO LLM`。它不写入 Living World Canon，只用于上游模型故障时保证现场核心概念仍可操作演示。

Living World 的 Planner/Journal 本身已有无 Key fallback；Private OS 生成也已有超时 fallback。这个页面补齐的是“实时语音上游整体不可用”时的现场展示保底。

## 来源版本

- Living World：`kaleidoroom@06ae52e`（含对话记忆、结构化单 POV 日记与观察信息脱敏）
- TV：`TV-Demo agent/bring-your-oc-tv@c848e89`
- Room / Voice：`oc-eink-demo feature/fullscreen-room-voice-ui@858f4a3`
- Orange Pi：`oc-eink-demo feature/orange-pi-hardware-kit@132fa51`

给下一位开发者或 AI 的接手说明见 [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md)。
#adventurex2026
