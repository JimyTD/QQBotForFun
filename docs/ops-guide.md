# 运维手册

> 通过 CodeBuddy 的 Lighthouse 集成管理 QQ 机器人

## 服务器信息

| 项目 | 值 |
|------|------|
| 实例 ID | lhins-hwnz7rcz |
| 地域 | ap-guangzhou |
| 服务器 IP | 106.55.228.236 |
| 项目路径 | `/root/QQBotForFun_20260508113003` |
| Bot QQ 号 | 3959381140 |
| NapCat WebUI | http://106.55.228.236:6099 |
| OneBot Token | `qqbot_fun_token_2026` |
| Searxng | 内网 `http://searxng:8080`（不对外暴露） |

---

## 一、机器人没反应时的排查流程

依次执行：

### 1. 检查容器状态

```
cd /root/QQBotForFun_20260502112049 && docker compose ps
```

正常：4 个容器都 `Up`，postgres 为 `healthy`。

### 2. 检查 NapCat 是否掉线

```
cd /root/QQBotForFun_20260502112049 && docker compose logs napcat 2>&1 | grep -i 'kicked\|offline\|失效' | tail -3
```

如果有 `KickedOffLine` 记录，说明 QQ 掉线了，需要重新登录（见下方）。

### 3. 检查 Bot 和 NapCat 的 WebSocket 连接

```
cd /root/QQBotForFun_20260502112049 && docker compose logs bot 2>&1 | grep 'connected' | tail -1
```

如果最后连接时间是很久以前，说明 NapCat 掉线后没重连。

---

## 二、NapCat 重新登录

QQ 新号容易被风控踢下线，恢复步骤：

### 1. 重启 NapCat

```
cd /root/QQBotForFun_20260502112049 && docker compose restart napcat
```

### 2. 获取 WebUI Token

```
cd /root/QQBotForFun_20260502112049 && docker compose logs napcat 2>&1 | grep 'WebUi Token' | tail -1
```

### 3. 浏览器扫码

打开 http://106.55.228.236:6099 ，输入 Token，扫码登录。

### 4. 确认连接成功

```
cd /root/QQBotForFun_20260502112049 && docker compose logs bot --tail 5
```

应该看到 `Bot 3959381140 connected`。

---

## 三、更新代码后重新部署

本地改完代码后：

### 1. 上传项目

使用 Lighthouse 集成的 `deploy_project_preparation` 工具上传项目。

### 2. 配置新目录

```
# 复制 .env（替换 NEW_DIR 为实际新路径）
cp /root/QQBotForFun_20260502112049/.env /root/NEW_DIR/.env
```

### 3. Dockerfile 镜像加速补丁

```
cd /root/NEW_DIR && python3 << 'PYEOF'
with open('Dockerfile','r') as f: c=f.read()
c=c.replace("RUN apt-get update","RUN sed -i 's@deb.debian.org@mirrors.cloud.tencent.com@g' /etc/apt/sources.list.d/debian.sources && apt-get update")
c=c.replace('RUN pip install uv','RUN pip install -i https://mirrors.cloud.tencent.com/pypi/simple uv')
c=c.replace('RUN uv pip install --system .','RUN uv pip install --system --index-url https://mirrors.cloud.tencent.com/pypi/simple .')
c=c.replace('COPY pyproject.toml ./','COPY pyproject.toml README.md ./')
with open('Dockerfile','w') as f: f.write(c)
print('Dockerfile patched')
PYEOF
```

### 4. 切换部署

```
cd /root/OLD_DIR && docker compose down
cd /root/NEW_DIR && docker compose up -d
```

### 4.5 数据库迁移（重要！）

新版本如果包含新的数据模型（ORM 表），需要在 bot 启动后执行迁移：

```bash
# 方式 1：用 alembic（推荐，如果有 migration 文件）
cd /root/NEW_DIR && docker compose exec -T bot alembic upgrade head

# 方式 2：手动建表（如果还没生成 migration）
# 查看 bot 日志是否有 "UndefinedTableError" 报错，根据对应的 models.py 手动建表：
cd /root/NEW_DIR && docker compose exec -T postgres psql -U qqbot qqbot -c "CREATE TABLE IF NOT EXISTS <表名> (...);"
# 建表后重启 bot：
docker compose restart bot
```

**如何判断是否需要迁移：** 部署后检查 bot 日志，如果看到 `UndefinedTableError` 或 `relation "xxx" does not exist`，就需要建表。

### 5. 写入 NapCat WebSocket 配置

```
cd /root/NEW_DIR && docker compose exec napcat sh -c 'cat > /app/napcat/config/onebot11_3959381140.json << EOF
{"network":{"httpServers":[],"httpSseServers":[],"httpClients":[],"websocketServers":[],"websocketClients":[{"enable":true,"name":"qqbot","url":"ws://bot:8080/onebot/v11/ws","messagePostFormat":"array","reconnectInterval":3000,"token":"qqbot_fun_token_2026","heartInterval":30000}],"plugins":[]},"musicSignUrl":"","enableLocalFile2Url":false,"parseMultMsg":false,"imageDownloadProxy":"","timeout":{"baseTimeout":10000,"uploadSpeedKBps":256,"downloadSpeedKBps":256,"maxTimeout":1800000}}
EOF'
docker compose restart napcat
```

### 6. 去 WebUI 扫码登录

---

## 四、仅更新 Bot 代码（推荐，不需要扫码）

**绝大多数部署应该用这个方式**（只要没改 `docker-compose.yml`）：

```
cd /root/<新项目目录> && docker compose up -d --build bot
```

NapCat 不会受影响，**不需要重新扫码**。

> ⚠️ 仅当修改了 `docker-compose.yml`（如新增/删除服务、改端口映射等）时，
> 才需要用"三、更新代码后重新部署"中的 `docker compose down` + `docker compose up -d` 全流程。
> 全流程会重启 NapCat，需要重新扫码。

---

## 五、关键注意事项

- **NapCat 和 Bot 是两个独立容器**，文件系统隔离。Bot 容器里的文件 NapCat 读不到（图片要用 base64 发送）。
- **NapCat 每次重启都需要重新扫码**，且重启后 WebSocket 配置可能被重置为空，需要重新写入。
- **新 QQ 号前几天容易被风控踢下线**，养号几天后会稳定。
- **`docker compose up -d --build bot`** 只重建 Bot，不影响 NapCat/数据库，是最轻量的更新方式。

---

## 六、数据卷规范（重要）

docker-compose.yml 使用**固定名称的外部卷**（`external: true`），确保无论项目目录怎么变，数据永远在同一个卷里。

### 卷名约定

| 卷名 | 用途 |
|------|------|
| `qqbot_pg_data` | PostgreSQL 数据（用户金币、积分、对局记录等） |
| `qqbot_redis_data` | Redis 缓存 |
| `qqbot_napcat_data` | NapCat 登录态和配置 |

### 首次部署（全新服务器）

必须先手动创建卷：

```bash
docker volume create qqbot_pg_data
docker volume create qqbot_redis_data
docker volume create qqbot_napcat_data
```

之后再 `docker compose up -d`。

### 换目录重新部署

只要卷存在，数据就不会丢。直接在新目录 `docker compose up -d` 即可挂载同一份数据。

### 禁止操作

- ❌ 不要 `docker volume rm qqbot_pg_data`（除非你确认要清空所有数据）
- ❌ 不要在 docker-compose.yml 里去掉 `external: true`（会导致 compose 自建带前缀的新卷）
