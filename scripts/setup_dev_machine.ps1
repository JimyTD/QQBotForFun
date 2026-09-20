#requires -Version 5.1
<#
.SYNOPSIS
    Onboard a dev machine to the QQBotForFun ops channel (idempotent, agent-agnostic).

.DESCRIPTION
    Sets up an agent-neutral SSH MCP channel, then registers it with whichever
    MCP-capable agents you name via -Target.

    Everything shared lives under a NEUTRAL path (~/.ssh-mcp/), so no single IDE owns it:
      ~/.ssh-mcp/server/            ssh-mcp-server (npm package)
      ~/.ssh-mcp/config.json        connection config + command blacklist
      ~/.ssh/qqbot_deploy           private key (plain OpenSSH key, usable by anything)

    It touches NO cloud credentials, NEVER modifies the git repo, and uploads nothing.

    One step cannot be automated: authorising this machine's public key ON the server,
    because that requires a non-SSH channel. The script prints the exact command.
    See docs/dev-machine-setup.md.

    NOTE: this file is intentionally kept pure ASCII. PowerShell 5.1 decodes files
    WITHOUT a BOM using the system ANSI codepage (GBK on zh-CN Windows), which shifts
    bytes inside multi-byte characters and can silently eat string terminators. Keep
    it ASCII-only so any editor/tool can rewrite it safely.

.PARAMETER Target
    Which agents to register with. Comma-separated. Default: codebuddy
      codebuddy   - writes %APPDATA%\CodeBuddy CN\...\codebuddy_mcp_settings.json  (key: mcpServers)
      cursor      - writes ~/.cursor/mcp.json                                      (key: mcpServers)
      windsurf    - writes ~/.codeium/windsurf/mcp_config.json                     (key: mcpServers)
      claudecode  - prints only (its user config is ~/.claude.json, a shared state file)
      vscode      - prints only (NOTE: root key is `servers`, not `mcpServers`)
      zed         - prints only (root key: context_servers)
      opencode    - prints only (root key: mcp)
      codex       - prints only (TOML: [mcp_servers.<name>])
      all         - every target above
      none        - set up shared artifacts only

.PARAMETER ListTargets
    Print the target table (config path + root key per agent) and exit.

