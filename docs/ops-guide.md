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

---

## 固定参数

```
Region:      ap-guangzhou
InstanceId:  lhins-hwnz7rcz
IP:          106.55.228.236
项目路径:     /root/qqbot（符号链接，指向实际目录）
Bot QQ:      3959381140
NapCat WebUI: http://106.55.228.236:6099
```

所有命令直接用 `cd /root/qqbot && ...`，不需要查地域或实例列表。

---

## 操作决策树

```
需要做什么？
├─ 更新 Python 代码/数据 → §1 日常部署
├─ 机器人没反应 → §2 排查
├─ NapCat 掉线/需要扫码 → §3 重新登录
├─ 改了 docker-compose.yml → §4 全流程部署（需扫码）
└─ 查战斗日志 → §5 日志
```

---

## §1 日常部署（最常用）

适用：只改了 src/ seeds/ scripts/ docs/ pyproject.toml，未改 docker-compose.yml。

**步骤：**

1. 用 `deploy_project_preparation` 上传项目（会生成临时目录 `/root/QQBotForFun_<ts>`）
2. 停 bot、复制文件、重建：

```bash
cd /root/qqbot && docker compose stop bot && docker compose rm -f bot
cp -r /root/QQBotForFun_<ts>/{src,seeds,scripts,docs,resources,pyproject.toml} /root/qqbot/
cd /root/qqbot && docker compose up -d --build bot
```

3. 确认启动：

```bash
cd /root/qqbot && docker compose logs bot --tail=5
```

应看到 `[bot] ready.` 和 `Uvicorn running`。

**禁止事项：**
- ❌ 不要在新目录里执行 `docker compose up`（会启新容器栈）
- ❌ 不要 `docker compose down`（会杀 NapCat，需要重新扫码）
- ❌ 不要重命名或删除 `/root/qqbot` 链接指向的实际目录

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

## §4 全流程部署（极少用）

**仅当修改了 docker-compose.yml 时才需要。会重启 NapCat，需要重新扫码。**

```bash
# 1. 上传代码（deploy_project_preparation），得到新目录 /root/QQBotForFun_<ts>

# 2. 停掉所有容器
cd /root/qqbot && docker compose down

# 3. 更新符号链接
ln -sfn /root/QQBotForFun_<ts> /root/qqbot

# 4. Dockerfile 镜像加速（如果新目录的 Dockerfile 还没 patch）
cd /root/qqbot && python3 << 'PYEOF'
with open('Dockerfile','r') as f: c=f.read()
c=c.replace("RUN apt-get update","RUN sed -i 's@deb.debian.org@mirrors.cloud.tencent.com@g' /etc/apt/sources.list.d/debian.sources && apt-get update")
c=c.replace('RUN pip install uv','RUN pip install -i https://mirrors.cloud.tencent.com/pypi/simple uv')
c=c.replace('RUN uv pip install --system .','RUN uv pip install --system --index-url https://mirrors.cloud.tencent.com/pypi/simple .')
c=c.replace('COPY pyproject.toml ./','COPY pyproject.toml README.md ./')
with open('Dockerfile','w') as f: f.write(c)
print('Dockerfile patched')
PYEOF

# 5. 启动
cd /root/qqbot && docker compose up -d

# 6. 写入 NapCat WebSocket 配置（全流程部署后配置会被重置）
cd /root/qqbot && docker compose exec napcat sh -c 'cat > /app/napcat/config/onebot11_3959381140.json << EOF
{"network":{"httpServers":[],"httpSseServers":[],"httpClients":[],"websocketServers":[],"websocketClients":[{"enable":true,"name":"qqbot","url":"ws://bot:8080/onebot/v11/ws","messagePostFormat":"array","reconnectInterval":3000,"token":"qqbot_fun_token_2026","heartInterval":30000}],"plugins":[]},"musicSignUrl":"","enableLocalFile2Url":false,"parseMultMsg":false,"imageDownloadProxy":"","timeout":{"baseTimeout":10000,"uploadSpeedKBps":256,"downloadSpeedKBps":256,"maxTimeout":1800000}}
EOF'
# 必须 stop+rm+up（不是 restart），否则端口映射可能丢失
docker compose stop napcat && docker compose rm -f napcat && docker compose up -d napcat

# 7. 去 WebUI 扫码（同 §3 步骤 2~4）
```

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

- NapCat 每次重启都需要重新扫码
- `docker compose up -d --build bot` 只重建 Bot，不影响 NapCat
- docker-compose.yml 中 `name: qqbot` 固定了项目名，与目录名无关
- 数据卷使用 external volume（`qqbot_pg_data` 等），数据不会因目录变化丢失
- Bot 容器里的文件 NapCat 读不到，图片用 base64 发送
