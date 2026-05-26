# 本地端到端测试指南（Windows）

- **Status**: Draft v1.1
- **Last Updated**: 2026-04-30
- **Owner**: @owner
- **适用场景**: 本地 Windows 开发机测试完整 QQ 机器人流程，无需云服务器

> 如果你需要生产部署（云服务器长期运行），请看 [`05-deployment.md`](./05-deployment.md)。
> 本项目的 **CLI↔Bot 一致性铁律** 见 [`13-cli-bot-parity.md`](./13-cli-bot-parity.md)。

---

## 0. 测试方式的两种选择

| 方式 | 覆盖面 | 启动成本 | 什么时候用 |
|---|---|---|---|
| **CLI 测试**（§0.5） | 游戏主流程（状态机、判定、奖励发放） | 一条命令，秒起 | **日常开发首选**：改了游戏逻辑想快速验证 |
| **QQ 群完整闭环**（§1-§5） | 全链路（NapCat ↔ bot ↔ 玩家） | 要起 Docker + 扫码登录 + 反向 WebSocket | 验证消息路由、多玩家交互、真实群聊体验 |

由于 CLI 和 Bot 遵循 **1:1 对齐铁律**（[`13-cli-bot-parity.md`](./13-cli-bot-parity.md)），**CLI 跑通 ≈ 群里就能跑通**。除非你在改 bot 层（消息路由/NapCat 对接），否则 CLI 就够用了。

---

## 0.5 CLI 测试（最轻量，日常开发首选）

`scripts/play_cli.py` 是**所有游戏的统一 CLI 入口**。它会读取 `ADAPTERS` 字典里注册的所有游戏（当前：海龟汤、趣味问答），和 QQ 群里的玩家交互逻辑保持 1:1 对齐。

### 0.5.1 最常用启动方式（不带参数，完整菜单）

```powershell
cd i:\QQBotForFun
uv run python scripts/play_cli.py
```

进入后会先让你选游戏，再选模式：

```
🎮 可用游戏
   1. 海龟汤        [turtle_soup]
   2. 趣味问答      [trivia]
   Q. 退出
选择游戏（编号 / ID / Q）>
```

### 0.5.2 跳过菜单的快捷启动

| 用法 | 效果 |
|---|---|
| `uv run python scripts/play_cli.py` | **完整菜单**（推荐日常使用） |
| `uv run python scripts/play_cli.py turtle_soup` | 跳过游戏选择，直接进海龟汤选模式 |
| `uv run python scripts/play_cli.py turtle_soup 1` | 两层都跳，海龟汤 · 模式 1（题库随机）直接开局 |
| `uv run python scripts/play_cli.py trivia` | 跳过游戏选择，直接进趣味问答选类目 |

> ⚠️ 如果你是 AI Agent / 新协作者：**请默认用不带参数的方式启动**。带了 `turtle_soup` 会绕过游戏选择，容易让用户以为 CLI 只能玩海龟汤（实际是统一入口）。

### 0.5.3 Debug 模式

需要看 LLM 请求/响应原文时：

```powershell
$env:GAME_CLI_DEBUG=1; uv run python scripts/play_cli.py
```

（或设 `SOUP_DEBUG=1`，二者等价。）

### 0.5.4 CLI 特殊行为（和 Bot 的差异点）

CLI 遵守 1:1 对齐铁律，但有 2 个**非玩家可见**的差异：

1. **经济系统不真发 DB**：CLI 的 `qq_id=0` 是虚拟账户。玩家能看到 `+2 score / +100 coin` 提示（行为一致），但不调 `economy.add`，避免污染生产数据。详见 [`09-conventions.md §0.5`](./09-conventions.md)。
2. **局末烂题询问**：海龟汤 CLI 每局结束会追问 `这题要标记为烂题吗？(y/N)`，等同于 Bot 的 `/汤 烂题` 指令。

### 0.5.5 新增游戏如何接入 CLI

在 `scripts/cli_adapters/` 下新建 adapter（实现 `GameCLIAdapter` 协议，声明 `MODES`），再到 `scripts/play_cli.py` 顶部的 `ADAPTERS` 字典里注册一行即可。详见 [`04-game-development.md`](./04-game-development.md)。

### 0.5.6 AI Agent 帮你启动 CLI（开发辅助）

