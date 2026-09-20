# 去 Lighthouse 化迁移指南（通用版）

> **适用对象**：任何用 CodeBuddy + 腾讯云 Lighthouse 做运维的项目（本文档的宿主项目是 QQBotForFun，但内容刻意写成项目无关的）。
>
> **读的人可能是人，也可能是另一个 agent** —— 所以下面全部写成可执行步骤，不给"大概思路"。
>
> **参考实现**：`QQBotForFun/scripts/setup_dev_machine.ps1`（可直接抄的 PowerShell 脚本）+ `docs/dev-machine-setup.md`（宿主项目的落地手册）。
> 你要做的不是重写，而是**按 §4 改几个参数**。

---

## §1 为什么必须迁（判据）

### 1.1 CodeBuddy 内置 Lighthouse 集成有两个独立的死因

任一都足以判死，两个同时成立：

| # | 死因 | 表现 |
|---|---|---|
| 1 | **OAuth 授权会失效** | 失效后所有调用返回 `Token verification failed. Please check your Token is correct.`，必须人工重新登录授权。实测：连续 3 次调用 3 次失败 |
| 2 | **锚点跨工作区共享** | 绑定是**云端账号级单锚点**，工作区里的 `.codebuddy/integration/lighthouse.json` 只是"当时锚在哪"的镜像，**不是 per-workspace 绑定** |

第 2 条的实证：在一台机器上同时有 A、B 两个项目，A 项目的操作把 B 项目工作区里的锚点文件从 B 自己的实例改成了 A 的实例。**两个项目会互相覆盖部署目标** —— 这是数据安全级别的隐患，不只是不方便。

### 1.2 它完全不 agent 中立

它只能被 CodeBuddy 用。换 Cursor / Claude Code / VS Code 就用不了，CLI 也无法调用。

### 1.3 自查：你的项目还在依赖它吗

```bash
# 集成的工具名 / 锚点文件（注意 .codebuddy 是隐藏目录，ripgrep 默认跳过，必须单独搜）
grep -rn "execute_command\|deploy_project_preparation\|Configure Integration" \
     --include=*.md --include=*.mdc --include=*.py --include=*.ts .
grep -rn "execute_command\|Lighthouse" .codebuddy/

# 锚点文件（每个工作区一份，本地文件，通常没进 git）
ls .codebuddy/integration/lighthouse.json 2>/dev/null

# 文档/规则里是否还写着"用 lighthouse execute_command 执行命令"
grep -rn "lighthouse" docs/ .codebuddy/rules/
```

⚠️ 注意排除同名噪音：AoE3 里有个单位就叫 Lighthouse，Red Alert 2 里有 `denuggetlighthouse.png`。

---

## §2 目标架构

### 2.1 三层兼容性（越往下越通用）

| 层 | 内容 | 谁能用 |
|---|---|---|
| **协议层** | 标准 stdio MCP server（`@fangjunjie/ssh-mcp-server`，基于官方 MCP SDK） | **任何**支持 MCP 的客户端 |
| **凭据层** | `~/.ssh/<key>`，就是一把普通 OpenSSH 私钥 | 任何 SSH 工具、脚本、人 |
| **降级层** | 原生 `ssh -i <key> user@host "<cmd>"` | **任何能跑 shell 的 agent** —— 连 MCP 都不需要 |

**降级层是这套方案最值钱的部分**：即使某天所有 MCP 客户端都不支持了，`ssh` 还在。

### 2.2 通道分工

| 通道 | 定位 | 依赖 | 何时用 |
|---|---|---|---|
| **SSH MCP**（主力） | 日常运维与部署 | 22 端口 + 私钥 | 99% 的操作 |
| **控制台网页终端**（引导） | 装/修公钥、救火 | 浏览器 + 云账号 | 每台新机器接入一次；SSH 配坏时兜底 |
| **TAT MCP**（可选，仅腾讯云） | 腾讯云 API 层操作、脚本化引导 | 云 AK/SK + TAT agent | 低频；不想开浏览器时 |

### 2.3 产物布局（agent 中立，不挂在任何 IDE 目录下）

