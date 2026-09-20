# 运维手册（Agent 操作指南）

> **同步方式**：Git（自 2026-08-28 起）。已废弃 `deploy_project_preparation` 上传 + `cp` 清单的旧流程。

## ⚠️ 铁律一：不要触发重新扫码

以下操作会导致用户必须手动扫码，**除非明确需要，禁止执行**：

- ❌ `docker compose down`（删除所有容器包括 NapCat）
- ❌ `docker compose stop napcat && rm napcat`（删除 NapCat 容器）
- ❌ 任何导致 NapCat 容器被删除重建的操作

**安全操作（不需要扫码）：**
- ✅ `docker compose stop bot && rm -f bot && up -d --build bot`（日常部署）
- ✅ `docker compose restart napcat`（重启但不删容器，登录态保留）
- ✅ `docker compose restart bot`
- ✅ `docker compose up -d --build`（只要没改 napcat 的 service 定义，只会重建 bot）
- ✅ **所有 git 操作**（git 只改目录里的文件，碰不到 NapCat 容器和它的 volume）

---

## ⚠️ 铁律二：Git 操作红线

`/root/qqbot` 现在是 git 工作区，以下命令**绝对禁止**：

| 禁令 | 原因 |
|---|---|
| ❌ `git clean -fdx` / `git clean -fx` | `-x` 会删除 ignored 文件 → **会删掉 `.env`（本地无副本）和 `logs/`** |
| ❌ `git pull` | 可能触发 merge/交互。统一用 `git fetch` + `git reset --hard` |
| ❌ 在服务器编辑任何 tracked 文件 | 包括 `config/llm.yaml`、`docker-compose.yml`、`Dockerfile`。会被下次 reset 覆盖，并造成静默漂移。要改就改本地 + push |
| ❌ 把 `.env` 提交进 git | 历史上已发生过一次事故（commit `66e2df6`），密钥在 public 仓库泄露，不得重演 |
| ❌ 仓库转 private 后继续用镜像 + PAT | 凭证会明文经过第三方镜像站。转 private 必须改用 SSH deploy key 或自建代理 |

**安全的 git 操作**（只动 tracked 文件，untracked/ignored 一律不碰）：
- ✅ `git fetch mirror main`
- ✅ `git reset --hard mirror/main`
- ✅ `git status` / `git log` / `git rev-parse HEAD`
- ✅ `git checkout -- <file>`

---

## ⚠️ 铁律三：目录与数据

- `/root/qqbot` 是**真实目录 + git 工作区**，生产环境唯一真身，**永久存在，永不删除、永不重命名、永不做 `ln -sfn` 之类的指向切换**。
- 部署**不再需要任何中转目录**。git 直接在真身目录里 fetch/reset，不存在 `.deploy_staging` 或 `QQBotForFun_<ts>` 这类临时目录。
- 如果在 `/root/` 发现 `QQBotForFun_*` 或 `.deploy_staging` 目录 → 是旧流程遗留或异常，**先报告用户询问，禁止直接删除**。
- **任何 `rm -rf` 目标位于 `/root/` 下、看起来像项目目录 → 先 `ls -la` 确认、向用户报告，禁止自行删除**。`/root/` 下存在其他项目（如 SilentWereWolf），其中有正在运行的生产目录。

---

## 固定参数

```
Region:       ap-guangzhou
InstanceId:   lhins-hwnz7rcz
IP:           106.55.228.236
项目路径:      /root/qqbot（真实目录 + git 工作区）
Bot QQ:       3959381140
NapCat WebUI: http://106.55.228.236:6099
GitHub:       https://github.com/JimyTD/QQBotForFun
```

**Git remote 配置：**

| remote | URL | 用途 |
|---|---|---|
| `origin` | `https://github.com/JimyTD/QQBotForFun.git` | 记录真实地址。**直连不通**，不能用来 fetch |
| `mirror` | `https://ghfast.top/https://github.com/JimyTD/QQBotForFun.git` | **实际拉取用这个** |

