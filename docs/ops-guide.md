# 运维手册

> 通过 CodeBuddy 的 Lighthouse 集成管理 QQ 机器人

## 服务器信息

| 项目 | 值 |
|------|------|
| 实例 ID | lhins-hwnz7rcz |
| 地域 | ap-guangzhou |
| 服务器 IP | 106.55.228.236 |
| 项目路径 | `/root/QQBotForFun_20260502112049` |
| Bot QQ 号 | 3959381140 |
| NapCat WebUI | http://106.55.228.236:6099 |
| OneBot Token | `qqbot_fun_token_2026` |

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

### 5. 写入 NapCat WebSocket 配置

```
cd /root/NEW_DIR && docker compose exec napcat sh -c 'cat > /app/napcat/config/onebot11_3959381140.json << EOF
{"network":{"httpServers":[],"httpSseServers":[],"httpClients":[],"websocketServers":[],"websocketClients":[{"enable":true,"name":"qqbot","url":"ws://bot:8080/onebot/v11/ws","messagePostFormat":"array","reconnectInterval":3000,"token":"qqbot_fun_token_2026","heartInterval":30000}],"plugins":[]},"musicSignUrl":"","enableLocalFile2Url":false,"parseMultMsg":false,"imageDownloadProxy":"","timeout":{"baseTimeout":10000,"uploadSpeedKBps":256,"downloadSpeedKBps":256,"maxTimeout":1800000}}
EOF'
docker compose restart napcat
```

### 6. 去 WebUI 扫码登录

---

## 四、仅更新 Bot 代码（不重建整个环境）

如果只改了 `src/` 下的 Python 文件，可以直接在服务器上改文件后重建 Bot 容器：

```
cd /root/QQBotForFun_20260502112049 && docker compose up -d --build bot
```

NapCat 不会受影响，不需要重新扫码。

---

## 五、关键注意事项

- **NapCat 和 Bot 是两个独立容器**，文件系统隔离。Bot 容器里的文件 NapCat 读不到（图片要用 base64 发送）。
- **NapCat 每次重启都需要重新扫码**，且重启后 WebSocket 配置可能被重置为空，需要重新写入。
- **新 QQ 号前几天容易被风控踢下线**，养号几天后会稳定。
- **`docker compose up -d --build bot`** 只重建 Bot，不影响 NapCat/数据库，是最轻量的更新方式。