```
~/.ssh/<project>_deploy           私钥（+ .pub）        ← 通用，任何东西都能用
~/.ssh-mcp/server/                 MCP server（npm 包）  ← 所有项目可共用
~/.ssh-mcp/config.json             连接配置 + 命令黑名单 ← 一个文件放多个具名连接
<agent 自己的配置文件>              只是指向上面那两样的一行
```

**关键设计**：MCP 只注册**一次**，加服务器/加项目 = 往 `config.json` 加一条具名连接，**不用改任何 IDE 设置**。

---

## §3 迁移 SOP

### Step 0：记录现状（5 分钟，别跳）

```bash
# 你现在的服务器上跑着什么、在哪个 commit、有没有漂移
ssh ... "docker compose ps; git -C <项目目录> rev-parse --short HEAD; git -C <项目目录> status --short"
```
把结果记下来，迁移后要能对上。**尤其是 git status 必须为空** —— 有空行说明服务器被手改过，先搞清楚再动。

### Step 1：本机准备（生成密钥 + 装 MCP server + 写连接配置）

抄参考实现，按 §4 改参数后运行：

```powershell
git clone https://github.com/JimyTD/QQBotForFun.git   # 或者把 setup_dev_machine.ps1 抄到你自己的仓库
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Target <你的agent>
```

脚本是幂等的，可以反复跑。它做的事：
1. 检查 Node >= 18
2. 生成 `~/.ssh/<project>_deploy`（ed25519，无口令）
3. 装 `ssh-mcp-server` 到 `~/.ssh-mcp/server/`
4. 生成/合并 `~/.ssh-mcp/config.json`（含命令黑名单）
5. 按 `-Target` 注册到对应 agent

### Step 2：装公钥（唯一的人工步骤）

**这是结构性的引导问题，绕不开**：装公钥本身需要一条非 SSH 通道，而这条通道不能依赖 SSH（否则死循环）。

三条路，选一条：

| 路线 | 做法 | 代价 |
|---|---|---|
| **[A] 推荐** | 云控制台 → 找到实例 → 点「登录」（网页终端，腾讯云叫 OrcaTerm）→ 粘脚本打印的那条命令 | 浏览器点几下。**完全绕开 sshd**（实测：有 orcaterm 会话记录但 auth.log 里 0 条 sshd `Accepted`），不需要 22 端口 / IP 白名单 / AK/SK |
| **[B]** | 在另一台**已接入**的机器上，让 agent 跑同一条命令 | 需要两台机器同时在场 |
| **[C]** | 临时挂 TAT MCP 跑命令，用完摘掉 | 需要云 AK/SK |

路线 A 的关键性质：**它绕开 sshd，所以 sshd 配坏了也照样能进** —— 这是兜底通道该有的样子。

> **想彻底免掉这一步**：新机器不生成新密钥，把已接入机器的私钥文件拷过去（脚本检测到密钥已存在会跳过生成，并自动派生出缺失的 `.pub`，**只需拷 1 个文件**）。代价是所有机器共用一把 key，丢一台等于全部泄露 —— 对"一台服务器 + 任意开发机"通常划算。

### Step 3：注册到你用的 agent

`-Target <agent>`。支持的取值与各自的配置文件/根键见 §5。

### Step 4：验证

```bash
# 脚本加 -Verify 会自己试连；手动的话：
ssh -i ~/.ssh/<project>_deploy <user>@<host> "hostname; whoami; ls -d <项目目录>"
```
期望看到主机名 + 正确身份 + 项目目录。**对不上就别往下走。**

### Step 5：写命令黑名单（这一步最容易漏）

参考实现里有一份 16 条的黑名单，思路是：**把项目铁律变成可执行的拒绝规则**。你必须按自己项目的铁律改，至少要覆盖：

| 类别 | 为什么 |
|---|---|
| `git clean -f*` | 会删掉未跟踪文件（比如 `.env`，可能本地无副本） |
| 递归删 `/`、系统目录 | 显而易见 |
| `mkfs` / `dd of=/dev/*` | 毁盘 |
| `shutdown` / `reboot` / `halt` | 失联 |
| `iptables -F` / `ufw disable` | 自断后路 |
| `docker volume rm` / `docker system prune -a` | 删数据卷 / 清镜像缓存 |
| 你自己项目的雷区 | 例：QQBot 项目禁 `docker compose down` 和动 napcat（会触发重新扫码） |