> ⚠️ 服务器直连 GitHub 完全不通（TCP 443 被拒 + timeout），必须走镜像。
> 备用镜像：`https://gh-proxy.com/https://github.com/JimyTD/QQBotForFun.git`

---

## 执行通道（自 2026-09-20 起）

### ⛔ 已禁用：CodeBuddy 内置的 Lighthouse 集成

**永久不使用它的任何工具** —— `execute_command`、`deploy_project_preparation`、`describe_*_firewall_rules`、`analyze_lighthouse_instances` 等，一个都不用。两个**互相独立**的原因，任一都足以判死：

1. **OAuth 授权会失效** —— 失效后所有调用返回 `Token verification failed. Please check your Token is correct.`，必须人工重新登录授权（2026-09-20 实测连续 3 次调用 3 次失败）。
2. **锚点跨工作区共享** —— 它的绑定是**云端账号级单锚点**，工作区里的 `.codebuddy/integration/lighthouse.json` 只是"当时锚在哪"的镜像，**不是 per-workspace 绑定**。在 QQBot 工作区操作会把 SilentWereWolf 工作区的绑定一起改掉（历史上确实发生过：SilentWereWolf 原本指向 `lhins-5xyrg0ei`／`62.234.18.113`，被改成了本机的 `lhins-hwnz7rcz`）。

替代品齐全，**没有任何场景需要它**：命令执行 → `qqbot-ssh`；新机器引导 → 腾讯云控制台 OrcaTerm；腾讯云 API → `tencent-lighthouse`。

> 唯一已知能力缺口：**Lighthouse 防火墙规则的读写**没有对应 MCP 工具。走腾讯云控制台，或用 `d:/Fun/tencent-lighthouse-mcp/src/tencent-api.js` 的 `tcRequest` 直接调 `lighthouse:DescribeFirewallRules` / `ModifyFirewallRules`。

改用两个 MCP 通道：

| 通道 | 定位 | 调用方式 |
|---|---|---|
| `qqbot-ssh` | **主力**：日常运维与部署 | 工具 `execute-command`：`connectionName="qqbot"`、`directory="/root/qqbot"`、`timeout`（毫秒，缺省走配置 600000） |
| `tencent-lighthouse` | 后备：TAT agent 诊断、腾讯云 API 层操作（实例/监控）；OrcaTerm 不可用时的备用引导通道 | 工具 `run_command`：`region="ap-guangzhou"`、`instanceIds=["lhins-hwnz7rcz"]` |

- `directory` 参数即工作目录，不必用 `cd X && ...` 拼接。
- `qqbot-ssh` 启用命令黑名单，命中即拒绝：`git clean -f*`、`git pull`、`docker compose down`、`docker compose (rm|stop|kill) … napcat`、`docker volume rm`、`docker system prune -a`、`rm -rf /…`、`mkfs`、`dd of=/dev/*`、`reboot` 等。**`git reset --hard` 刻意未列入**——部署流程需要它。
- 产物位置（**全部在仓库外且 agent 中立，永不入 git**）：连接配置 `~/.ssh-mcp/config.json`；MCP server `~/.ssh-mcp/server/`；私钥 `~/.ssh/qqbot_deploy`；MCP 注册在 `~/.codebuddy/mcp.json`。
- ⚠️ **CodeBuddy 的 MCP 注册只认 `~/.codebuddy/mcp.json`** —— **不是** `%APPDATA%\CodeBuddy CN\...\globalStorage\tencent.planning-genie\settings\codebuddy_mcp_settings.json`。后者本版本不读，写进去**静默无效**（2026-09-20 实测踩过）。
- **引导通道**：安装/修复 SSH 公钥必须走非 SSH 通道（不能靠 SSH 装 SSH）。**首选腾讯云控制台的 OrcaTerm 网页终端** —— 它完全绕开 sshd（实测：`last` 里有 orcaterm 会话，但同期 auth.log 里 0 条 sshd `Accepted`），不需要 22 端口、不需要你的 IP 白名单、不需要 AK/SK。需要脚本化时才用 `tencent-lighthouse` 的 `run_command`。
- exec 模式下每次调用是**独立会话**，不要依赖 `cd` 跨调用保持；用 `directory` 参数或绝对路径。
- **新开发机接入**（新机器 / 新 agent 怎么拿到这条通道）→ 见 **`docs/dev-machine-setup.md`**，一键脚本 `scripts/setup_dev_machine.ps1`。

