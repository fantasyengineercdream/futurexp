# VPS 部署手册

适用于 Ubuntu / Debian、Node.js 22+、Python 3.11+，目标目录固定为 `/opt/oocc`。

## 1. 上传代码

把交付包的**内容**上传到 `/opt/oocc`。解压后必须直接存在 `/opt/oocc/apps`、`/opt/oocc/services`、`/opt/oocc/deploy`；禁止出现 `/opt/oocc/OOCC-delivery/apps` 这一层，否则 systemd 会继续运行旧代码。仓库中不得包含真实 `.env`、数据库、日志或令牌。

```bash
sudo mkdir -p /opt/oocc /var/lib/oocc /etc/oocc
sudo chown -R "$USER":"$USER" /opt/oocc
cd /opt/oocc
test -f /opt/oocc/apps/room/package.json
test -f /opt/oocc/services/api/pyproject.toml
```

## 2. 安装依赖与构建

```bash
python3 -m venv /opt/oocc/.venv
/opt/oocc/.venv/bin/pip install -e /opt/oocc/services/api

cd /opt/oocc/apps/room
npm ci
npm run typecheck:relay
npm run build:vps
```

构建成功后，交给服务账号读取代码，并让它能写运行数据库：

```bash
sudo chown -R www-data:www-data /opt/oocc /var/lib/oocc
sudo find /opt/oocc -type d -exec chmod 755 {} \;
sudo find /opt/oocc -type f -exec chmod 644 {} \;
sudo chmod 755 /opt/oocc/.venv/bin/*
```

## 3. 配置秘密

只在服务器创建 `/etc/oocc/room.env`：

```dotenv
STEPFUN_API_KEY=replace-on-server
OC_DEVICE_TOKEN=replace-with-dedicated-device-token
LIVING_WORLD_API_BASE_URL=http://127.0.0.1:8000
PORT=8765
OC_STATIC_DIR=/opt/oocc/apps/room/dist
```

```bash
sudo chown root:www-data /etc/oocc/room.env
sudo chmod 640 /etc/oocc/room.env
```

不要把该文件复制回仓库或发到群聊。

## 4. 安装三个服务

```bash
sudo cp /opt/oocc/deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now oocc-api oocc-tv oocc-room
sudo systemctl restart oocc-api oocc-tv oocc-room
```

检查：

```bash
systemctl --no-pager --full status oocc-api oocc-tv oocc-room
journalctl -u oocc-api -u oocc-tv -u oocc-room -n 100 --no-pager
```

## 5. Nginx

把 [nginx/oc-voice.open.smn.icu.conf](nginx/oc-voice.open.smn.icu.conf) 中的 `location` 配置合并到 `oc-voice.open.smn.icu` 已有的 HTTPS `server` block。不要覆盖现有证书配置。

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 6. 验收

```bash
curl -fsS http://127.0.0.1:8000/docs >/dev/null
curl -fsS http://127.0.0.1:5177/ >/dev/null
curl -fsS http://127.0.0.1:8765/api/health
curl -fsS https://oc-voice.open.smn.icu/ >/dev/null
curl -fsS https://oc-voice.open.smn.icu/room/ >/dev/null
bash /opt/oocc/deploy/verify-production.sh
```

浏览器手动走一遍：

1. 打开世界首页 `https://oc-voice.open.smn.icu/`；
2. 确认 OO、CC、奶蛙与公开 Day Loop 正常；
3. 粘贴一段 OC 设定，审阅四项 RPG 属性并确认加入；
4. 确认新 OC 出现在 Living World，并以自己的身份进入临时 Room；
5. 进入 OO 或 CC 的 Room，完成一轮实时语音；
6. Orange Pi 在线时确认它收到 `oc.inner_os` 并向墨水屏 ACK。
7. 断开模型上游后打开 `https://oc-voice.open.smn.icu/fallback-demo/`，确认本地降级演示仍可输入、切换 OO/CC，并同时显示外在回答和内心 OS。

## 7. 更新

```bash
cd /opt/oocc
# 替换代码或 git pull 后：
/opt/oocc/.venv/bin/pip install -e /opt/oocc/services/api
cd /opt/oocc/apps/room && npm ci && npm run build:vps
sudo chown -R www-data:www-data /opt/oocc /var/lib/oocc
sudo systemctl restart oocc-api oocc-tv oocc-room
sudo nginx -t && sudo systemctl reload nginx
```

若硬件只需要调试语音/内心 OS，不必在 VPS 安装 Orange Pi Gateway；它运行在 Orange Pi 上，并通过 `OC_DEVICE_TOKEN` 连接本域名。
