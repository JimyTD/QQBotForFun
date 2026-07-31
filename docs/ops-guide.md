# 运维手册（Agent 操作指南）

## ⚠️ 铁律：不要触发重新扫码

以下操作会导致用户必须手动扫码，**除非明确需要，禁止执行**：

- ❌ `docker compose down`（删除所有容器包括 NapCat）
- ❌ `docker compose stop napcat && rm napcat`（删除 NapCat 容器）
- ❌ 任何导致 NapCat 容器被删除重建的操作

**安全操作（不需要扫码）：**
- ✅ `docker compose stop bot && rm -f bot && up -d --build bot`（日常部署）
- ✅ `docker compose restart napcat`（重启但不删容器，登录态保留）
- ✅ `docker compose restart bot`
- ✅ `docker compose up -d --build`（只要没改 napcat 的 service 定义，只会重建 bot）

---

## ⚠️ 铁律：目录命名与角色绑定

- `/root/qqbot` 是**真实目录**（不是符号链接），生产环境唯一真身，**永久存在，永不删除、永不重命名、永不做 `ln -sfn` 之类的指向切换**。
- `deploy_project_preparation` 上传后生成的 `/root/QQBotForFun_<timestamp>` **只允许作为一次性中转**，寿命不超过一条部署命令链。
- 上传后第一步永远是把它改名成固定名字：`mv /root/QQBotForFun_<ts> /root/.deploy_staging`，之后所有操作都从这个固定名字读取，用完无条件删除。
- **正常情况下 `/root/` 不应该存在任何 `QQBotForFun_*` 目录**（只在一条命令执行的瞬间存在）。排查磁盘时如果看到这种目录，说明某次部署被中断过，**必须先询问用户，禁止当作垃圾直接删除**——这正是历史上一次生产目录被误删的直接原因（旧版流程用 `ln -sfn` 切换符号链接指向，从未清理被替换掉的旧目标目录，导致"真身"和"废弃临时目录"共用同一套命名，无法区分）。

---

## 固定参数

```
Region:      ap-guangzhou
InstanceId:  lhins-hwnz7rcz
IP:          106.55.228.236
项目路径:     /root/qqbot（真实目录，生产唯一真身，不是符号链接）
Bot QQ:      3959381140
NapCat WebUI: http://106.55.228.236:6099
```

所有命令直接用 `cd /root/qqbot && ...`，不需要查地域或实例列表。

---

## 权威副本规定

| 内容 | 唯一权威来源 |
|---|---|
| 代码/文档/资源/配置模板/依赖清单/迁移脚本 | 本地 git 仓库，服务器版本永远由本地 `cp` 覆盖 |
| `.env`（真实密钥） | 服务器 `/root/qqbot/.env` + 备份 `/root/.env_qqbot_backup`，本地无副本 |
| NapCat 登录态 / QQ 账号数据 | named volume `qqbot_napcat_data`，与目录无关 |
| Postgres / Redis 数据 | named volume `qqbot_pg_data` / `qqbot_redis_data`，与目录无关 |
| `logs/` | 服务器本地，无备份，可接受丢失 |

---

## 操作决策树

```
需要做什么？
├─ 更新 Python 代码/数据 → §1 日常部署
├─ 机器人没反应 → §2 排查
├─ NapCat 掉线/需要扫码 → §3 重新登录
├─ 改了 docker-compose.yml / Dockerfile → §4 根级文件部署
└─ 查战斗日志 → §5 日志
```

---

## §1 日常部署（最常用）

适用：只改了 src/ seeds/ scripts/ docs/ pyproject.toml，未改 docker-compose.yml。

**步骤：**

1. 用 `deploy_project_preparation` 上传项目（会生成临时目录 `/root/QQBotForFun_<ts>`）
2. **立刻**把临时目录改名成固定名字，消除时间戳歧义：

```bash
rm -rf /root/.deploy_staging
mv /root/QQBotForFun_<ts> /root/.deploy_staging
```

3. 停 bot、复制文件、重建：

```bash
cd /root/qqbot && docker compose stop bot && docker compose rm -f bot
cp -r /root/.deploy_staging/{src,seeds,scripts,docs,resources,pyproject.toml} /root/qqbot/
cd /root/qqbot && docker compose up -d --build bot
```

4. 确认启动：

```bash
cd /root/qqbot && docker compose logs bot --tail=5
```

应看到 `[bot] ready.` 和 `Uvicorn running`。

5. 无条件清理（成功失败都执行，不是"确认成功后才做"）：

```bash
rm -rf /root/.deploy_staging && docker image prune -f
```

> 中转目录和旧镜像层会持续积累磁盘空间，必须每次都清理，且必须清理干净（不留任何 `QQBotForFun_*` 残留）。

**禁止事项：**
- ❌ 不要在中转目录里执行 `docker compose up`（会启新容器栈）
- ❌ 不要 `docker compose down`（会杀 NapCat，需要重新扫码）
- ❌ 不要对 `/root/qqbot` 做任何重命名、删除、`ln -sfn` 操作——它是真实目录，没有"指向"这个概念
- ❌ 不要 `docker system prune -a` 或 `--volumes`（清掉所有镜像缓存，重建耗时数十分钟）

**磁盘空间维护：**
- 每次部署后无条件执行步骤 5，磁盘上不该残留任何 `.deploy_staging` 以外的中转目录
- 如果在 `/root/` 发现 `QQBotForFun_*` 命名的目录 → 先报告用户询问来源，**禁止直接删除**（正常流程不会留下这种目录，出现即异常）
- 其他清理操作必须先报告用户由用户决定，禁止自行执行

---

## §2 排查：机器人没反应

**按顺序检查：**