---

## 服务器安全基线（2026-09-20 起）

**SSH 仅允许密钥登录**，配置在 `/etc/ssh/sshd_config.d/10-hardening.conf`：

```
PasswordAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
```

- `10-` 前缀是必要的，不是随手起的：`Include /etc/ssh/sshd_config.d/*.conf` 在主文件**第 12 行**（早于主文件自己的指令），而 OpenSSH 对同一关键字取**首个**值 —— 所以 drop-in 先于主文件、`10-` 又先于 `50-cloud-init.conf`，**同时扛住 cloud-init 重写**。
- 改 sshd 的通则：先 `sshd -t` 校验，再 `systemctl reload ssh`（**不要用 restart** —— reload 失败时旧配置继续生效，restart 会把你锁在门外）。
- 回滚（自己进不去时）：`rm /etc/ssh/sshd_config.d/10-hardening.conf && systemctl reload ssh`。
- OrcaTerm 是最终兜底：**完全绕开 sshd**，SSH 配坏了也能靠它进去救。
- 实测证据（2026-09-20）：改前 `Permission denied (publickey,password)`，改后 `Permission denied (publickey)` —— 密码选项已从报错里消失。

**按已约定口径（"防君子与外行"，非高密级）刻意不做的事** —— 后来者不必再提：

- CAM 策略资源级收窄（该子账号的 TAT 权限覆盖账号下所有 Lighthouse 实例）
- AK/SK 不常驻（`BioTrace/.cursor/mcp.json` 与 CodeBuddy 全局设置各一份副本）
- NapCat WebUI（6099）收窄到固定 IP（用户 IP 不固定，代价大于收益）

---

## 权威副本规定

| 内容 | 唯一权威来源 |
|---|---|
| 代码/文档/资源/配置模板/依赖清单/迁移脚本/根级文件 | **git 仓库**（`main` 分支）。服务器由 `git reset --hard` 对齐，服务器上不做手工编辑 |
| `.env`（真实密钥） | **服务器 `/root/qqbot/.env`** + 备份 `/root/.env_qqbot_backup`。**永不入 git**，由运维助手手工填写 |
| NapCat 登录态 / QQ 账号数据 | named volume `qqbot_napcat_data`，与目录无关 |
| Postgres / Redis 数据 | named volume `qqbot_pg_data` / `qqbot_redis_data`，与目录无关 |
| `logs/` | 服务器本地，无备份，可接受丢失 |

---

## 操作决策树

```
需要做什么？
├─ 更新代码（任何文件）      → §1 日常部署
├─ 机器人没反应             → §2 排查
├─ NapCat 掉线/需要扫码      → §3 重新登录
├─ 查服务器版本 / 回滚       → §4 版本管理
├─ 修改 .env（密钥轮换等）   → §5 密钥维护
└─ 查战斗日志               → §6 日志
```

> 注意：**不再区分「日常部署」和「根级文件部署」**。git 全仓库对齐，`docker-compose.yml`、`Dockerfile`、`uv.lock`、`migrations/` 等根级文件都会自动同步，用同一套 §1 流程即可。

---

## §1 日常部署（唯一部署流程）

### 前置检查（必做）

```bash
# 本地：确认已 push，否则服务器拉到的是旧代码
git status --short          # 应为空
git rev-parse HEAD          # 记下这个 hash
git ls-remote origin HEAD   # 应与上面一致
```

### 部署

> 经 `qqbot-ssh` 通道执行：`connectionName="qqbot"`、`directory="/root/qqbot"`、`timeout=900000`（首次构建装新依赖可能超 10 分钟）。

