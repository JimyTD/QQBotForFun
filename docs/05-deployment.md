# 05 · 部署指南

- **Status**: Draft v1
- **Last Updated**: 2026-04-28
- **Owner**: @owner

## 1. 总览

两个场景：
- **本地开发（Windows）**：NapCat（Docker Desktop）+ Bot（Python 直跑，热重载）+ SQLite
- **生产（Linux 云服务器）**：全部容器化（NapCat + Bot + PostgreSQL + Redis）

## 2. 环境要求

| 项 | 本地 | 生产 |
|---|---|---|
| OS | Windows 10/11 | Linux（Ubuntu 22.04+ 推荐） |
| Python | 3.11 | 容器提供 |
| uv | 最新 | — |
| Docker | Desktop | Engine + Compose |
| 内存 | ≥ 4GB | ≥ 2GB |
| 磁盘 | ≥ 10GB | ≥ 20GB |
| QQ 小号 | 1 个 | 同一个 |

## 3. 本地开发部署

### 3.1 拉代码
```powershell
git clone <repo-url> QQBotForFun
cd QQBotForFun
```

### 3.2 安装 Python 依赖
```powershell
# 安装 uv（如未安装）
pip install uv

# 同步依赖
uv sync
```

### 3.3 启动 NapCat（Docker Desktop）
```powershell
docker compose -f docker-compose.dev.yml up -d napcat
```
然后：
1. 浏览器打开 `http://localhost:6099`（NapCat Web UI）
2. 扫码登录**专用 QQ 小号**（切勿主号）
3. WebUI 中设置"反向 WebSocket 客户端"，地址：`ws://host.docker.internal:8080/onebot/v11/ws`，Token 任意（与 `.env` 一致）

> **关键**：开发模式下 NapCat 在容器里，Bot 在 Windows 原生，所以 NapCat 反连 Bot 要走 `host.docker.internal`。

### 3.4 配置环境变量
```powershell
copy .env.example .env
# 编辑 .env 填入：
#   ONEBOT_ACCESS_TOKEN（与 NapCat 一致）
#   ADMIN_QQ（你的主号）
#   ZHIPU_API_KEY
#   LONGCAT_API_KEY（查资料兜底，可选）
notepad .env
```

### 3.5 初始化数据库
```powershell
# 创建 data 目录
mkdir data

# 运行迁移
uv run alembic upgrade head

# Seed 海龟汤题库
uv run python scripts/seed_turtle_soup.py
```

### 3.6 启动 Bot
```powershell
uv run python -m src.bot
```

看到类似日志即表示连上 NapCat：
```
INFO | Connected to OneBot: self_id=10086
```

### 3.7 自测
1. 拉机器人小号进测试群
2. 群里发 `/menu` → 应返回游戏大厅
3. 发 `/play turtle_soup` → 开始一局海龟汤

## 4. 生产部署（Linux 云服务器）

> **当前生产环境的日常运维请直接看 `docs/ops-guide.md`**（含固定参数、Git 同步流程、铁律）。
> 本节保留「从零搭建一台新服务器」的完整步骤，供灾难重建或迁移新机时参考。

### 4.1 准备
- 一台 Linux 服务器（2核 2GB+）
- Docker + Docker Compose v2 已安装
- 放行端口（可选，仅当需外部访问 NapCat WebUI）

### 4.2 拉代码

⚠️ **国内服务器直连 GitHub 通常不通**（实测当前生产机 TCP 443 被拒），需走镜像：

```bash
# 镜像 clone（推荐）
git clone https://ghfast.top/https://github.com/JimyTD/QQBotForFun.git /root/qqbot
cd /root/qqbot

# 配置双 remote：origin 存真实地址，mirror 用于实际拉取
git remote set-url origin https://github.com/JimyTD/QQBotForFun.git
git remote add mirror https://ghfast.top/https://github.com/JimyTD/QQBotForFun.git
```

> 备用镜像：`https://gh-proxy.com/https://github.com/JimyTD/QQBotForFun.git`
> 生产路径约定为 `/root/qqbot`（真实目录，永不重命名/删除/做符号链接）。

### 4.3 配置

⚠️ `.env` **永不入 git**，必须手工创建（含真实密钥）：

```bash
cp .env.example .env
# 编辑 .env，修改：
#   APP_ENV=prod
#   DATABASE_URL=postgresql+asyncpg://qqbot:qqbot_pass@postgres:5432/qqbot
#   REDIS_URL=redis://redis:6379/0
#   ONEBOT_ACCESS_TOKEN（与 NapCat WebSocket 配置一致）
#   ZHIPU_API_KEY / LONGCAT_API_KEY 等
nano .env

# 立刻建立备份（.env 是唯一权威来源，本地无副本）
cp .env /root/.env_qqbot_backup
chmod 600 .env
```

### 4.3.1 创建 external volumes（首次必做）

`docker-compose.yml` 使用 external volume，确保数据与目录解耦：

```bash
docker volume create qqbot_pg_data
docker volume create qqbot_redis_data
docker volume create qqbot_napcat_data
```

### 4.4 启动
```bash
docker compose up -d
docker compose logs -f bot
```

首次启动会自动：
1. 拉起 postgres / redis / napcat / bot 四个容器
2. bot 容器内执行 `alembic upgrade head`
3. bot 容器内执行 `python scripts/seed_turtle_soup.py`（幂等）

