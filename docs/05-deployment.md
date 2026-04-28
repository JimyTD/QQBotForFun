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
#   SILICONFLOW_API_KEY
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

### 4.1 准备
- 一台 Linux 服务器（2核 2GB+）
- Docker + Docker Compose v2 已安装
- 放行端口（可选，仅当需外部访问 NapCat WebUI）

### 4.2 拉代码
```bash
git clone <repo-url> /opt/qqbot
cd /opt/qqbot
```

### 4.3 配置
```bash
cp .env.example .env
# 编辑 .env，修改：
#   APP_ENV=prod
#   DATABASE_URL=postgresql+asyncpg://qqbot:xxx@postgres:5432/qqbot
#   REDIS_URL=redis://redis:6379/0
#   ONEBOT_WS_URL=ws://napcat:3001
#   以及所有 API KEY
nano .env
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

# 升级代码
git pull
docker compose build bot
docker compose up -d bot
```

## 6. NapCat 账号维护

### 6.1 账号掉线
NapCat 少数情况会掉线：
1. `docker compose logs napcat` 查看原因
2. 重新扫码：访问 WebUI 或从日志获取登录 URL

### 6.2 换号
1. 停 NapCat：`docker compose stop napcat`
2. 清空 napcat 数据卷：`docker volume rm qqbot_napcat_data`
3. 重启并重新登录

## 7. 安全建议

- 防火墙**只开放必要端口**（SSH 22、HTTPS 443 若有 Web）
- NapCat WebUI（6099）**不对外开放**，需要时通过 SSH 隧道访问
- `.env` 文件权限设为 600
- API Key 定期轮换
- 数据库和 Redis 不暴露到公网

## 8. 故障排查

| 现象 | 检查 |
|---|---|
| bot 启动报 "OneBot connection failed" | NapCat 是否启动、`ONEBOT_WS_URL` 是否正确、token 是否一致 |
| bot 启动报 "DB connection refused" | postgres 是否健康、`DATABASE_URL` 是否正确 |
| LLM 调用 401 | API Key 是否正确、配额是否用完 |
| 群里发指令无反应 | NapCat 是否收到消息（看日志）、机器人是否被设为群管理员（部分指令需要） |
| `/play turtle_soup` 报 LLMError | 检查 LLM 配额、`config/llm.yaml` 配置 |
| 数据库表不存在 | `docker compose exec bot alembic upgrade head` |

## 9. 变更日志
| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