**刻意不要列入的**：`git reset --hard` —— 部署流程本身要用它（如果误列入，部署会永久卡死且没有逃生口，因为 ssh-mcp-server 的黑名单**没有 confirmDangerous 之类的豁免机制**）。

黑名单是**正则、任意位置匹配**（`regex.test(command)`），所以会对整条复合命令生效。

### Step 6：清理 Lighthouse 集成（"去 lighthouse 化"的本体）

四件事，缺一不可：

1. **文档/规则里改成明确禁用**，不要只写"已废弃"。要写清：禁用哪些工具 + 两条独立死因 + 替代品分别是谁。
2. **删掉工作区锚点文件**（本地文件，通常不在 git 里）：
   ```bash
   rm .codebuddy/integration/lighthouse.json
   ```
   ⚠️ 如果同一台机器上有**其他项目**也用了这个集成，它们的锚点文件会被互相覆盖 —— 一并检查。
3. **全仓排查残留引用**（见 §1.4），把"用内置 `execute_command`"这类指令全部清掉。**这一步最关键**：agent 是读文档干活的，留一条旧指令，下一个 agent 就会去撞坏掉的东西。
4. **把判定标准改成"以实测为准"**：不要在任何文档里写死"XX 目录是生产目录"、"锚点指向 YY"这类会过期的结论。改成"跑 `docker compose ls` 看 CONFIG FILES"。

**唯一的能力缺口**：腾讯云 Lighthouse 防火墙规则的读写没有对应 MCP 工具。走控制台，或直接用云 API（参考 `tencent-lighthouse-mcp/src/tencent-api.js` 里的 TC3 签名实现，可复用）。

### Step 7：服务器侧硬化

```bash
# 仅密钥登录。用 drop-in 文件，不要改主配置
cat > /etc/ssh/sshd_config.d/10-hardening.conf <<'EOF'
PasswordAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF

sshd -t && systemctl reload ssh      # 先校验，再 reload
sshd -T | grep -iE 'passwordauth|permitroot'
```

**改 sshd 的通则**：
- **先 `sshd -t` 校验，再 `reload`（绝不用 `restart`）** —— reload 失败时旧配置继续生效，restart 会把你锁在门外。
- **回滚**：`rm /etc/ssh/sshd_config.d/10-hardening.conf && systemctl reload ssh`
- **drop-in 要排序在前**：OpenSSH 对同一关键字取**首个**值，而 `Include /etc/ssh/sshd_config.d/*.conf` 通常在主文件靠前位置。云厂商常自带 `50-cloud-init.conf`，所以用 `10-` 前缀压过它，**同时也扛住 cloud-init 重写**。

**为什么值得做**：实测一台公网服务器 3 周被爆破 **23,953 次**（0 次成功）。关掉密码认证后这些尝试全部无效，而报错也会从 `Permission denied (publickey,password)` 变成 `Permission denied (publickey)` —— 可以直接用这个判断是否生效。

**不用做的**（除非你的项目真有高密级数据）：按 IP 收窄 22 端口、私钥加口令、云凭据不常驻。这些会显著牺牲"任意开发机"的灵活性。

---

## §4 每个项目必须改的参数

| 参数 | 说明 |
|---|---|
| `-SshHost` / `-SshUser` | 你的服务器 |
| `-ConnectionName` | 连接名，**多项目共用一份 config 时必须唯一**，如 `qqbot` / `silentwerewolf` |
| `-RemoteProjectDir` | 项目在服务器上的目录（用于收窄 SFTP 范围），如 `/root/qqbot` |
| `-KeyPath` | 默认 `~/.ssh/qqbot_deploy` → 改成 `~/.ssh/<project>_deploy` |
| `-BaseDir` | `~/.ssh-mcp`。**多项目建议共用**（一份 config 多连接，MCP 只注册一次） |
| `-Target` | 你用的 agent，见 §5 |
| **黑名单** | **必须按 §5 步骤 5 改写** —— 这是唯一不能直接抄的部分 |
| 引导通道 | 腾讯云有 TAT 可用；其他云厂商只能靠控制台网页终端，或临时用密码认证装完公钥再切 key |