.PARAMETER Verify
    Try connecting to the server afterwards to confirm the channel works.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Verify

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Target cursor,windsurf

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Target all
#>
[CmdletBinding()]
param(
    [string]$SshHost = '106.55.228.236',
    [string]$SshUser = 'root',
    [string]$ConnectionName = 'qqbot',
    [string]$RemoteProjectDir = '/root/qqbot',
    [string]$KeyPath,
    [string]$BaseDir,
    [string[]]$Target = @('codebuddy'),
    [switch]$ListTargets,
    [switch]$RegisterMcp,   # deprecated alias for -Target codebuddy
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'

function Info([string]$M) { Write-Host "[setup] $M" }
function Warn([string]$M) { Write-Host "[warn ] $M" -ForegroundColor Yellow }
function Fail([string]$M) { Write-Host "[fail ] $M" -ForegroundColor Red; exit 1 }

# Pitfall: PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM, and Node's
# JSON.parse rejects BOM-prefixed files. The MCP server then fails to start with
# "Invalid JSON in config file: Unexpected token '\uFEFF'". Always write via .NET.
function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

function Read-JsonFile([string]$Path) {
    return (Get-Content $Path -Raw | ConvertFrom-Json)
}

# Merge `$Entry` under `$RootKey` into a JSON config file, preserving everything else.
function Merge-JsonServer([string]$Path, [string]$RootKey, [string]$Name, $Entry) {
    $map = [ordered]@{}
    if (Test-Path $Path) {
        Copy-Item $Path "$Path.bak" -Force
        $existing = Read-JsonFile $Path
        $root = $existing.PSObject.Properties | Where-Object { $_.Name -eq $RootKey }
        if ($root) {
            foreach ($p in $root.Value.PSObject.Properties) { $map[$p.Name] = $p.Value }
        }
    } else {
        $dir = Split-Path -Parent $Path
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    }
    $map[$Name] = $Entry
    $out = [ordered]@{ $RootKey = $map }
    Write-Utf8NoBom $Path ($out | ConvertTo-Json -Depth 14)
}

# Which agents exist, where their config lives, and which root key they use.
# Kind 'json'  -> safe dedicated file, we can merge-write it.
# Kind 'print' -> shared/state file or exotic format; we only emit the snippet.
function Get-TargetTable([string]$UserProfile) {
    return [ordered]@{
        # VERIFIED 2026-09-20: this is the file CodeBuddy actually loads. The path the
        # docs point at (globalStorage/.../codebuddy_mcp_settings.json) is NOT read by
        # this build - registering there silently does nothing, which is exactly the
        # trap we fell into. Evidence: the servers that DO work in-session are listed here.
        codebuddy  = @{ Kind = 'json';  Key = 'mcpServers'; Path = (Join-Path $UserProfile '.codebuddy\mcp.json');                            Note = 'CodeBuddy - the working path is ~/.codebuddy/mcp.json (NOT globalStorage)' }
        cursor     = @{ Kind = 'json';  Key = 'mcpServers'; Path = (Join-Path $UserProfile '.cursor\mcp.json');                                        Note = 'Cursor' }
        windsurf   = @{ Kind = 'json';  Key = 'mcpServers'; Path = (Join-Path $UserProfile '.codeium\windsurf\mcp_config.json');                      Note = 'Windsurf' }
        claudecode = @{ Kind = 'print'; Key = 'mcpServers'; Path = '~/.claude.json  or  <repo>/.mcp.json';                                            Note = 'Claude Code (user config is a shared state file - edit by hand or use `claude mcp add`)' }
        vscode     = @{ Kind = 'print'; Key = 'servers';    Path = '<repo>/.vscode/mcp.json';                                                          Note = 'VS Code / Copilot Chat - ROOT KEY IS servers, NOT mcpServers' }
        zed        = @{ Kind = 'print'; Key = 'context_servers'; Path = (Join-Path $UserProfile '.config\zed\settings.json');                          Note = 'Zed - nested one level deeper than the others' }
        opencode   = @{ Kind = 'print'; Key = 'mcp';        Path = (Join-Path $UserProfile '.config\opencode\opencode.json');                           Note = 'OpenCode' }
        codex      = @{ Kind = 'print'; Key = '[mcp_servers.<name>]'; Path = (Join-Path $UserProfile '.codex\config.toml');                             Note = 'Codex CLI - TOML, not JSON' }
    }
}

$profile = $env:USERPROFILE
if (-not $KeyPath) { $KeyPath = Join-Path $profile '.ssh\qqbot_deploy' }
if (-not $BaseDir) { $BaseDir  = Join-Path $profile '.ssh-mcp' }

$ServerDir   = Join-Path $BaseDir 'server'
$ConfigPath  = Join-Path $BaseDir 'config.json'
$ServerEntry = Join-Path $ServerDir 'node_modules\@fangjunjie\ssh-mcp-server\build\index.js'
$targets     = Get-TargetTable $profile

if ($ListTargets) {
    Write-Host ''
    Write-Host 'Supported -Target values:' -ForegroundColor Cyan
    foreach ($k in $targets.Keys) {
        $t = $targets[$k]
        Write-Host ("  {0,-11} {1,-16} {2}" -f $k, $t.Key, $t.Path)
        Write-Host ("              {0}" -f $t.Note) -ForegroundColor DarkGray
    }
    Write-Host ''
    Write-Host '  all         register every target above'
    Write-Host '  none        shared artifacts only, no registration'
    Write-Host ''
    exit 0
}

if ($RegisterMcp -and -not $PSBoundParameters.ContainsKey('Target')) { $Target = @('codebuddy') }
if ($Target -contains 'all')  { $Target = @($targets.Keys) }
if ($Target -contains 'none') { $Target = @() }

foreach ($t in $Target) {
    if (-not $targets.Contains($t)) { Fail "unknown -Target '$t'. Run with -ListTargets to see the list." }
}

Write-Host ''
Write-Host '=== QQBotForFun dev-machine onboarding (agent-agnostic) ===' -ForegroundColor Cyan
Write-Host "  host         : $SshUser@$SshHost"
Write-Host "  connection   : $ConnectionName"
Write-Host "  private key  : $KeyPath"
Write-Host "  shared dir   : $BaseDir"
Write-Host "  conn config  : $ConfigPath"
Write-Host "  targets      : $(if ($Target.Count) { $Target -join ', ' } else { '(none)' })"
Write-Host ''

# ------------------------------------------------------------------ 1. Node.js
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) { Fail 'node not found. Install Node.js >= 18 first: https://nodejs.org/' }
$nodeVersion = (& node -v).Trim().TrimStart('v')
$nodeMajor = [int]($nodeVersion.Split('.')[0])
if ($nodeMajor -lt 18) { Fail "Node.js >= 18 required, found v$nodeVersion" }
Info "node v$nodeVersion -> $($nodeCmd.Source)"

