# VPS 紧急发布 Prompt

请将 `OOCC-delivery-20260725-final-v4-root.zip` 发布到现有 OOCC VPS。当前公网 Room 错误地仍在运行 `BUILD 2026.07.25.11`；目标是 `BUILD 2026.07.25.13`。

必须遵守：

1. 先校验压缩包 SHA256：`EBE07B4EDE2CE7BE18D00BC1F64E4E84E7886E9A440F14E9147577AD66799F8D`。
2. 压缩包是无外层目录版本。解压到临时目录后必须存在 `apps/room/package.json`，不得出现 `OOCC-delivery/apps` 中间层。
3. 把临时目录的**内容**同步到 `/opt/oocc/`；保留 `/opt/oocc/.venv`，不要触碰 `/etc/oocc/room.env` 与 `/var/lib/oocc`。
4. 在 `/opt/oocc/services/api` 更新 Python 依赖。
5. 在 `/opt/oocc/apps/room` 执行 `npm ci && npm run typecheck:relay && npm run build:vps`。
6. 确认 `/opt/oocc/apps/room/dist` 中包含 `BUILD 2026.07.25.13`。
7. 重启 `oocc-api`、`oocc-tv`、`oocc-room`，执行 `nginx -t` 后 reload。
8. 最后必须执行：`bash /opt/oocc/deploy/verify-production.sh`。只有输出 `OOCC production verified: BUILD 2026.07.25.13` 才算成功。
9. 回报三个 systemd 状态、最终公网 Room JS 资产 URL、验证脚本输出和浏览器进入 OO Room 的结果。

不要修改代码，不要重新设计目录，不要把真实密钥打印到日志或聊天中。
