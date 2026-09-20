# 新开发机接入手册（agent 中立）

> 场景：在一台**全新的开发机**上从 git 拉取本仓库后，如何让本机 agent 能使用运维流程更新服务器。
> 配套脚本：`scripts/setup_dev_machine.ps1`（幂等，可重复执行）。
>
> **这套通道不绑定任何 IDE。** MCP server 是标准 stdio server，私钥是普通 OpenSSH key ——
> 任何 MCP 客户端都能接，任何能跑 shell 的 agent 也能直接 `ssh -i` 用。换 agent 只需改它自己那一行配置。

---

## TL;DR

```powershell
# 1. 本机自动化：生成密钥 + 装 MCP server + 写连接配置 + 注册到你用的 agent
git clone https://github.com/JimyTD/QQBotForFun.git
cd QQBotForFun
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Target codebuddy

#    换 agent 就换 -Target；不确定有什么写就 -ListTargets；全量 -Target all
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -ListTargets

# 2. 把脚本打印出来的公钥装到服务器  ← 唯一需要人工的一步，见「步骤 2」

# 3. 验证 + 重启 agent / 开新会话
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Target codebuddy -Verify
```

## 前提

- 任一支持 MCP 的 agent（CodeBuddy / Cursor / Windsurf / Claude Code / VS Code / Zed / OpenCode / Codex …），或任何能跑 shell 的 agent
- **Node.js >= 18**（脚本会检查；`ssh-mcp-server` 需要它）
- git

## 步骤 1：本机自动化

脚本做四件事，全部幂等（已存在就跳过）：

1. 检查 Node >= 18
2. 生成**本机专用** SSH 密钥（ed25519，无口令）→ `~/.ssh/qqbot_deploy`
3. 安装 `ssh-mcp-server` → `~/.ssh-mcp/server/`
4. 生成/合并连接配置 → `~/.ssh-mcp/config.json`（含命令黑名单）

然后按 `-Target` 把 MCP 注册到对应 agent。

**产物位置与 git 边界（全部 agent 中立，不挂在任何 IDE 目录下）：**

| 产物 | 路径 | 进 git？ |
|---|---|---|
| SSH 私钥 / 公钥 | `~/.ssh/qqbot_deploy[.pub]` | ❌ 永不 |
| MCP server（第三方包） | `~/.ssh-mcp/server/` | ❌ |
| 连接配置 + 命令黑名单 | `~/.ssh-mcp/config.json` | ❌ |
| MCP 注册（CodeBuddy） | `~/.codebuddy/mcp.json` | ❌ |
| **命令黑名单的来源** | `scripts/setup_dev_machine.ps1` | ✅ 在仓库里 |

> 黑名单刻意放在**仓库里的脚本**中，每次跑脚本渲染到本机配置 —— 这样多台机器不会各写一份而漂移。

## 步骤 2：把公钥装到服务器（唯一需要人工的一步）

**为什么必须人工：** 这是个引导问题 —— 装公钥本身需要一条非 SSH 通道，而这条通道不能依赖 SSH（否则死循环）。所以每台新机器的接入都要"借"一次外部通道。

脚本会把公钥和现成命令打印出来。三条路任选：

| 路线 | 做法 | 代价 |
|---|---|---|
| **[A] 推荐** | 腾讯云控制台 → 轻量应用服务器 → 点实例「登录」（OrcaTerm 网页终端）→ 粘那条命令 | 浏览器点几下。**完全绕开 sshd**（实测：`last` 里有 orcaterm 会话但同期 auth.log 里 0 条 sshd `Accepted`），不需要 22 端口 / IP 白名单 / AK/SK |
| **[B]** | 在另一台**已接入**的开发机上，让 agent 用 `qqbot-ssh` 的 `execute-command` 跑同一条命令 | 需要两台机器同时在场 |
| **[C]** | 临时挂载 TAT MCP（需要腾讯云 AK/SK），跑完摘掉 | 会把账号级凭据放到磁盘上 |

> **想彻底免掉"装公钥"这一步**：新机器上不生成新密钥，直接把已接入机器的 `~/.ssh/qqbot_deploy` 拷过去 —— 脚本检测到密钥已存在会跳过生成，并自动派生出缺失的 `.pub`（**只需拷 1 个文件**）。代价是所有机器共用一把 key，丢一台等于全部泄露；对"一台服务器 + 任意开发机"这个场景通常划算。

> ⚠️ 路线 C 是**临时**手段；除非人在外面且控制台用不了，否则优先路线 A。

## 步骤 3：注册 MCP 并让 agent 看到

`-Target <agent>` 自动注册。支持的取值：