**人类用户直接用 §0.5.1 的 `uv run python scripts/play_cli.py` 就行，这一小节不用看。**

如果是 AI Agent 需要"在用户桌面上弹一个能交互的 CLI 窗口"（agent 自己的 shell 没 TTY，直接跑 CLI 会 EOF 秒退），正确姿势：

```powershell
# ⚠️ 下面命令里的 uv.exe 路径是 @jimygong 机器上的实测值，换机器 / 换用户必须替换！
# 新 agent 第一次在一台新机器上用时，请先在 **用户自己的 PowerShell**（不是 agent 的 shell）里跑：
#     where.exe uv
# 把输出的完整路径（例如 C:\Users\<你>\AppData\Local\Python\pythoncore-3.1x-64\Scripts\uv.exe）
# 替换下面的 <UV_EXE_ABSOLUTE_PATH> 占位符。
Start-Process -FilePath cmd -ArgumentList '/k','cd /d i:\QQBotForFun && <UV_EXE_ABSOLUTE_PATH> run python scripts/play_cli.py'

# 已知可工作的实测示例（@jimygong 机器，2026-04-30）——直接 Ctrl+C/V 用，不过机器不同就会失效：
Start-Process -FilePath cmd -ArgumentList '/k','cd /d i:\QQBotForFun && C:\Users\jimygong\AppData\Local\Python\pythoncore-3.14-64\Scripts\uv.exe run python scripts/play_cli.py'
```

**关键坑点**（2026-04-30 实测）：
1. `Start-Process` 弹出的新 cmd 窗口标题是 `管理员: C:\Windows\System32`，**以管理员身份运行**（因为继承了 agent 进程的身份）
2. 管理员窗口**只继承系统 PATH，不继承用户 PATH**
3. `uv.exe` 装在用户目录（`C:\Users\<用户名>\AppData\Local\Python\...\Scripts\uv.exe`），管理员窗口里直接跑 `uv` 会报 **"不是内部或外部命令"**
4. **必须用 `uv.exe` 的完整绝对路径**，不要依赖 PATH —— 这就是上面命令里要用占位符而不是直接写 `uv` 的原因

**别的踩过的坑**：
- bash 里用 `start "标题" ...` 会被引号转义搞坏，报"系统找不到文件"
- agent 自己的 PowerShell 里直接跑 `uv` 会被安全钩静默拦截（返回空）；所有 uv 命令在 agent 端应走 bash
- 弹出的窗口**归用户所有**，agent 看不到里面的输出、发不了输入——这叫"启动"不叫"驱动"。想让 agent 自动走完一局对局，得给 CLI 加 `--script <file>` 模式

---




## 0.9 QQ 群闭环测试准备

> 下面的第 1 节开始讲"跑通完整 QQ 群机器人流程"的方式，需要 Docker / 小号 / NapCat。
> **如果你只是想验证游戏逻辑，直接用上面的 §0.5（CLI 测试）就够了。**

你需要准备：

| 项 | 说明 | 必要性 |
|---|---|---|
| 专用 QQ 小号 | **不能用主号**，有封号风险 | 必需 |
| 测试群 | 用主号拉小号进去 | 必需 |
| Docker Desktop | 跑 NapCat 容器 | 必需 |
| 代码环境 | `uv sync` 已跑过 | 必需 |
| `.env` 已配好 | ADMIN_QQ、ZHIPU_API_KEY、LONGCAT_API_KEY（查资料兜底） | 必需 |
| 题库已导入 | `python scripts/seed_turtle_soup.py` | 必需 |

---

## 1. 启动 NapCat

### 1.1 启动容器

在项目根目录：

```powershell
cd i:\QQBotForFun
docker compose -f docker-compose.dev.yml up -d
```

等 10-20 秒让 NapCat 启动。确认容器状态：

```powershell
docker compose -f docker-compose.dev.yml ps
```

看到 `napcat` 状态是 `running` 即可。

### 1.2 获取 WebUI 登录 Token

NapCat 首次启动时会在日志里打印 WebUI Token：

```powershell
docker compose -f docker-compose.dev.yml logs napcat
```

找类似这样的行：
```
[WebUi] WebUI is ready, token: XXXXXXXXXXXX
[WebUi] 请在浏览器打开 http://localhost:6099/webui?token=XXXX...
```

**复制这个 token**，或者直接复制完整 URL。

---

## 2. WebUI 登录小号

