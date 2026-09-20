# 新开发机接入手册

> 场景：在一台**全新的开发机**上从 git 拉取本仓库后，如何让本机 agent 能使用运维流程更新服务器。
> 配套脚本：`scripts/setup_dev_machine.ps1`（幂等，可重复执行）。

---

## TL;DR（三步）

```powershell
# 1. 本机自动化（生成密钥 + 装 MCP server + 写连接配置）
git clone https://github.com/JimyTD/QQBotForFun.git
cd QQBotForFun
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1

# 2. 把脚本打印出来的公钥装到服务器  ← 唯一需要人工/另一台机器的一步
#    见下面「步骤 2」

# 3. 注册 MCP（脚本加 -RegisterMcp 自动做），然后重启 CodeBuddy 或开新会话
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -RegisterMcp -Verify
```

---

## 前提

- CodeBuddy（CN 版）
- **Node.js >= 18**（脚本会检查；ssh-mcp-server 需要它）
- git

## 步骤 1：本机自动化

脚本做四件事，全部幂等（已存在就跳过）：

1. 检查 Node >= 18
2. 生成**本机专用** SSH 密钥（ed25519，无口令）→ `~/.ssh/qqbot_deploy`
3. 安装 `ssh-mcp-server` → `~/.codebuddy/mcp/ssh-mcp-server/`
4. 生成/合并连接配置 → `~/.codebuddy/ssh-mcp-config.json`

**加上 `-RegisterMcp`** 还会把 MCP 注册写进 CodeBuddy 全局设置（原文件先备份）。

**产物位置与 git 边界：**

| 产物 | 路径 | 进 git？ |
|---|---|---|
| SSH 私钥 | `~/.ssh/qqbot_deploy` | ❌ 永不 |
| SSH 公钥 | `~/.ssh/qqbot_deploy.pub` | ❌ 永不 |
| MCP server（第三方包） | `~/.codebuddy/mcp/ssh-mcp-server/` | ❌ |
| 连接配置 + 命令黑名单 | `~/.codebuddy/ssh-mcp-config.json` | ❌ |
| MCP 注册 | `%APPDATA%\CodeBuddy CN\...\codebuddy_mcp_settings.json` | ❌ |
| **命令黑名单的来源** | `scripts/setup_dev_machine.ps1` | ✅ 在仓库里 |

> 黑名单刻意放在**仓库里的脚本**中，每次跑脚本渲染到本机配置 —— 这样多台机器不会各写一份而漂移。

## 步骤 2：把公钥装到服务器（唯一需要人工的一步）

**为什么必须人工：** 这是个引导问题 —— 装公钥本身需要一条非 SSH 通道，而这条通道不能依赖 SSH（否则死循环）。所以每台新机器的接入都要"借"一次外部通道。

脚本会把公钥和现成命令打印出来。三条路任选：

| 路线 | 做法 | 代价 |
|---|---|---|
| **[A] 推荐** | 在另一台**已接入**的开发机上，让 agent 用 `qqbot-ssh` 的 `execute-command` 跑那条 `install ... >> authorized_keys` 命令 | 需要两台机器同时在场 |
| **[B] 兜底** | 腾讯云控制台 → 轻量应用服务器 → 登录（OrcaTerm），粘同一条命令 | 人工点几下 |
| **[C] 临时** | 临时挂载 TAT MCP（需要腾讯云 AK/SK），跑完摘掉 | 会把账号级凭据放到磁盘上 |

> ⚠️ 路线 C 是**临时**手段。长期安全前提是**云凭据不常驻**（见文末「安全前提」）。

## 步骤 3：注册 MCP 并让 agent 看到

用 `-RegisterMcp` 自动注册，或手动粘进 CodeBuddy 的 **Settings → MCP**：

```json
{
  "qqbot-ssh": {
    "type": "stdio",
    "command": "<node 绝对路径>",
    "args": [
      "<home>/.codebuddy/mcp/ssh-mcp-server/node_modules/@fangjunjie/ssh-mcp-server/build/index.js",
      "--config-file",
      "<home>/.codebuddy/ssh-mcp-config.json"
    ]
  }
}
```

> ⚠️ **必须重启 CodeBuddy 或开新会话。** 当前会话的 MCP 工具清单是**会话启动时的快照**，热重载不会把新 MCP 加进来（表现为 `Server 'qqbot-ssh' not found or not connected`，但配置文件其实是好的）。
>
> 应急办法：不要等重启，直接用仓库里的 CLI 桥调用（**不需要 IDE 注册**）：
> ```
> node scripts/mcp_call.mjs qqbot-ssh execute-command <参数文件或inline JSON>
> node scripts/mcp_call.mjs --list-servers      # 看当前注册了哪些 server
> ```
> 它从 CodeBuddy 的 MCP 设置里读配置（含 `env` 里的凭据），所以不重复存密钥。

## 步骤 4：验证

```powershell
# 加 -Verify 让脚本自己试连；或手动：
ssh -i ~/.ssh/qqbot_deploy root@106.55.228.236 "hostname; ls -d /root/qqbot"
```