# ------------------------------------------------------------------ 2. SSH key
if (Test-Path $KeyPath) {
    Info "key already exists, skipping generation: $KeyPath"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $KeyPath) | Out-Null

    # Pitfall: ssh-keygen reads the passphrase from the console (CONIN$), not stdin,
    # so piping input hangs forever.
    # Pitfall: PowerShell 5.1 DROPS empty-string arguments, turning `-N ''` into a bare
    # `-N`. Routing through a .cmd file keeps cmd's parsing, so `-N ""` really is empty.
    $tmpCmd  = Join-Path $env:TEMP "qqbot_genkey_$PID.cmd"
    $comment = "$([System.Net.Dns]::GetHostName())-codebuddy"
    @"
@echo off
ssh-keygen -t ed25519 -f "$KeyPath" -C "$comment" -N "" < nul
"@ | Set-Content -Path $tmpCmd -Encoding ASCII

    try { & cmd.exe /c $tmpCmd | Out-Host } finally { Remove-Item $tmpCmd -Force -ErrorAction SilentlyContinue }
    if (-not (Test-Path $KeyPath)) { Fail "ssh-keygen did not produce a key at $KeyPath" }
    Info "generated key: $KeyPath"
}

# If only the private key was copied over from another machine (no .pub sibling),
# derive the public key from it so a single-file copy is enough.
if (-not (Test-Path "$KeyPath.pub")) {
    Info 'no .pub file next to the private key - deriving it'
    & ssh-keygen -y -f $KeyPath | Set-Content -Path "$KeyPath.pub" -Encoding ASCII
    if (-not (Test-Path "$KeyPath.pub")) { Fail "could not derive the public key from $KeyPath" }
}

$pubKey = (Get-Content "$KeyPath.pub" -Raw).Trim()
try { $keyFingerprint = (& ssh-keygen -l -f "$KeyPath.pub" 2>&1) -join ' ' } catch { $keyFingerprint = '(unknown)' }
Info "public key fingerprint: $keyFingerprint"

# ------------------------------------------------------------------ 3. ssh-mcp-server
if (Test-Path $ServerEntry) {
    Info 'ssh-mcp-server already installed, skipping'
} else {
    New-Item -ItemType Directory -Force -Path $ServerDir | Out-Null
    Info 'installing ssh-mcp-server (~20s) ...'
    # The package name MUST be quoted, otherwise PowerShell parses the leading @ as splatting.
    & npm install --prefix $ServerDir '@fangjunjie/ssh-mcp-server' --no-fund --no-audit --loglevel=error | Out-Host
    if (-not (Test-Path $ServerEntry)) { Fail "install failed, entry not found: $ServerEntry" }
    Info 'ssh-mcp-server installed'
}

