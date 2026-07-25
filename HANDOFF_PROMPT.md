# 给后续 Codex / Claude 的交接 Prompt

请只在完整交付仓库 `M:\code\hackthon\OOCC-delivery` 中工作；上传 VPS 后对应 `/opt/oocc`。

压缩包是无外层目录版本。解压后必须是 `/opt/oocc/apps`，不能是 `/opt/oocc/OOCC-delivery/apps`。部署后必须运行 `bash /opt/oocc/deploy/verify-production.sh`，并确认公网 Room 为 `BUILD 2026.07.25.13`；仅仅看到 systemd active 不算部署成功。

这个目录已经把 AdventureX 2026 OOCC 项目的四块运行代码收在一起：

- `apps/tv/Tower`：无限频道电视塔、OC 导入界面和 Day Loop 展示；
- `apps/room`：OO / CC 房间、StepFun 实时语音、外在回答与 Private OS Relay；
- `services/api`：OC 导入、Living World、DM 编排、RPG Rule Kernel、POV 和记忆；
- `hardware/orange-pi/gateway`：Orange Pi、Zilo 指环和墨水屏网关；
- `deploy`：VPS systemd 和 Nginx 配置。

先读 `README.md`、`SOURCE_MANIFEST.md` 和 `deploy/README.md`。不要回到旧工作树继续改，不要读取或提交 `.env`、令牌、聊天记录、Agent 计划、截图、日志、SQLite 数据库或 `.wrangler` 状态。

当前冻结边界：

1. OO / CC 的 Room、实时语音和 OC 签证链路可用。
2. 创作者文本可以生成并确认 OC，进入真实 Living World Day Loop。
3. 动态导入 OC 可以用自己的身份进入临时 Room，并从 `GET /api/ocs/{ocId}` 加载人格；没有素材时不借 OO/CC 立绘，也不绑定指环或墨水屏。
4. 新工作必须先补失败测试，再改代码；完成前运行 `scripts/verify.ps1`。
5. 目标不是扩功能，而是保证世界首页 `https://oc-voice.open.smn.icu/` 到 `/room/` 的 1–3 分钟现场 Demo 稳定。
6. StepFun/LLM 整体不可用时，只启用 `/fallback-demo/`；该页面必须持续明确标注 `LOCAL FALLBACK · NO LLM`，不得伪装成在线模型结果。
7. 冻结来源为 Living World `06ae52e`、Room/Voice `858f4a3`；Owner Journal 已按 scene/intent/check/observation/consequence/reflection/ownerConversation 分区，并保持单角色 POV 隔离；他人观察不暴露属性、骰点、DC、目标或动机。

不要继续开发世界编辑器、多人社交、NFC 社交或新 UI。只允许修复部署、真机硬件和主链稳定性问题。
