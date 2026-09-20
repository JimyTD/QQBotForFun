#requires -Version 5.1
<#
.SYNOPSIS
    Onboard a new dev machine to the QQBotForFun ops channel (idempotent).

.DESCRIPTION
    Does three things so an agent on this machine can operate the server over SSH MCP:

      1. Generate a machine-local SSH key pair (ed25519, no passphrase)
      2. Install ssh-mcp-server into ~/.codebuddy/mcp/
      3. Create/update the connection config ~/.codebuddy/ssh-mcp-config.json

    It touches NO cloud credentials, NEVER modifies the git repo, and uploads nothing.

    One step cannot be automated: authorising this machine's public key ON the server,
    because that requires a non-SSH channel. The script prints the exact command.
    See docs/dev-machine-setup.md.

    NOTE: this file is intentionally kept pure ASCII. PowerShell 5.1 decodes files
    WITHOUT a BOM using the system ANSI codepage (GBK on zh-CN Windows), which shifts
    bytes inside multi-byte characters and can silently eat string terminators. Keep
    it ASCII-only so any editor/tool can rewrite it safely. See docs, "Pitfall log".

.PARAMETER RegisterMcp
    Also register the MCP server in CodeBuddy global settings (existing file is backed up).

.PARAMETER Verify
    Try connecting to the server afterwards to confirm the channel works.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -Verify

.EXAMPLE
    # Already onboarded: just re-sync the command blacklist and register the MCP.
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup_dev_machine.ps1 -RegisterMcp
#>
[CmdletBinding()]
param(
    [string]$SshHost = '106.55.228.236',
    [string]$SshUser = 'root',
    [string]$ConnectionName = 'qqbot',
    [string]$RemoteProjectDir = '/root/qqbot',
    [string]$KeyPath,
    [string]$SettingsPath,
    [switch]$RegisterMcp,
    [switch]$Verify
)

$ErrorActionPreference = 'Stop'

function Info([string]$M) { Write-Host "[setup] $M" }
function Warn([string]$M) { Write-Host "[warn ] $M" -ForegroundColor Yellow }
function Fail([string]$M) { Write-Host "[fail ] $M" -ForegroundColor Red; exit 1 }

# Pitfall 3: PowerShell 5.1's `Set-Content -Encoding UTF8` writes a BOM, and Node's
# JSON.parse rejects BOM-prefixed files. The MCP server then fails to start with
# "Invalid JSON in config file: Unexpected token '\uFEFF'". Always write via .NET.
function Write-Utf8NoBom([string]$Path, [string]$Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
}

# ------------------------------------------------------------------ resolve paths
if (-not $KeyPath) { $KeyPath = Join-Path $env:USERPROFILE '.ssh\qqbot_deploy' }
if (-not $SettingsPath) {
    $SettingsPath = Join-Path $env:APPDATA 'CodeBuddy CN\User\globalStorage\tencent.planning-genie\settings\codebuddy_mcp_settings.json'
}

$KeyDir       = Split-Path -Parent $KeyPath
$CodeBuddyDir = Join-Path $env:USERPROFILE '.codebuddy'
$McpDir       = Join-Path $CodeBuddyDir 'mcp\ssh-mcp-server'
$ConfigPath   = Join-Path $CodeBuddyDir 'ssh-mcp-config.json'
$McpEntry     = Join-Path $McpDir 'node_modules\@fangjunjie\ssh-mcp-server\build\index.js'

Write-Host ''
Write-Host '=== QQBotForFun dev-machine onboarding ===' -ForegroundColor Cyan
Write-Host "  host        : $SshUser@$SshHost"
Write-Host "  connection  : $ConnectionName"
Write-Host "  private key : $KeyPath"
Write-Host "  mcp server  : $McpDir"
Write-Host "  conn config : $ConfigPath"
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
    New-Item -ItemType Directory -Force -Path $KeyDir | Out-Null

    # Pitfall 1: ssh-keygen reads the passphrase from the console (CONIN$), not stdin,
    # so piping input hangs forever.
    # Pitfall 2: PowerShell 5.1 DROPS empty-string arguments, turning `-N ''` into a
    # bare `-N`. Routing through a .cmd file keeps cmd's argument parsing, so `-N ""`
    # really is an empty passphrase. `< nul` is a second line of defence.
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

$pubKey = (Get-Content "$KeyPath.pub" -Raw).Trim()
try { $keyFingerprint = (& ssh-keygen -l -f "$KeyPath.pub" 2>&1) -join ' ' } catch { $keyFingerprint = '(unknown)' }
Info "public key fingerprint: $keyFingerprint"