# ------------------------------------------------------------------ 4. connection config
# The blacklist is the project's hard rules made executable. It lives here (in the repo)
# and gets rendered onto each machine, so machines cannot drift apart.
# NOTE: use SINGLE backslashes in these single-quoted strings. ConvertTo-Json escapes
# them into the double backslashes that JSON requires. Do NOT write \\ here.
$blacklist = @(
    '\brm\s+(-[a-zA-Z]*\s+)*-?[rf]{1,2}[a-zA-Z]*\s+/(?:\s|$|\*)'                       # recursive delete of /
    '\brm\s+-[a-zA-Z]*r[a-zA-Z]*f?[a-zA-Z]*\s+/(etc|var|usr|bin|boot|lib|opt|home|root|data)\b'
    '\bmkfs(\.\w+)?\b'                                                                  # filesystem format
    '\bdd\b[^\n]*\bof=/dev/'                                                            # raw write to a block device
    '\b(shutdown|reboot|halt|poweroff)\b'                                               # host shutdown / reboot
    '\biptables\s+-F\b'                                                                 # flush firewall
    '\bufw\s+(disable|reset)\b'
    '\buserdel\b|\bpasswd\s+root\b'                                                     # account modification
    '\bdocker\s+system\s+prune\b[^\n]*(-a|--all)'                                       # wipes all image cache
    '\bdocker\s+volume\s+rm\b'                                                          # deletes a data volume
    '\bgit\s+clean\s+-[a-zA-Z]*[dfx]'                                                   # deletes .env (sole authoritative copy)
    '\bgit\s+pull\b'                                                                     # use fetch + reset instead
    '\bdocker\s+compose\s+down\b'                                                        # kills NapCat -> requires re-scanning
    '\bdocker\s+compose\s+(rm|stop|kill)\b[^\n]*napcat\b'                                # same
    '\bgit\s+push\b[^\n]*--force\b'
    ':\s*\(\s*\)\s*\{.*\}\s*;\s*:'                                                       # fork bomb
)
# Deliberately NOT blacklisted: '\bgit\s+reset\s+--hard\b' - the deploy flow needs it.

$connection = [ordered]@{
    host                = $SshHost
    port                = 22
    username            = $SshUser
    privateKey          = ($KeyPath -replace '\\', '/')
    transportMode       = 'exec'
    commandTimeoutMs    = 600000   # 10 min: enough for `docker compose build` with akshare
    connectionTimeoutMs = 30000
    keepaliveIntervalMs = 30000    # keep the link alive during long builds
    keepaliveCountMax   = 5
    allowedRemotePaths  = @($RemoteProjectDir)   # narrow the SFTP surface
    commandBlacklist    = $blacklist
}

New-Item -ItemType Directory -Force -Path $BaseDir | Out-Null

if (Test-Path $ConfigPath) {
    Copy-Item $ConfigPath "$ConfigPath.bak" -Force
    $existing = Read-JsonFile $ConfigPath
    $map = [ordered]@{}
    foreach ($p in $existing.PSObject.Properties) { $map[$p.Name] = $p.Value }
    $map[$ConnectionName] = $connection
    Info "merged into existing config (other connections kept, backup: $ConfigPath.bak)"
} else {
    $map = [ordered]@{}
    $map[$ConnectionName] = $connection
    Info 'created new connection config'
}
Write-Utf8NoBom $ConfigPath ($map | ConvertTo-Json -Depth 14)
Info "wrote: $ConfigPath (UTF-8, no BOM)"

# A leftover from the previous CodeBuddy-only layout - mention it so it gets cleaned up.
$legacyConfig = Join-Path $profile '.codebuddy\ssh-mcp-config.json'
if (Test-Path $legacyConfig) {
    Warn "legacy CodeBuddy-only config still present, you can delete it: $legacyConfig"
}