### 2.1 打开 WebUI

浏览器访问：**http://localhost:6099**

用上一步拿到的 token 登录。

### 2.2 QQ 扫码登录

1. 点"QQ 登录"或"快速登录"
2. 点"二维码登录"获取二维码
3. 用你的**专用小号手机 QQ** 扫码
4. 小号手机上确认登录
5. WebUI 显示登录成功，在线状态为绿色

> ⚠️ **安全提示**：
> - 绝对不要用主号
> - 新登录小号 1-2 小时内不要狂发消息，先养号
> - 被风控后换小号或等 24 小时

---

## 3. 配置反向 WebSocket 连接

NapCat 登录后，需要告诉它"连到我们的 bot"。

### 3.1 在 WebUI 中

左侧菜单 → **网络配置** → 找到 **Websocket 客户端**（不是服务器） → **新建**。

字段填写：

| 字段 | 值 |
|---|---|
| 启用 | ✅ 开 |
| 名称 | `qqbot`（随便） |
| URL | `ws://host.docker.internal:8080/onebot/v11/ws` |
| 消息格式 | `array` |
| Token | `change_me`（必须和 `.env` 里 `ONEBOT_ACCESS_TOKEN` 一致） |
| 心跳间隔 | `30000` |
| 重连间隔 | `3000` |
| 上报自身消息 | ❌ 关 |

**点保存**。

此时 bot 还没启动，NapCat 连接会失败 / 一直重试，**这是正常的**，下一步启动 bot 后会自动连上。

---

## 4. 启动 Bot

**重要**：**开一个新的 PowerShell 窗口**（不要关 NapCat 的那个日志窗口）。

```powershell
cd i:\QQBotForFun
uv run --no-sync python -m src.bot
```

### 4.1 期望日志

```
[bot] startup: init llm config...
[llm] init ok. providers=['zhipu', 'longcat'] scenes=[...]
[bot] startup: init database...
[bot] startup: recover active sessions...
[bot] ready.
INFO:     Uvicorn running on http://0.0.0.0:8080
INFO:     OneBot V11 | Bot XXXXXXXX connected
```

最后一行 `Bot XXXXXXXX connected` 表示 NapCat 已连上，XXXXXXXX 是你的小号 QQ 号。

### 4.2 如果 bot 启动报错

见末尾"常见问题"。

---

## 5. 在群里测试

### 5.1 拉小号进测试群

用你**主号** 604384365 的手机 QQ：
- 打开一个测试群（建议新建一个"bot 测试"群，不要用活跃的大群）
- 邀请小号进群
- 可以也邀请主号自己在群里方便测

### 5.2 基础验证

在测试群发：

```
/ping
```
→ 机器人应回复 `pong 🏓`

```
/menu
```
→ 显示游戏大厅，里面有 🐢 海龟汤

```
/help
```
→ 显示帮助

```
/balance
```
→ 查看金币（初始 0）

### 5.3 开一局海龟汤

```
/play turtle_soup
```

机器人会：
1. 显示"正在出题…"（或直接出题）
2. 推送汤面卡片（局号、标题、故事）
3. 提示"提问以 ? 结尾，宣告汤底以「汤底:」开头"

然后你可以：

```
他活着吗？
```
→ 机器人判定并回复"✅ 是 / ❌ 不是 / 🤔 与此无关 / 💡 关键线索"

```
汤底: 我猜是…… (写你推理的完整故事)
```
→ 机器人判定 correct / partial / wrong

### 5.4 其他游戏内指令

- `/soup status` — 查看当前进度（提问几次了）
- `/soup recap` — 回顾已发掘的关键线索
- `/soup giveup` — 投降，公布汤底
- `/quit` — 终止本局

### 5.5 管理员指令（用主号 604384365 发）

```
/admin check 小号QQ
/admin coin 小号QQ 500      # 给小号加 500 金币
```

---

## 6. 停止与清理

### 6.1 停 bot
在 bot 运行的 PowerShell 窗口按 `Ctrl+C`。

### 6.2 停 NapCat
```powershell
docker compose -f docker-compose.dev.yml down
```

### 6.3 数据保留
- `data/bot.db`：所有游戏数据都在这里，重启后仍在
- `napcat/data/`：登录态，下次启动免扫码