```bash
git fetch mirror main
git log --oneline HEAD..mirror/main        # 可选：看这次要上哪些 commit
docker compose stop bot && docker compose rm -f bot
git reset --hard mirror/main
docker compose up -d --build bot
```

### 验证

> 同上通道执行。

```bash
git rev-parse --short HEAD                # 应与本地一致
git status --short                        # 应为空（无漂移）
docker compose logs bot --tail=15         # 应看到 [bot] ready. + Bot 3959381140 connected
docker compose ps                         # 4 个容器 Up，postgres healthy
```

### 清理

```bash
docker image prune -f     # 清理悬挂（dangling）镜像层
```

⚠️ **跑这条之前先看一眼有没有"没名字的基础镜像"**：

```bash
docker images -f dangling=true
```

`python:3.11-slim` 一旦被上游更新替代，旧的那块就会失去 tag、变成 dangling，
正好被 `prune -f` 当垃圾删掉。删掉的后果不是"少占点磁盘"，而是
**下一次部署又要从头重建一遍**（base 重新下载 → digest 变化 → apt / uv 依赖全层失效，
十几分钟，见 2026-09-20 那次部署）。所以：

- 列出来是空的 → 随便跑 `prune -f`，什么也不会删；
- 列表里出现 `python:3.11-slim`（或其它基础镜像）→ **先别删**，直接跳过清理。
  磁盘不紧张（40G 盘日常剩 10G 以上）时，不清理完全没问题。

> 根因修在 `Dockerfile`：base 已固定 digest。这里仍是保险丝——
> 万一哪天有人把 digest 改回浮动 tag，这条注解能提醒他别顺手删掉缓存。

**不需要**清理任何中转目录——git 流程不产生中转目录。

**禁止事项：**
- ❌ `docker compose down`（杀 NapCat，需重新扫码）
- ❌ `git clean -fdx`（删 `.env`）
- ❌ `git pull`（用 fetch + reset）
- ❌ `docker system prune -a` 或 `--volumes`（清掉所有镜像缓存，重建耗时数十分钟）
- ❌ 对 `/root/qqbot` 做重命名、删除、`ln -sfn`

### 带新依赖的部署

`pyproject.toml` / `uv.lock` 新增包时，`--build` 会自动重建镜像安装新依赖，无需额外操作。较大的包（如 `akshare`）首次构建约 2-3 分钟。

`config/llm.yaml` 是 git tracked 文件，`reset --hard` 会自动同步，**不再需要单独 cp**。

新增 DB 表由 `init_db()` 的 `create_all` 幂等创建；如有新 alembic migration，bot 容器启动时自动 `alembic upgrade head`。

### 镜像站故障时的 fallback

```bash
cd /root/qqbot
git remote set-url mirror https://gh-proxy.com/https://github.com/JimyTD/QQBotForFun.git
git fetch mirror main
# 用完可改回 ghfast.top，也可以留着
```

---

## §2 排查：机器人没反应

**按顺序检查：**

```bash
# 1. 容器状态（4个都应 Up，postgres=healthy）
cd /root/qqbot && docker compose ps

# 2. Bot 日志（看有没有报错）
cd /root/qqbot && docker compose logs bot --tail=30

# 3. Bot↔NapCat WebSocket 是否连接（应有 "Bot 3959381140 connected"）
cd /root/qqbot && docker compose logs bot 2>&1 | grep 'connected' | tail -1

# 4. NapCat 的 QQ 账号是否在线（关键！WebSocket 通 ≠ QQ 在线）
cd /root/qqbot && docker compose logs napcat 2>&1 | grep -iE 'KickedOffLine|账号状态变更|offline|二维码' | tail -5

# 5. 服务器代码版本（确认部署是否生效）
cd /root/qqbot && git rev-parse --short HEAD && git status --short
```

**判定：**