| `-Target` | 配置文件 | 根键 | 脚本行为 |
|---|---|---|---|
| `codebuddy` | **`~/.codebuddy/mcp.json`** ⚠️ 见下方警告 | `mcpServers` | ✅ 自动写入（合并，原文件先备份） |
| `cursor` | `~/.cursor/mcp.json`（全局）或 `<repo>/.cursor/mcp.json`（项目） | `mcpServers` | ✅ 自动写入 |
| `windsurf` | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | ✅ 自动写入 |
| `claudecode` | `~/.claude.json`（用户）或 `<repo>/.mcp.json`（项目） | `mcpServers` | 仅打印（用户配置是**共享状态文件**，手改风险高；建议用 `claude mcp add`） |
| `vscode` | `<repo>/.vscode/mcp.json` | **`servers`** ⚠️ 不是 `mcpServers` | 仅打印 |
| `zed` | `~/.config/zed/settings.json` | `context_servers` | 仅打印 |
| `opencode` | `~/.config/opencode/opencode.json` | `mcp` | 仅打印 |
| `codex` | `~/.codex/config.toml` | `[mcp_servers.<name>]`（**TOML**） | 仅打印 |
| `all` / `none` | — | — | 全量注册 / 只装共享产物 |

**只有 `codebuddy` 那一行是实测确认的**（2026-09-20）；其余来自公开文档汇总，首次使用请核对官方文档。

> ⚠️ **CodeBuddy 最坑的一点**：它的文档指向
> `%APPDATA%\CodeBuddy CN\...\globalStorage\tencent.planning-genie\settings\codebuddy_mcp_settings.json`，
> 但**这个版本根本不读那个文件** —— 写进去静默无效，表现为重启后工具依然
> `Server 'qqbot-ssh' not found or not connected`。**真正生效的是 `~/.codebuddy/mcp.json`。**
> 判断方法：会话里已经能用的 MCP server 就列在那个文件里。

要手动加的话，粘这一条（键名就是 `~/.codebuddy/mcp.json` 里已有的 server 名）：

```jsonc
{
  "qqbot-ssh": {
    "type": "stdio",
    "command": "<node 绝对路径>",
    "args": [
      "<home>/.ssh-mcp/server/node_modules/@fangjunjie/ssh-mcp-server/build/index.js",
      "--config-file",
      "<home>/.ssh-mcp/config.json"
    ]
  }
}
```

**重启 agent 或开新会话。** 多数 agent 的工具清单在会话启动时快照一次，运行中不热重载。

**应急：CLI 桥（不需要 agent 注册）**

```bash
node scripts/mcp_call.mjs qqbot-ssh execute-command <参数文件或inline JSON>
node scripts/mcp_call.mjs --list-servers        # 看它读了哪个配置文件、有哪些 server
node scripts/mcp_call.mjs --settings <path> ... # 指定配置文件
node scripts/mcp_call.mjs --list-servers | head -1   # 自动探测结果
```

它按 `--settings` → `$MCP_SETTINGS` → `$CODEBUDDY_MCP_SETTINGS`（旧名）→ 各客户端默认位置 依次查找配置文件，
所以换 agent 不用改代码，必要时用 `--settings` 显式指定即可。

## 步骤 4：验证

```powershell
# 加 -Verify 让脚本自己试连；或手动：
ssh -i ~/.ssh/qqbot_deploy root@106.55.228.236 "hostname; ls -d /root/qqbot"
```

期望看到主机名和 `/root/qqbot`。接上之后就可以按 `docs/ops-guide.md` §1 部署了。

**降级用法（任何 agent 都能用，连 MCP 都不需要）：**

```bash
ssh -i ~/.ssh/qqbot_deploy root@106.55.228.236 "cd /root/qqbot && docker compose ps"
```

只要 agent 能执行 shell 命令，这条就直接可用 —— 这是"最不会坏"的一层。

## 进一步：项目级配置（零配置接入）

`.cursor/mcp.json`、`.mcp.json`、`.vscode/mcp.json` 是**项目级**配置文件，可以提交进仓库。
我们的连接配置**不含任何密钥**（只有 host + 私钥**路径** + 黑名单），且支持 `~` 展开 —— 所以理论上可以做到"用 Cursor/Claude Code 打开仓库就自动有工具"。

唯一障碍是 `command` 需要 **node 绝对路径**（每台机器不同）。可行方向：用变量展开（VS Code 的 `${env:}` / `${userHome}`、Claude Code 的 `${VAR}`），或让使用者在本地覆盖。**尚未落地**，需要时再说。

## macOS / Linux 变体