# ------------------------------------------------------------------ 3. ssh-mcp-server
if (Test-Path $McpEntry) {
    Info 'ssh-mcp-server already installed, skipping'
} else {
    New-Item -ItemType Directory -Force -Path $McpDir | Out-Null
    Info 'installing ssh-mcp-server (~20s) ...'
    # The package name MUST be quoted, otherwise PowerShell parses the leading @ as splatting.
    & npm install --prefix $McpDir '@fangjunjie/ssh-mcp-server' --no-fund --no-audit --loglevel=error | Out-Host
    if (-not (Test-Path $McpEntry)) { Fail "install failed, entry not found: $McpEntry" }
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

New-Item -ItemType Directory -Force -Path $CodeBuddyDir | Out-Null

if (Test-Path $ConfigPath) {
    Copy-Item $ConfigPath "$ConfigPath.bak" -Force
    $existing = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $map = [ordered]@{}
    foreach ($p in $existing.PSObject.Properties) { $map[$p.Name] = $p.Value }
    $map[$ConnectionName] = $connection
    Info "merged into existing config (other connections kept, backup: $ConfigPath.bak)"
} else {
    $map = [ordered]@{}
    $map[$ConnectionName] = $connection
    Info 'created new connection config'
}

Write-Utf8NoBom $ConfigPath ($map | ConvertTo-Json -Depth 12)
Info "wrote: $ConfigPath (UTF-8, no BOM)"

# ------------------------------------------------------------------ 5. optional MCP registration
$mcpServerEntry = [ordered]@{
    type    = 'stdio'
    command = $nodeCmd.Source -replace '\\', '/'
    args    = @(($McpEntry -replace '\\', '/'), '--config-file', ($ConfigPath -replace '\\', '/'))
}

if ($RegisterMcp) {
    if (-not (Test-Path $SettingsPath)) {
        Warn "CodeBuddy settings not found, skipping registration: $SettingsPath"
    } else {
        Copy-Item $SettingsPath "$SettingsPath.bak" -Force
        $settings = Get-Content $SettingsPath -Raw | ConvertFrom-Json
        $servers = [ordered]@{}
        if ($settings.mcpServers) {
            foreach ($p in $settings.mcpServers.PSObject.Properties) { $servers[$p.Name] = $p.Value }
        }
        $servers[$ConnectionName + '-ssh'] = $mcpServerEntry
        $out = [ordered]@{ mcpServers = $servers }
        Write-Utf8NoBom $SettingsPath ($out | ConvertTo-Json -Depth 12)
        Info "registered MCP '$ConnectionName-ssh' (backup: $SettingsPath.bak)"
    }
}

# ------------------------------------------------------------------ 6. print the one manual step
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
Write-Host '  [A] RECOMMENDED - on ANOTHER already-onboarded dev machine, have the agent run:' -ForegroundColor Green
Write-Host '      (via the qqbot-ssh channel, tool execute-command, connectionName=qqbot)'
Write-Host ''
Write-Host "      $installCmd" -ForegroundColor Gray
Write-Host ''
Write-Host '  [B] Tencent Cloud console -> Lighthouse -> Login (OrcaTerm), paste the same command' -ForegroundColor Green
Write-Host ''
Write-Host '  [C] Temporarily mount the TAT MCP (needs Tencent Cloud AK/SK; unmount when done)' -ForegroundColor Green
Write-Host ''
if (-not $RegisterMcp) {
    Write-Host 'MCP registration (or paste it into CodeBuddy Settings -> MCP):' -ForegroundColor Yellow
    Write-Host (($mcpServerEntry | ConvertTo-Json -Depth 6)) -ForegroundColor Gray
    Write-Host ''
}

# ------------------------------------------------------------------ 7. optional verify
if ($Verify) {
    Write-Host '=== trying to connect ===' -ForegroundColor Cyan
    & ssh -i $KeyPath -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 "$SshUser@$SshHost" 'hostname; whoami; ls -d /root/qqbot'
    if ($LASTEXITCODE -eq 0) {
        Write-Host ''
        Write-Host 'CHANNEL OK - next: restart CodeBuddy (or open a new chat) so the MCP tools load.' -ForegroundColor Green
    } else {
        Write-Host ''
        Warn 'Connection refused - most likely the public key was never installed on the server.'
    }
}

Write-Host ''
