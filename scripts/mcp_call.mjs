#!/usr/bin/env node
/**
 * CLI bridge: call any MCP server registered with a local MCP client, without the client.
 *
 * Why this exists: agent sessions snapshot their MCP tool list at startup, so a server
 * registered mid-session shows up as "not found or not connected" even though the config
 * is perfectly valid. This bridge talks MCP over stdio directly, so onboarding and
 * bootstrapping do not have to wait for an agent restart.
 *
 * Credentials are read from the client's own settings file, so nothing is duplicated.
 *
 * Usage:
 *   node scripts/mcp_call.mjs <serverName> <toolName> [argsFileOrInlineJson]
 *   node scripts/mcp_call.mjs --list-servers
 *
 *   --settings <path>   which MCP client settings file to read (see below)
 *
 * Settings file resolution order:
 *   1. --settings <path>
 *   2. $MCP_SETTINGS
 *   3. $CODEBUDDY_MCP_SETTINGS   (deprecated alias, still honoured)
 *   4. auto-detect: CodeBuddy CN -> Cursor -> Windsurf -> <repo>/.mcp.json
 */
import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const REL = ["User", "globalStorage", "tencent.planning-genie", "settings", "codebuddy_mcp_settings.json"];

function candidateSettings() {
  const home = os.homedir();
  const list = [];

  // VERIFIED 2026-09-20: CodeBuddy loads ~/.codebuddy/mcp.json. The globalStorage path
  // that its docs mention is NOT read by this build (registering there does nothing).
  list.push(path.join(home, ".codebuddy", "mcp.json"));

  if (process.platform === "win32") {
    const roaming = process.env.APPDATA || path.join(home, "AppData", "Roaming");
    list.push(path.join(roaming, "CodeBuddy CN", ...REL));
  } else if (process.platform === "darwin") {
    list.push(path.join(home, "Library", "Application Support", "CodeBuddy CN", ...REL));
  } else {
    list.push(path.join(home, ".config", "CodeBuddy CN", ...REL));
  }

  list.push(path.join(home, ".cursor", "mcp.json"));
  list.push(path.join(home, ".codeium", "windsurf", "mcp_config.json"));
  list.push(path.join(process.cwd(), ".mcp.json"));
  return list;
}

function resolveSettings(argv) {
  const i = argv.indexOf("--settings");
  if (i >= 0 && argv[i + 1]) return argv[i + 1];
  if (process.env.MCP_SETTINGS) return process.env.MCP_SETTINGS;
  if (process.env.CODEBUDDY_MCP_SETTINGS) return process.env.CODEBUDDY_MCP_SETTINGS;
  for (const c of candidateSettings()) {
    if (existsSync(c)) return c;
  }
  return candidateSettings()[0];
}

// Strip --settings <path> out of the positional arguments.
function positionals(argv) {
  const out = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--settings") {
      i++;
      continue;
    }
    out.push(argv[i]);
  }
  return out;
}

const SETTINGS_PATH = resolveSettings(process.argv);
const [serverName, toolName, argsArg] = positionals(process.argv.slice(2));

if (!existsSync(SETTINGS_PATH)) {
  console.error("MCP settings file not found: " + SETTINGS_PATH);
  console.error("Pass --settings <path>, set MCP_SETTINGS, or check the auto-detect list:");
  for (const c of candidateSettings()) console.error("  " + c + (existsSync(c) ? "   <- exists" : ""));
  process.exit(2);
}

let servers;
try {
  servers = JSON.parse(readFileSync(SETTINGS_PATH, "utf8")).mcpServers ?? {};
} catch (e) {
  console.error("Could not parse " + SETTINGS_PATH + ": " + e.message);
  console.error("Hint: if a BOM sneaked in, rewrite the file as UTF-8 without BOM.");
  process.exit(2);
}

if (serverName === "--list-servers" || !serverName) {
  console.log("Settings: " + SETTINGS_PATH);
  console.log("Servers:");
  for (const [name, cfg] of Object.entries(servers)) {
    console.log("  " + name + "  ->  " + cfg.command + " " + (cfg.args ?? []).join(" "));
  }
  process.exit(0);
}

if (!toolName) {
  console.error("usage: node scripts/mcp_call.mjs <serverName> <toolName> [argsFileOrInlineJson]");
  process.exit(2);
}

const cfg = servers[serverName];
if (!cfg) {
  console.error("Server not in settings: " + serverName);
  console.error("Known: " + Object.keys(servers).join(", "));
  process.exit(2);
}

let toolArgs = {};
if (argsArg) {
  const raw = existsSync(argsArg) ? readFileSync(argsArg, "utf8") : argsArg;
  toolArgs = JSON.parse(raw);
}

const child = spawn(cfg.command, cfg.args ?? [], {
  env: { ...process.env, ...(cfg.env ?? {}) },
  stdio: ["pipe", "pipe", "pipe"],
});

let buf = "";
const pending = new Map();

child.stdout.on("data", (chunk) => {
  buf += chunk.toString();
  let idx;
  while ((idx = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, idx).trim();
    buf = buf.slice(idx + 1);
    if (!line) continue;
    try {
      const msg = JSON.parse(line);
      if (msg.id && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
      }
    } catch {
      /* not a JSON-RPC line */
    }
  }
});
child.stderr.on("data", (chunk) => process.stderr.write("[stderr] " + chunk.toString()));
child.on("exit", (code) => console.error("[server exited " + code + "]"));

let nextId = 1;
const rpc = (method, params) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, resolve);
    child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
    setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error("timeout waiting for " + method));
      }
    }, 300000);
  });

const main = async () => {
  await rpc("initialize", {
    protocolVersion: "2024-11-05",
    capabilities: {},
    clientInfo: { name: "mcp-call", version: "1.0.0" },
  });
  child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");

  const res = await rpc("tools/call", { name: toolName, arguments: toolArgs });
  for (const part of res.result?.content ?? []) {
    console.log(part.type === "text" ? part.text : JSON.stringify(part));
  }
  if (res.result?.isError) {
    console.error("TOOL RETURNED isError=true");
    child.kill();
    process.exit(1);
  }
  child.kill();
  process.exit(0);
};

main().catch((e) => {
  console.error("CALL FAILED: " + e.message);
  child.kill();
  process.exit(1);
});