只有生成密钥那一步不同 —— 那边没有 Windows 的坑：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/qqbot_deploy -C "$(hostname)-agent" -N ''
```

其余（npm 安装、连接配置、MCP 注册）结构相同，路径用 `~` 代替 `$env:USERPROFILE`，`command` 用该平台的 node 绝对路径。
脚本本身是 PowerShell；macOS/Linux 上目前需照本文档手工做一遍，或后续补一个 `.sh` 版本。

---

## 排查表

| 现象 | 原因 | 处理 |
|---|---|---|
| `Server '...' not found or not connected`（配置明明写了） | **注册写进了不生效的文件**（CodeBuddy 常见） | 确认写的是 `~/.codebuddy/mcp.json`，见步骤 3 的警告 |
| 注册后仍看不到工具 | 会话启动时快照了工具清单 | 重启 agent / 开新会话；急用就上 `scripts/mcp_call.mjs` |
| `Invalid JSON in config file: Unexpected token ''` | 配置文件带了 BOM，Node 拒绝解析 | 重跑脚本（它用 .NET 写无 BOM UTF-8） |
| `Permission denied (publickey)` | 公钥还没装到服务器 | 回到步骤 2 |
| `Command matches blacklist, execution forbidden` | 命中了项目铁律 | 换命令；确实需要就改脚本里的黑名单并重新渲染 |
| `WARNING: Running without a command whitelist` | **刻意如此** —— 白名单会禁止 `&` `|` `>` `$()`，而我们的命令要用 `&&` 和管道 | 忽略 |
| 部署卡住/超时 | `docker compose build` 慢 | 连接已设 `commandTimeoutMs` 600000（10 分钟）；更久按次传更大的 `timeout` |
| 脚本报 `意外的标记` / `缺少右 )` / `string is missing the terminator` | 脚本文件被存成了**带中文的无 BOM** 文件（PS 5.1 按 GBK 解码导致引号错位） | 用 `scripts/setup_dev_machine.ps1` 原版（纯 ASCII），别往里加中文 |

## 坑日志（Pitfall log，全部实测踩出来的）

1. **ssh-keygen 从 `CONIN$` 读口令，不走 stdin。** 用管道喂空口令会**永久卡住**（无输出直到超时）。必须用 `-N ""` 并加 `< nul` 兜底。
2. **PowerShell 5.1 会丢掉空字符串参数**，`-N ''` 会变成裸的 `-N` 让 ssh-keygen 报错。解法：把命令写进一个 `.cmd` 文件用 cmd 的参数解析执行。
3. **`Set-Content -Encoding UTF8` 在 PS 5.1 会写 BOM**，Node 的 `JSON.parse` 直接拒绝，表现为 MCP server 启动即失败。必须用 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`。
4. **脚本必须保持纯 ASCII。** PS 5.1 对**无 BOM** 文件按系统 ANSI（中文 Windows 是 GBK）解码，多字节中文字符会错位并吃掉字符串结束引号 → 报 `|| is not a valid statement separator` / `string is missing the terminator`。所以 `setup_dev_machine.ps1` 里不放中文，中文说明放本文档。
5. **PowerShell 的转义符是反引号（`` ` ``），不是反斜杠。** 在双引号字符串里写 `\"` 不会转义，那个 `"` 会**直接终止字符串** → 报 `意外的标记 "{"`。要插引号用单引号拼接或双写 `""`。
6. **CodeBuddy 的 MCP 配置有两个候选文件，只有一个生效。** 文档指向 globalStorage 下那份，实测**不读**；生效的是 `~/.codebuddy/mcp.json`。写错文件的表现是"完全静默"——没有任何报错，只是工具永远不出现。判断方法：看会话里已生效的 server 在哪个文件里。
7. **包名 `@fangjunjie/ssh-mcp-server` 必须加引号**，否则 PowerShell 把开头的 `@` 当成 splatting 语法。

---

## 设计说明

### 为什么这套方案不会重演"多项目抢锚点"

| | 旧：CodeBuddy 内置 Lighthouse 集成 | 新：SSH MCP |
|---|---|---|
| 绑定存在哪 | **云端账号级单锚点**（一个腾讯云账号锚定一个实例） | 本地配置文件里的一个**具名条目** |
| 多工作区 | 必然互抢（实测 QQBot 与 SilentWereWolf 互相覆盖绑定） | 互不干扰，一份配置 = N 个具名连接 |
| 多 agent | 只能 CodeBuddy 用 | 任何 MCP 客户端 / 任何能跑 shell 的 agent |
| 授权时效 | OAuth，会失效 → 反复要求登录 | 私钥，永不过期 |

### 扩展到「任意服务器 + 任意开发机 + 任意 agent」

- **加服务器** = 往 `~/.ssh-mcp/config.json` 加一条连接（同 host 不同连接名即可）。**不用改任何 IDE 设置。**
- **加开发机** = 在新机器上重跑本文档的三步。
- **加 agent** = 跑 `-Target <agent>`，或把它自己配置文件里的那一行加上。共享产物完全复用。
- **一台开发机一把 key**（或按需共用一把，见步骤 2 的说明）。
- 黑名单/超时/SFTP 范围都是 **per-connection** 的；黑名单的单一来源是仓库里的脚本，改一处即全局一致。

### 安全口径（用户 2026-09-20 明确）

**"防君子与外行"，不做高密级防护。** 据此已做与刻意不做：

| 项 | 状态 |
|---|---|
| SSH 仅密钥登录（`PasswordAuthentication no`） | ✅ 已做 —— 挡住扫描器/脚本小子（3 周 2.4 万次爆破尝试即此类） |
| 命令黑名单（含项目铁律） | ✅ 已做 |
| SFTP 范围收窄到 `/root/qqbot` | ✅ 已做 |
| CAM 策略资源级收窄 | ❌ 刻意不做 |
| AK/SK 不常驻磁盘 | ❌ 刻意不做 |
| NapCat WebUI（6099）收窄到固定 IP | ❌ 刻意不做（IP 不固定，代价大于收益） |
| 私钥加口令 | ❌ 刻意不做（会破坏 agent 可用性） |