**共用 vs 隔离 `-BaseDir` 的取舍**：

| | 共用 `~/.ssh-mcp/`（推荐） | 每项目一个 BaseDir |
|---|---|---|
| MCP 注册次数 | 1 次 | 每项目 1 次 |
| 加服务器 | 加一条连接 | 加一个 MCP server |
| 隔离性 | 命令黑名单是 per-connection 的，仍可各自不同 | 完全隔离 |
| 风险 | 一个文件坏了影响所有项目 | — |

---

## §5 跨 agent 配置对照表

| agent | 配置文件 | 根键 | 备注 |
|---|---|---|---|
| **CodeBuddy** | **`~/.codebuddy/mcp.json`** ⚠️ | `mcpServers` | **实测确认**。官方文档指向的 `%APPDATA%\CodeBuddy CN\...\globalStorage\...\codebuddy_mcp_settings.json` **本版本不读**，写进去静默无效 |
| Cursor | `~/.cursor/mcp.json`（全局）/ `<repo>/.cursor/mcp.json`（项目） | `mcpServers` | 支持项目级 |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` | `mcpServers` | |
| Claude Code | `~/.claude.json`（用户）/ `<repo>/.mcp.json`（项目） | `mcpServers` | 用户配置是**共享状态文件**，手改有风险，建议 `claude mcp add` |
| VS Code / Copilot | `<repo>/.vscode/mcp.json` | **`servers`** ⚠️ | **唯一不是 `mcpServers` 的主流客户端**，从 Cursor 复制过来必翻车 |
| Zed | `~/.config/zed/settings.json` | `context_servers` | 结构多嵌一层 |
| OpenCode | `~/.config/opencode/opencode.json` | `mcp` | |
| Codex CLI | `~/.codex/config.toml` | `[mcp_servers.<name>]` | **TOML**，不是 JSON |

**只有 CodeBuddy 那行是实测确认的**，其余来自公开文档汇总 —— 首次使用请核对官方文档。

**但里面那 5 行是逐字相同的**：

```jsonc
{
  "type": "stdio",
  "command": "<node 绝对路径>",
  "args": [
    "<home>/.ssh-mcp/server/node_modules/@fangjunjie/ssh-mcp-server/build/index.js",
    "--config-file",
    "<home>/.ssh-mcp/config.json"
  ]
}
```

换 agent = 把这个对象贴进它自己的配置文件的对应根键下。**共享产物完全复用，不需要重建。**

**应急 CLI 桥**（不需要 agent 注册，也不会被"会话快照"卡住）：

```bash
node scripts/mcp_call.mjs <serverName> <toolName> [argsFileOrInlineJson]
node scripts/mcp_call.mjs --list-servers          # 看读了哪个配置文件、有哪些 server
node scripts/mcp_call.mjs --settings <path> ...   # 显式指定配置文件
```

---

## §6 坑日志（全部实测踩出来的，抄过去能省一天）

| # | 坑 | 表现 | 解法 |
|---|---|---|---|
| 1 | **CodeBuddy 的 MCP 配置有两个候选文件，只有一个生效** | 注册后工具永远不出现，**零报错** | 只写 `~/.codebuddy/mcp.json`。判断方法：看会话里已生效的 server 在哪个文件里 |
| 2 | **`Set-Content -Encoding UTF8` 在 PS 5.1 会写 BOM** | Node 的 `JSON.parse` 拒绝 → MCP server 启动即失败（`Unexpected token '\uFEFF'`） | 用 `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)` |
| 3 | **PowerShell 5.1 对无 BOM 文件按系统 ANSI（GBK）解码** | 脚本里写中文 → 多字节字符错位吃掉字符串结束引号 → 报 `string is missing the terminator` / `|| is not a valid statement separator` | **脚本保持纯 ASCII**，中文说明放 `.md` |
| 4 | **PowerShell 的转义符是反引号，不是反斜杠** | 双引号字符串里写 `\"` 不会转义，那个 `"` 直接终止字符串 → 报 `意外的标记 "{"` | 用单引号拼接，或双写 `""` |
| 5 | **`ssh-keygen` 从 `CONIN$` 读口令，不走 stdin** | 用管道喂空口令 → **永久卡住**，无输出直到超时 | 用 `-N ""` 并加 `< nul` |
| 6 | **PowerShell 5.1 会丢掉空字符串参数** | `-N ''` 变成裸的 `-N`，ssh-keygen 报错 | 把命令写进 `.cmd` 文件用 cmd 的参数解析 |
| 7 | **`@` 开头的包名在 PowerShell 里要加引号** | `npm install @scope/pkg` 被解析成 splatting | `'@scope/pkg'` |
| 8 | **agent 会话在启动时快照工具清单** | 运行中注册的 MCP 不生效 | 开新会话，或先用 CLI 桥 |
| 9 | **ripgrep 默认跳过隐藏目录** | 搜不到 `.codebuddy/` 里的残留引用，误以为清干净了 | 单独搜 `.codebuddy/` |

---

## §7 验收清单

- [ ] `ssh -i <key> <user>@<host> "hostname"` 能通，**且密码认证已关闭**（报错里没有 `password` 选项）
- [ ] `node scripts/mcp_call.mjs --list-servers` 能看到你的 server，且它读的是**生效的那个**配置文件
- [ ] 新开一个 agent 会话，原生 MCP 工具里能看到你的 SSH server
- [ ] `grep -rn "execute_command\|deploy_project_preparation" --include=*.md --include=*.mdc .` 与 `grep -rn "execute_command\|Lighthouse" .codebuddy/` 的结果**全部是"禁用/历史"语境**，没有一条是指令
- [ ] `.codebuddy/integration/lighthouse.json` 已删除（**同机其他项目也要查**）
- [ ] 命令黑名单包含你项目的全部铁律，且**不含** `git reset --hard` 这类部署必需的
- [ ] 服务器 `git status --short` 为空（与 Step 0 记录一致）
- [ ] 跑一次真实部署，确认走的是新通道

---

## §8 成本收益（诚实版）

**成本**：
- 每台开发机 3 步（脚本 + 装公钥 + 开新会话）
- 每台服务器一次性装公钥
- 黑名单需要按项目改写一次

**收益**：
- 从"每次干活前可能先卡在重新登录授权"变成**永不失效**
- 从"两个项目互相覆盖部署目标"变成**互不干扰**
- 从"只有 CodeBuddy 能用"变成**任何 agent 都能用**
- 命令黑名单让项目铁律**可执行**，不再只靠文档约束 agent

**唯一退不回去的点**：如果你重度依赖那个冷启动的"一键部署"按钮，迁移后没有等价物 —— 但那个按钮本身就是坏的，等价物实际是"SSH 通道 + git 部署流程"，本来就更可控。

---

## 附：本文档的宿主项目落地记录（可作对照）

QQBotForFun 于 2026-09-20 完成迁移，提交序列：

| commit | 内容 |
|---|---|
| `30dc1a0` | 新开发机一键接入手册与脚本；CLI 桥 |
| `48fdefc` | 只拷私钥时自动派生公钥（从拷两个文件简化为一个） |
| `db9c646` | SSH 硬化（仅密钥登录）+ 安全基线与回滚方法 |
| `1bbb1b9` | 内置 Lighthouse 集成从"废弃"升级为**永久禁用** |
| `f4e60fc` | 统一规则与手册口径（OrcaTerm 优先），修正表格里不存在的工具 |
| `a9fc051` | 接入方案改为 **agent 中立**（`~/.ssh-mcp` + `-Target` 多客户端） |

参考实现文件：`scripts/setup_dev_machine.ps1`、`scripts/mcp_call.mjs`、`docs/dev-machine-setup.md`、`.codebuddy/rules/server-ops.mdc`。