### 4.5 NapCat 首次登录
```bash
# 查看 NapCat 日志获取登录方式
docker compose logs napcat

# 或访问 WebUI（如果你映射了端口）
#   http://<server-ip>:6099
```
用手机扫码登录 QQ 小号。**登录成功后**，NapCat 会自动连到 bot 服务（compose 网络内部通信）。

### 4.6 验证
```bash
# 查看 bot 日志
docker compose logs -f bot

# 应看到：
#   Bot started
#   Connected to OneBot: self_id=xxxxx
```

在测试群发 `/menu` 验证。

## 5. 运维常用命令

```bash
# 重启 bot（不重启 NapCat）
docker compose restart bot

# 查看日志
docker compose logs -f bot --tail=200

# 进入 bot 容器
docker compose exec bot bash

# 执行迁移
docker compose exec bot alembic upgrade head

# 数据库备份（每日 cron 推荐）
docker compose exec postgres pg_dump -U qqbot qqbot > backup_$(date +%F).sql

# 升级代码（⚠️ 生产环境请走 docs/ops-guide.md §1，不要用 git pull）
git fetch mirror main
docker compose stop bot && docker compose rm -f bot
git reset --hard mirror/main
docker compose up -d --build bot
```

> ⚠️ **生产环境注意**：
> - 服务器直连 GitHub 不通，必须走镜像 remote（`mirror`），详见 `docs/ops-guide.md`
> - 禁止 `git pull`（可能触发 merge/交互），统一用 `fetch` + `reset --hard`
> - 禁止 `git clean -fdx`（会删除 `.env` 和 `logs/`）
> - 生产路径是 `/root/qqbot`

## 6. NapCat 账号维护

### 6.1 账号掉线

⚠️ **关键**：`Bot xxx connected` 只代表 Bot ↔ NapCat 的 WebSocket 通了，**不代表 QQ 账号在线**。
账号被踢下线时 WebSocket 照样 connected，但收不到任何群消息。必须分开确认：

```bash
# 查 QQ 账号是否离线
docker compose logs napcat 2>&1 | grep -iE 'KickedOffLine|账号状态变更|offline' | tail -5
```

处理：
1. 若有 `KickedOffLine` / `账号状态变更为离线` → 需重新扫码
2. 扫码前**必须**确认 NapCat 的 WebSocket 配置不为空（`ws_clients` ≥ 1），否则登录了也收不到消息 —— 详见 `docs/ops-guide.md` §3
3. 若报「当前账号已登录,无法重复登录」但实际是离线状态 → NapCat 内部状态残留，`docker compose restart napcat` 清掉后会生成新二维码
4. 缓存的 `/app/napcat/cache/qrcode.png` 可能是很久以前的过期码，必须 restart 后取新码

### 6.2 换号
1. 停 NapCat：`docker compose stop napcat`
2. 清空 napcat 数据卷：`docker volume rm qqbot_napcat_data`
3. 重启并重新登录

> ⚠️ 日常运维中禁止 `docker compose down` 或删除 NapCat 容器——会导致必须重新扫码。只有换号才做 6.2。

## 7. 安全建议

- 防火墙**只开放必要端口**（SSH 22、HTTPS 443 若有 Web）
- NapCat WebUI（6099）**不对外开放**，需要时通过 SSH 隧道访问
- `.env` 文件权限设为 600
- API Key 定期轮换
- 数据库和 Redis 不暴露到公网

### 7.1 密钥管理铁律

- 🔴 **`.env` 永不入 git**。本仓库历史上曾误提交过一次（commit `66e2df6`），导致密钥在 public 仓库泄露，不得重演
- 🔴 **禁止 `git clean -fdx` / `-fx`** —— `-x` 会删除 ignored 文件，即 `.env` 和 `logs/`
- ✅ `.env` 唯一权威来源是服务器上的文件，备份于 `/root/.env_qqbot_backup`，改动后必须同步更新备份
- ✅ `config/llm.yaml` 只用 `${ZHIPU_API_KEY}` 占位符，真值从 `.env` 注入 —— 轮换密钥只改 `.env`，不动 yaml
- ⚠️ **若仓库转为 private**，禁止继续用第三方镜像 + PAT 拉取（凭证会明文经过第三方），必须改用 SSH deploy key 或自建代理

密钥轮换流程见 `docs/ops-guide.md` §5。

## 8. 故障排查

| 现象 | 检查 |
|---|---|
| bot 启动报 "OneBot connection failed" | NapCat 是否启动、`ONEBOT_WS_URL` 是否正确、token 是否一致 |
| bot 启动报 "DB connection refused" | postgres 是否健康、`DATABASE_URL` 是否正确 |
| LLM 调用 401 | API Key 是否正确、配额是否用完 |
| 群里发指令无反应，但日志有 `Bot xxx connected` | **QQ 账号可能已离线**（connected ≠ 在线），查 §6.1 |
| 群里发指令无反应 | NapCat 是否收到消息（看日志）、机器人是否被设为群管理员（部分指令需要） |
| `/play turtle_soup` 报 LLMError | 检查 LLM 配额、`config/llm.yaml` 配置 |
| 数据库表不存在 | `docker compose exec bot alembic upgrade head` |
| 服务器代码看起来没更新 | `cd /root/qqbot && git rev-parse --short HEAD` 对比本地；`git status --short` 查是否有人手改造成漂移 |

## 9. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
| v2 | 2026-08-28 | 生产同步方式改为 Git（镜像 remote + `fetch`/`reset --hard`）；生产路径更正为 `/root/qqbot`；补充 external volume 创建步骤、密钥管理铁律（§7.1）、NapCat「connected ≠ 在线」排查经验（§6.1） |
