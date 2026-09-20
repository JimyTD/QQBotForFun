#!/usr/bin/env node
/**
 * CLI bridge: call any MCP server registered in CodeBuddy's settings, without the IDE.
 *
 * Why this exists: an agent session snapshots its MCP tool list at startup, so a server
 * registered mid-session shows up as "not found or not connected" even though the config
 * is perfectly valid. This bridge talks MCP over stdio directly, so onboarding and
 * bootstrapping do not have to wait for an IDE restart.
 *
 * Credentials are read from the CodeBuddy settings file, so nothing is duplicated.
 *
 * Usage:
 *   node scripts/mcp_call.mjs <serverName> <toolName> [argsFileOrInlineJson]
 *   node scripts/mcp_call.mjs --list-servers
 *
 * Settings file discovery:
 *   $CODEBUDDY_MCP_SETTINGS, else the platform default for CodeBuddy CN.
 */
import { spawn } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

function defaultSettingsPath() {
  if (process.env.CODEBUDDY_MCP_SETTINGS) return process.env.CODEBUDDY_MCP_SETTINGS;
  const rel = path.join(
    "User",
    "globalStorage",
    "tencent.planning-genie",
    "settings",
    "codebuddy_mcp_settings.json",
  );
  if (process.platform === "win32") {
    const base = process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
    return path.join(base, "CodeBuddy CN", rel);
  }
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "CodeBuddy CN", rel);
  }
  return path.join(os.homedir(), ".config", "CodeBuddy CN", rel);
}

const SETTINGS_PATH = defaultSettingsPath();

if (!existsSync(SETTINGS_PATH)) {
  console.error("CodeBuddy MCP settings not found: " + SETTINGS_PATH);
  console.error("Set CODEBUDDY_MCP_SETTINGS to point at it explicitly.");
  process.exit(2);
}

const servers = JSON.parse(readFileSync(SETTINGS_PATH, "utf8")).mcpServers ?? {};

const [serverName, toolName, argsArg] = process.argv.slice(2);

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