```bash
# 1. 容器状态（4个都应 Up，postgres=healthy）
cd /root/qqbot && docker compose ps

# 2. Bot 日志（看有没有报错）
cd /root/qqbot && docker compose logs bot --tail=30

# 3. WebSocket 是否连接（应有 "Bot 3959381140 connected"）
cd /root/qqbot && docker compose logs bot 2>&1 | grep 'connected' | tail -1

# 4. NapCat 是否掉线
cd /root/qqbot && docker compose logs napcat 2>&1 | grep -i 'kicked\|offline\|二维码' | tail -3
```

**判定：**
- 容器不在 → `docker compose up -d`
- Bot 报错 → 看错误修代码
- 无 connected 日志 / NapCat 有 kicked → 需要重新扫码（§3）

---

## §3 NapCat 重新登录

⚠️ NapCat 每次新建容器（rm+up）后，WebSocket 配置会被重置为空。必须在扫码前确认配置正确。

```bash
# 1. 检查 WebSocket 配置是否存在
cd /root/qqbot && docker compose exec napcat cat /app/napcat/config/onebot11_3959381140.json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print('ws_clients:',len(d['network']['websocketClients']))"
# 如果输出 ws_clients: 0 → 需要写入配置（步骤 2）
# 如果输出 ws_clients: 1 → 跳到步骤 3

# 2. 写入 WebSocket 配置（仅当 ws_clients: 0 时）
cd /root/qqbot && docker compose exec napcat sh -c 'echo "{\"network\":{\"httpServers\":[],\"httpSseServers\":[],\"httpClients\":[],\"websocketServers\":[],\"websocketClients\":[{\"enable\":true,\"name\":\"qqbot\",\"url\":\"ws://bot:8080/onebot/v11/ws\",\"messagePostFormat\":\"array\",\"reconnectInterval\":3000,\"token\":\"qqbot_fun_token_2026\",\"heartInterval\":30000}],\"plugins\":[]},\"musicSignUrl\":\"\",\"enableLocalFile2Url\":false,\"parseMultMsg\":false,\"imageDownloadProxy\":\"\",\"timeout\":{\"baseTimeout\":10000,\"uploadSpeedKBps\":256,\"downloadSpeedKBps\":256,\"maxTimeout\":1800000}}" > /app/napcat/config/onebot11_3959381140.json'
# 写入后 restart（不要 rm，否则配置又丢）
cd /root/qqbot && docker compose restart napcat

# 3. 获取 WebUI Token
cd /root/qqbot && docker compose logs napcat 2>&1 | grep 'WebUi Token' | tail -1

# 4. 浏览器打开 http://106.55.228.236:6099，输入 Token，用户扫码

# 5. 确认连接（扫码后等几秒）
cd /root/qqbot && docker compose logs bot --tail=5
# 应看到 "Bot 3959381140 connected"
```

**关键规则：**
- 扫码前必须确认 ws_clients 不为空，否则扫码成功了也收不到消息
- 写配置后用 `restart`（不是 rm+up），restart 保留容器实例不会覆盖配置
- 如果 bot 日志无 connected 但 NapCat 已登录 → 先检查配置再 restart napcat

---

## §4 根级文件部署（改了 docker-compose.yml / Dockerfile 等）

**`/root/qqbot` 是真实目录，这一步不再需要 `down`、不再需要切换符号链接、正常情况下也不需要重新扫码**——本质就是把变了的根级文件 cp 进去，让 compose 按需重建。

```bash
# 1. 上传代码，立刻转固定名
rm -rf /root/.deploy_staging && mv /root/QQBotForFun_<ts> /root/.deploy_staging

# 2. 把变了的根级文件 cp 进真身目录（按实际改动挑选，不是全量覆盖）
cp /root/.deploy_staging/docker-compose.yml /root/qqbot/docker-compose.yml
# 如果 Dockerfile / pyproject.toml / uv.lock / alembic.ini 等也变了，一并 cp

# 3. 让 compose 按服务定义差异自动重建（一般只会重建 bot）
cd /root/qqbot && docker compose up -d --build

# 4. 清理
rm -rf /root/.deploy_staging && docker image prune -f
```

**判断是否会影响 NapCat：**
- 只改了 `bot` service 的定义（环境变量、构建方式等）→ 只重建 `bot`，NapCat 不受影响，**不需要扫码**
- 确实修改了 `napcat` service 本身的定义（镜像版本、端口映射等）→ `docker compose up -d --build napcat` 会重建该容器，**需要走 §3 重新登录**
- 不确定改动范围时，先 `docker compose config` 或 `docker compose up -d --build --dry-run`（如支持）确认哪些服务会被重建，再执行

---

## §5 查战斗日志

```bash
# 最近 5 局列表
cd /root/qqbot && ls -t logs/aoe3_battle/*.json | grep -v full | head -5

# 查看最新一局精简日志
cd /root/qqbot && cat logs/aoe3_battle/$(ls -t logs/aoe3_battle/*.json | grep -v full | head -1)
```

精简日志包含：阵容、结果、击杀链、单位统计、MVP。

---

## §6 关键规则

- NapCat 只有「删容器重建」才需要重新扫码，`restart` 不需要
- `docker compose up -d --build` 只重建服务定义发生变化的容器
- docker-compose.yml 中 `name: qqbot` 固定了项目名，与目录名无关
- 数据卷使用 external volume（`qqbot_pg_data` 等），数据不会因目录内容变化丢失
- Bot 容器里的文件 NapCat 读不到，图片用 base64 发送
- **任何 `rm -rf` 目标如果不是 `/root/.deploy_staging`，且位于 `/root/` 下、名字像项目目录 → 先确认来源、向用户报告，禁止直接删除**