| 现象 | 结论 |
|---|---|
| 容器不在 | `docker compose up -d` |
| Bot 报错 | 看错误修代码，走 §1 重新部署 |
| 无 connected 日志 | Bot↔NapCat 链路问题，检查 §3 的 ws 配置 |
| 有 connected，但有 `KickedOffLine` / `账号状态变更为离线` | **QQ 账号本身离线**，需重新扫码（§3）。这与部署无关 |
| `git status` 有输出 | 有人在服务器上手改了文件，属违规漂移，`git reset --hard mirror/main` 恢复 |

> ⚠️ 重要经验：`Bot xxx connected` 只代表 **Bot ↔ NapCat** 的 WebSocket 通了，**不代表 QQ 账号在线**。QQ 被踢下线时，WebSocket 照样是 connected，但收不到任何消息。必须单独查 NapCat 的账号状态。

---

## §3 NapCat 重新登录

⚠️ NapCat 每次新建容器（rm+up）后，WebSocket 配置会被重置为空。必须在扫码前确认配置正确。

```bash
# 1. 检查 WebSocket 配置是否存在
cd /root/qqbot && docker compose exec -T napcat cat /app/napcat/config/onebot11_3959381140.json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print('ws_clients:',len(d['network']['websocketClients']))"
# 输出 ws_clients: 0 → 需要写入配置（步骤 2）
# 输出 ws_clients: 1 → 跳到步骤 3

# 2. 写入 WebSocket 配置（仅当 ws_clients: 0 时）
cd /root/qqbot && docker compose exec napcat sh -c 'echo "{\"network\":{\"httpServers\":[],\"httpSseServers\":[],\"httpClients\":[],\"websocketServers\":[],\"websocketClients\":[{\"enable\":true,\"name\":\"qqbot\",\"url\":\"ws://bot:8080/onebot/v11/ws\",\"messagePostFormat\":\"array\",\"reconnectInterval\":3000,\"token\":\"qqbot_fun_token_2026\",\"heartInterval\":30000}],\"plugins\":[]},\"musicSignUrl\":\"\",\"enableLocalFile2Url\":false,\"parseMultMsg\":false,\"imageDownloadProxy\":\"\",\"timeout\":{\"baseTimeout\":10000,\"uploadSpeedKBps\":256,\"downloadSpeedKBps\":256,\"maxTimeout\":1800000}}" > /app/napcat/config/onebot11_3959381140.json'
cd /root/qqbot && docker compose restart napcat

# 3. 获取 WebUI Token
cd /root/qqbot && docker compose exec -T napcat cat /app/napcat/config/webui.json 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print('TOKEN:',d.get('token'))"
# 或从日志取：docker compose logs napcat 2>&1 | grep 'WebUi Token' | tail -1

# 4. 浏览器打开 http://106.55.228.236:6099，输入 Token，用户扫码

# 5. 确认连接（扫码后等几秒）
cd /root/qqbot && docker compose logs bot --tail=5
# 应看到 "Bot 3959381140 connected"
```

**关键规则：**
- 扫码前必须确认 ws_clients 不为空，否则扫码成功了也收不到消息
- 写配置后用 `restart`（不是 rm+up），restart 保留容器实例不会覆盖配置
- **报 "当前账号已登录,无法重复登录" 但实际是离线状态** → NapCat 内部状态残留（被踢下线时未正确复位）。用 `docker compose restart napcat` 清掉残留，重启后会生成新二维码
- 缓存的 `/app/napcat/cache/qrcode.png` 可能是很久以前的，已过期。必须 restart 后取新码
- QQ 账号本身可能需要"更新网络身份验证"等账号层面操作，这类问题在 QQ 侧解决，与服务器无关

---

## §4 版本管理

### 查服务器当前版本

```bash
cd /root/qqbot
git rev-parse --short HEAD                       # 当前 commit
git log -1 --format='%h %s (%ci)'                # 详细信息
git status --short                               # 空 = 无手改漂移
git log --oneline -10                            # 最近 10 个 commit
```

### 回滚到旧版本

```bash
cd /root/qqbot
git log --oneline -10                            # 挑目标 commit
docker compose stop bot && docker compose rm -f bot
git reset --hard <commit>
docker compose up -d --build bot
docker compose logs bot --tail=15
```