# ------------------------------------------------------------------ 5. register with agents
$serverName = "$ConnectionName-ssh"
$mcpEntry = [ordered]@{
    type    = 'stdio'
    command = ($nodeCmd.Source -replace '\\', '/')
    args    = @(($ServerEntry -replace '\\', '/'), '--config-file', ($ConfigPath -replace '\\', '/'))
}
$snippet = ($mcpEntry | ConvertTo-Json -Depth 8)

foreach ($t in $Target) {
    $spec = $targets[$t]
    if ($spec.Kind -eq 'json') {
        Merge-JsonServer -Path $spec.Path -RootKey $spec.Key -Name $serverName -Entry $mcpEntry
        Info "registered '$serverName' for $t ($($spec.Key)) -> $($spec.Path)"
    }
}

$manual = @($Target | Where-Object { $targets[$_].Kind -eq 'print' })
if ($manual.Count) {
    Write-Host ''
    Write-Host '--- manual registration needed for: ' -NoNewline -ForegroundColor Yellow
    Write-Host ($manual -join ', ')
    foreach ($t in $manual) {
        $spec = $targets[$t]
        Write-Host ''
        Write-Host ("  {0}  -  {1}" -f $t, $spec.Note) -ForegroundColor Green
        Write-Host ("  file        : {0}" -f $spec.Path)
        Write-Host ("  root key    : {0}" -f $spec.Key)
        Write-Host '  entry       :' -NoNewline
        Write-Host ('  "' + $serverName + '": ' + $snippet) -ForegroundColor Gray
    }
}

# ------------------------------------------------------------------ 6. the one manual step
$installCmd = "install -d -m 700 /root/.ssh; touch /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys; grep -qxF '$pubKey' /root/.ssh/authorized_keys || echo '$pubKey' >> /root/.ssh/authorized_keys; echo '--- authorized_keys ---'; tail -3 /root/.ssh/authorized_keys"

Write-Host ''
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' THE ONE STEP THAT NEEDS A HUMAN (or another onboarded box)' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'This machine public key:' -ForegroundColor Yellow
Write-Host $pubKey
Write-Host ''
Write-Host 'Pick one of three routes:' -ForegroundColor Yellow
Write-Host ''
Write-Host '  [A] RECOMMENDED - Tencent Cloud console -> Lighthouse -> Login (OrcaTerm web terminal),' -ForegroundColor Green
Write-Host '      then paste the command below. It bypasses sshd entirely, so it needs no port,'
Write-Host '      no IP allowlist and no credentials.'
Write-Host ''
Write-Host '  [B] On ANOTHER already-onboarded machine, have the agent run the same command'
Write-Host '      (via the qqbot-ssh channel, tool execute-command).'
Write-Host ''
Write-Host '  [C] Temporarily mount the TAT MCP (needs Tencent Cloud AK/SK; unmount when done).'
Write-Host ''
Write-Host "      $installCmd" -ForegroundColor Gray
Write-Host ''

# ------------------------------------------------------------------ 7. optional verify
if ($Verify) {
    Write-Host '=== trying to connect ===' -ForegroundColor Cyan
    & ssh -i $KeyPath -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$SshUser@$SshHost" 'hostname; whoami; ls -d /root/qqbot'
    if ($LASTEXITCODE -eq 0) {
        Write-Host ''
        Write-Host 'CHANNEL OK - restart your agent / open a new chat so the MCP tools load.' -ForegroundColor Green
        Write-Host 'Note: agent sessions snapshot their MCP tool list at startup, so an already-running'
        Write-Host 'session will not see the new server until it restarts.'
    } else {
        Write-Host ''
        Warn 'Connection refused - most likely the public key was never installed on the server.'
    }
}

Write-Host ''