期望看到主机名和 `/root/qqbot`。接上之后就可以按 `docs/ops-guide.md` §1 部署了。

## macOS / Linux 变体

只有第 2 步（生成密钥）不同 —— 那边没有 Windows 的两个坑：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/qqbot_deploy -C "$(hostname)-codebuddy" -N ''
```

其余（npm 安装、连接配置、MCP 注册）结构相同，路径用 `~` 代替 `$env:USERPROFILE`。注意 `command` 要用该平台的 node 绝对路径。

脚本本身是 PowerShell，macOS/Linux 上需要照着本文档手工做一遍，或者后续补一个 `.sh` 版本。

---

## 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `Invalid JSON in config file: Unexpected token ''` | 配置文件带了 BOM，Node 拒绝解析 | 用 `-RegisterMcp` 重跑脚本（脚本用 .NET 写无 BOM UTF-8） |
| `Server 'qqbot-ssh' not found or not connected` | 当前会话是旧快照 | 重启 CodeBuddy 或开新会话；应急用 `scripts/mcp_call.mjs` |
| `Permission denied (publickey)` | 公钥还没装到服务器 | 回到步骤 2 |
| `Command matches blacklist, execution forbidden` | 命中了项目铁律 | 换命令；确实需要就改脚本里的黑名单并重新渲染 |
| `WARNING: Running without a command whitelist` | **刻意如此** —— 白名单会禁止 `&` `|` `>` `$()`，而我们的命令要用 `&&` 和管道 | 忽略这条警告 |
| 部署卡住/超时 | `docker compose build` 慢 | 连接的 `commandTimeoutMs` 已是 600000（10 分钟）；更久就按次传更大的 `timeout` |

## 坑日志（Pitfall log，都是实测踩出来的）

1. **ssh-keygen 从 `CONIN$` 读口令，不走 stdin。** 用管道喂空口令会**永久卡住**（无输出直到超时）。必须用 `-N ""`，并加 `< nul` 兜底。
2. **PowerShell 5.1 会丢掉空字符串参数**，`-N ''` 会变成裸的 `-N` 让 ssh-keygen 报错。解法：把命令写进一个 `.cmd` 文件用 cmd 的参数解析执行。
3. **`Set-Content -Encoding UTF8` 在 PS 5.1 会写 BOM**，Node 的 `JSON.parse` 直接拒绝，表现为 MCP server 启动即失败。必须用 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`。
4. **脚本必须保持纯 ASCII。** PS 5.1 对**无 BOM** 的文件按系统 ANSI（中文 Windows 是 GBK）解码，多字节中文字符会错位，把字符串结束引号吃掉 → 报出莫名其妙的 `|| is not a valid statement separator` / `string is missing the terminator`。所以 `setup_dev_machine.ps1` 里不放中文，中文说明放本文档。
5. **包名 `@fangjunjie/ssh-mcp-server` 必须加引号**，否则 PowerShell 把开头的 `@` 当成 splatting 语法。

---

## 设计说明

### 为什么 D 方案不会重演"多项目抢锚点"

| | 旧：CodeBuddy 内置 Lighthouse 集成 | 新：SSH MCP |
|---|---|---|
| 绑定存在哪 | **云端账号级单锚点**（一个腾讯云账号锚定一个实例） | 本地配置文件里的一个**具名条目** |
| 多工作区 | 必然互抢（实测 QQBot 与 SilentWereWolf 互相覆盖绑定） | 互不干扰，一份配置 = N 个具名连接 |
| 授权时效 | OAuth，会失效 → 反复要求登录 | 私钥，永不过期 |

### 扩展到「任意服务器 + 任意开发机」

- **加服务器** = 往 `~/.codebuddy/ssh-mcp-config.json` 加一条连接（同名 host 也可以，连接名不同即可）。**不用改 IDE 设置。**
- **加开发机** = 在新机器上重跑本文档的三步。
- **一台开发机一把 key**：不要一把 key 走天下 —— 某台机器出问题只需吊销那一把。
- 黑名单/超时/SFTP 范围都是 **per-connection** 的。要为新服务器复用项目铁律，把 `scripts/setup_dev_machine.ps1` 里的 `$blacklist` 抄过去，或给脚本加参数支持多连接。

### 安全前提

1. **SSH 通道优先，云凭据不常驻。** SSH MCP 建好之后，TAT MCP 退化为"引导 + 腾讯云 API 兜底"的**低频**通道 —— 需要时临时挂上，用完摘掉。
2. **TAT 的 `RunCommand` 等价于该实例的 root。** 所以任何能读到 AK/SK 的进程/会话都等价于拥有服务器 root。凭据**不进 git 只是第一步**，还要做到"不常驻磁盘"。
3. **服务器侧**：`PasswordAuthentication no` + `PermitRootLogin prohibit-password`（root 仍可用 key 登录）。22 端口保持对公网开放即可 —— 关掉密码认证后爆破无效，按 IP 收窄反而会牺牲"任意开发机"的灵活性。
4. **`~/.ssh` 私钥**建议加口令（`--passphrase`），代价是每台机器要配置一次；当前为了 agent 可用性选择无口令，靠文件权限 + SFTP 范围收窄来兜。