> 回滚只改代码。如果目标版本的 DB schema 不兼容，需要额外处理 migration（一般不会遇到）。

### 检查是否落后于远端

```bash
cd /root/qqbot
git fetch mirror main
git log --oneline HEAD..mirror/main              # 有输出 = 服务器落后，需部署
```

---

## §5 密钥维护（`.env`）

`.env` **永不入 git**，由运维助手手工写入。修改后必须同步备份。

```bash
# 1. 查看当前配置项（不打印完整值，只看指纹）
cd /root/qqbot && grep -E '^[A-Za-z_]+=' .env | while IFS='=' read -r k v; do
  if [ -n "$v" ]; then echo "$k  len=${#v}  starts=$(echo -n "$v" | cut -c1-4)"; else echo "$k  (empty)"; fi
done

# 2. 修改（用 sed 精确替换单个变量，避免全文件重写出错）
cd /root/qqbot && sed -i 's|^ZHIPU_API_KEY=.*|ZHIPU_API_KEY=<新key>|' .env

# 3. 同步备份（唯一权威来源，必做）
cp /root/qqbot/.env /root/.env_qqbot_backup

# 4. 生效（改 .env 只需 restart，不需要 rebuild）
cd /root/qqbot && docker compose restart bot
cd /root/qqbot && docker compose logs bot --tail=10   # 确认 [bot] ready.
```

**灾难恢复**（`.env` 丢失）：

```bash
cp /root/.env_qqbot_backup /root/qqbot/.env
cd /root/qqbot && docker compose restart bot
```

**注意**：`config/llm.yaml` 里的 `${ZHIPU_API_KEY}` 是占位符，真值从 `.env` 注入。轮换密钥只改 `.env`，不需要动 `llm.yaml`。

---

## §6 查战斗日志

```bash
# 最近 5 局列表
cd /root/qqbot && ls -t logs/aoe3_battle/*.json | grep -v full | head -5

# 查看最新一局精简日志
cd /root/qqbot && cat logs/aoe3_battle/$(ls -t logs/aoe3_battle/*.json | grep -v full | head -1)
```

精简日志包含：阵容、结果、击杀链、单位统计、MVP。

`logs/` 在 `.gitignore` 里，git 操作不会删除它（但 `git clean -fdx` 会，已禁止）。

---

## §7 数据备份

### DB 快照（重大变更前建议做）

```bash
cd /root/qqbot
docker compose exec -T postgres pg_dump -U qqbot qqbot > /root/pg_backup_$(date +%F).sql
ls -lh /root/pg_backup_*.sql
```

DB 很小（约 10MB，dump 约 730KB），成本极低。

### 恢复

```bash
cd /root/qqbot
cat /root/pg_backup_<date>.sql | docker compose exec -T postgres psql -U qqbot -d qqbot
```

### 数据现状参考基线（2026-08-28）

```
economy_tx                  1412
game_session                 500
game_turtle_soup_question    347
game_turtle_soup_session      44
economy_balance               12
group_config                   5
alembic_version         0002_food
DB 大小                   9687 kB
```

排查数据异常时可与此对比。

---

## §8 关键规则速查

- NapCat 只有「删容器重建」才需要重新扫码，`restart` 不需要；**git 操作永远不需要**
- `docker compose up -d --build` 只重建服务定义发生变化的容器
- `docker-compose.yml` 中 `name: qqbot` 固定了项目名，与目录名无关
- 数据卷使用 external volume（`qqbot_pg_data` / `qqbot_redis_data` / `qqbot_napcat_data`），数据不会因目录内容变化或 git 操作丢失
- Bot 容器里的文件 NapCat 读不到，图片用 base64 发送
- `Bot xxx connected` ≠ QQ 账号在线，排查时必须分开确认
- 服务器直连 GitHub 不通，git 必须走 `mirror` remote
- **任何 `rm -rf` 目标位于 `/root/` 下、名字像项目目录 → 先确认来源、向用户报告，禁止直接删除**（`/root/` 下有其他项目，含正在运行的生产目录）