### 6.4 完全重置
```powershell
docker compose -f docker-compose.dev.yml down -v    # 清空 volumes
Remove-Item data\bot.db                             # 清空游戏数据
python scripts/seed_turtle_soup.py                  # 重新导入题库
```

---

## 7. 常见问题

### Q1：NapCat WebUI 打不开 / 502 / 空白页

```powershell
docker compose -f docker-compose.dev.yml logs napcat --tail 100
```
看有没有 crash。重启容器：
```powershell
docker compose -f docker-compose.dev.yml restart napcat
```

### Q2：bot 启动报 `address already in use` (8080)

端口被占用：
```powershell
netstat -ano | findstr :8080
```
看 PID，然后 `taskkill /PID <pid> /F`。

或者改 `.env` 的 `PORT=8081`，同时改 NapCat WebUI 里的 URL 为 `ws://host.docker.internal:8081/onebot/v11/ws`。

### Q3：bot 启动成功但 NapCat 连不上

**大概率是 `host.docker.internal` 在你 Windows 上解析不到**。

诊断：
```powershell
docker compose -f docker-compose.dev.yml exec napcat ping -c 2 host.docker.internal
```

不通的话，查你电脑局域网 IP：
```powershell
ipconfig
```
找"IPv4 地址"（例如 `192.168.1.100`）。

改 NapCat WebUI 的 URL 为：`ws://192.168.1.100:8080/onebot/v11/ws`

另外 Windows **防火墙**可能拦 Docker → 宿主机 8080 的连接。首次启动时如果弹了授权框记得点"允许"。或者临时关闭防火墙确认是不是这个问题。

### Q4：发 `/ping` 没反应

按优先级排查：

1. **NapCat 有没有连上 bot**？看 bot 日志有没有 `Bot XXXXXXXX connected`
2. **机器人是否在该群**？群成员列表里有没有小号
3. **是不是群被风控**？小号在群里手动说句话看能不能发出
4. **token 是否一致**？`.env` 的 `ONEBOT_ACCESS_TOKEN` 和 NapCat WebUI 里填的完全一样（大小写敏感）
5. **bot 日志有没有收到消息**？正常会看到 `[OneBot V11] [group_xxx] xxx: /ping`

### Q5：`/play turtle_soup` 报错 "出题失败"

看 bot 日志：
- `[llm] ... failed` → API key 问题或网络问题
- `题库为空` → 没跑 seed 脚本

### Q6：机器人发消息乱码 / 格式错乱

看 bot 日志里实际发送的字符串——大概率是你客户端的字体渲染问题，换 QQ 新版客户端试试。

### Q7：反复开同一局海龟汤被拒

本群已有活跃对局。先 `/quit` 终止，或等超时（默认 60 分钟）。

### Q8：小号被封 / 风控

- 换一个小号重新扫码
- 数据库里的游戏数据**不绑账号只绑群和 qq_id**，换机器人小号不影响玩家数据
- 但 `napcat/data/` 里的登录态需要清掉：`docker volume rm qqbotforfun_napcat_data` 或 `Remove-Item napcat\data\* -Recurse -Force`

---

## 8. 跑完后你可以做什么

1. **多跑几局海龟汤**，看 LLM 判定质量
2. **改 prompt** 调优：`src/plugins/games/turtle_soup/prompts.py`
3. **扩充题库**：
   ```powershell
   python scripts/generate_soup_with_llm.py 10    # LLM 生成 10 道
   ```
4. **加新游戏**：参考 [`04-game-development.md`](./04-game-development.md)
5. **部署到云**：参考 [`05-deployment.md`](./05-deployment.md)

---

## 9. 变更日志

| 版本 | 日期 | 变更 |
|---|---|---|
| v1 | 2026-04-28 | 初版 |
| v1.1 | 2026-04-30 | 新增 §0.5 CLI 测试章节（统一入口 `play_cli.py` 用法、快捷启动、CLI 与 Bot 的差异点） |
| v1.2 | 2026-04-30 | §0.5.6 增加 AI Agent 启动 CLI 的姿势（Start-Process + uv 完整路径，解决管理员窗口缺用户 PATH 的问题） |
| v1.3 | 2026-04-30 | §0.5.6 的 uv.exe 绝对路径改成占位符 `<UV_EXE_ABSOLUTE_PATH>` 并加使用说明（原硬编了 `jimygong` 用户名，换机器会失效），实测示例保留作参考 |