---

## §9 变更日志

| 日期 | 变更 |
|---|---|
| 2026-09-20 | **接入方案改为 agent 中立**。共享产物从 `~/.codebuddy/` 迁到 `~/.ssh-mcp/`（连接配置 `config.json`、server `server/`），私钥仍是通用的 `~/.ssh/qqbot_deploy`。`setup_dev_machine.ps1` 新增 `-Target`（codebuddy / cursor / windsurf / claudecode / vscode / zed / opencode / codex / all / none）与 `-ListTargets`；`mcp_call.mjs` 支持 `--settings` / `MCP_SETTINGS` 并在多客户端配置文件间自动探测。**重要修正：CodeBuddy 真正生效的 MCP 配置文件是 `~/.codebuddy/mcp.json`；其文档所指的 globalStorage 路径本版本不读 —— 写进去静默无效，此前误判为「会话快照」。** |
| 2026-09-20 | **CodeBuddy 内置 Lighthouse 集成正式禁用**（从"已废弃"升级为"禁止使用"）。全仓排查确认 `src/`、`scripts/`、`README.md` 零引用；文档侧只涉及 `ops-guide.md` 与 `dev-machine-setup.md`，规则侧只涉及 `server-ops.mdc`。同步删除本工作区的集成锚点文件 `.codebuddy/integration/lighthouse.json`（untracked 本地文件）以实现工作区级禁用。记录唯一能力缺口：Lighthouse 防火墙规则读写无 MCP 工具，走控制台或 `tcRequest` 直调 API。 |
| 2026-09-20 | **SSH 硬化：仅允许密钥登录**。新增 `/etc/ssh/sshd_config.d/10-hardening.conf`（`PasswordAuthentication no` + `PermitRootLogin prohibit-password`），`10-` 前缀用于压过 `50-cloud-init.conf` 并扛住 cloud-init 重写。实测：改前报错是 `Permission denied (publickey,password)`，改后只剩 `(publickey)`。新增「服务器安全基线」章节，并把 OrcaTerm 确认为**完全绕开 sshd** 的最终兜底通道。 |
| 2026-09-20 | **执行通道改为两个 MCP**：主力 `qqbot-ssh`（SSH 私钥认证，`~/.ssh/qqbot_deploy`），后备/引导 `tencent-lighthouse`（自建 TAT MCP）。废弃 CodeBuddy 内置 Lighthouse 集成（`execute_command`）——其 OAuth 授权会失效、锚点跨工作区共享，实测 100% 不可用。新增 `qqbot-ssh` 命令黑名单（落实本项目铁律：`git clean -f*`、`git pull`、`docker compose down`、`docker compose (rm|stop|kill) … napcat` 等）。新增「执行通道」章节，部署/验证命令改由该通道执行。另新增 `docs/dev-machine-setup.md`（新开发机接入手册）+ `scripts/setup_dev_machine.ps1`（一键接入，幂等）+ `scripts/mcp_call.mjs`（CLI 桥，绕开会话快照限制）。 |
| 2026-08-28 | **同步方式改为 Git**。`/root/qqbot` 转为 git 工作区（`git init` + `origin`/`mirror` 双 remote + `fetch`/`reset --hard`）。废弃 `deploy_project_preparation` 上传 + `cp` 清单 + `.deploy_staging` 中转目录的旧流程。合并「日常部署」与「根级文件部署」为单一流程。新增 §4 版本管理、§5 密钥维护、§7 数据备份。 |
| 2026-09-20 | `Dockerfile` 的 base 改为**固定 digest**：此前用浮动 tag `python:3.11-slim`，上游一发新版就让 apt / uv 依赖所有层缓存失效，一次「只改了 3 行 Python」的部署耗时约 10 分钟（其中 `pip install uv` 单独跑了 7 分钟）。§1 补充告警：`docker image prune -f` 会删掉失去 tag 的基础镜像，从而把下一次部署再次推入全量重建，清理前先 `docker images -f dangling=true` 确认。 |
