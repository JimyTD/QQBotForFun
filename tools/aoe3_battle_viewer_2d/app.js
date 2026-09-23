const canvas = document.getElementById("battlefield");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const timeLabel = document.getElementById("time-label");
const metrics = {
  tick: document.getElementById("metric-tick"),
  alive: document.getElementById("metric-alive"),
  movers: document.getElementById("metric-movers"),
  blocked: document.getElementById("metric-blocked"),
  noProgress: document.getElementById("metric-no-progress"),
  overlap: document.getElementById("metric-overlap"),
};
const unitDetail = document.getElementById("unit-detail");
const timeline = document.getElementById("timeline");
const speedSelect = document.getElementById("speed");
const pauseButton = document.getElementById("pause");
const liveButton = document.getElementById("live");
const stepBackButton = document.getElementById("step-back");
const stepForwardButton = document.getElementById("step-forward");
const armyCards = {
  red: document.getElementById("army-red"),
  blue: document.getElementById("army-blue"),
};
const matchLabel = document.getElementById("match-label");
const restartButton = document.getElementById("restart");
const unitOptions = document.getElementById("unit-options");
const redUnitInput = document.getElementById("red-unit");
const blueUnitInput = document.getElementById("blue-unit");
const redCountInput = document.getElementById("red-count");
const blueCountInput = document.getElementById("blue-count");
const redCivSelect = document.getElementById("red-civ");
const blueCivSelect = document.getElementById("blue-civ");
const ageSelect = document.getElementById("age");
const seedInput = document.getElementById("seed");
const collisionModeSelect = document.getElementById("collision-mode");
const unitsSetup = document.getElementById("units-setup");
const civWarSetup = document.getElementById("civ-war-setup");
const setupRowMain = document.querySelector(".setup-row-main");

const FALLBACK_CIVS = [
  ["British", "英国"],
  ["Chinese", "中国"],
  ["DEAmericans", "美国"],
  ["DEDanish", "丹麦"],
  ["DEEthiopians", "埃塞俄比亚"],
  ["DEHausa", "豪萨"],
  ["DEInca", "印加"],
  ["DEItalians", "意大利"],
  ["DEMaltese", "马耳他"],
  ["DEMexicans", "墨西哥"],
  ["DEPolish", "波兰"],
  ["DESwedish", "瑞典"],
  ["Dutch", "荷兰"],
  ["French", "法国"],
  ["Germans", "德国"],
  ["Indians", "印度"],
  ["Japanese", "日本"],
  ["Ottomans", "奥斯曼"],
  ["Portuguese", "葡萄牙"],
  ["Russians", "俄罗斯"],
  ["Spanish", "西班牙"],
  ["XPAztec", "阿兹特克"],
  ["XPIroquois", "豪德诺索尼"],
  ["XPSioux", "拉科塔"],
].map(([id, name]) => ({ id, name, name_en: id }));

function populateCivSelects(civs) {
  const values = civs.length ? civs : FALLBACK_CIVS;
  for (const select of [redCivSelect, blueCivSelect]) {
    select.innerHTML = "";
    for (const civ of values) {
      const option = document.createElement("option");
      option.value = civ.id;
      option.textContent = `${civ.name} · ${civ.name_en}`;
      select.appendChild(option);
    }
  }
  redCivSelect.value = values[0].id;
  blueCivSelect.value = values[1].id;
}

async function bootstrapCatalog() {
  try {
    const response = await fetch("/api/catalog", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`catalog HTTP ${response.status}`);
    }
    const catalog = await response.json();
    state.catalog = catalog;
    unitOptions.innerHTML = "";
    for (const unit of catalog.units || []) {
      const option = document.createElement("option");
      option.value = unit.id;
      option.label = `${unit.name} · ${unit.name_en}`;
      unitOptions.appendChild(option);
    }
    populateCivSelects(catalog.civs || []);
    setStatus("阵容选择已加载", "running");
  } catch (error) {
    setStatus(`目录加载失败：${error.message}`, "finished");
  }
}

const state = {
  frames: [],
  remoteCount: 0,
  frameIndex: 0,
  fetchInFlight: false,
  generation: 0,
  playing: true,
  speed: 1,
  elapsedAccumulator: 0,
  lastAnimationTime: performance.now(),
  selectedUnitId: null,
  viewport: { width: 0, height: 0, scale: 1, offsetX: 0, offsetY: 0 },
  mode: "units",
  catalog: { units: [], civs: [] },
};

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function currentFrame() {
  return state.frames[state.frameIndex] || null;
}

function updateViewport(frame) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  const fieldWidth = Math.max(1, frame?.field?.width || 1);
  const fieldHeight = Math.max(1, frame?.field?.height || 1);
  const padding = 26;
  const scale = Math.min(
    (width - padding * 2) / fieldWidth,
    (height - padding * 2) / fieldHeight,
  );
  const drawWidth = fieldWidth * scale;
  const drawHeight = fieldHeight * scale;
  state.viewport = {
    width,
    height,
    scale,
    offsetX: (width - drawWidth) / 2,
    offsetY: (height - drawHeight) / 2,
  };
}

function toScreen(x, y) {
  return {
    x: state.viewport.offsetX + x * state.viewport.scale,
    y: state.viewport.offsetY + y * state.viewport.scale,
  };
}

function toWorld(clientX, clientY) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.viewport.offsetX) / state.viewport.scale,
    y: (clientY - rect.top - state.viewport.offsetY) / state.viewport.scale,
  };
}

function setStatus(text, className = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${className}`.trim();
}

function renderArmyCard(side, data) {
  const card = armyCards[side];
  if (!card || !data) return;
  const composition = (data.composition || [])
    .map((item) => `${item.name}×${item.count}`)
    .join(" + ");
  const ratio = Math.max(0, Math.min(1, Number(data.hp_ratio || 0)));
  card.querySelector(".army-alive").textContent =
    `${data.alive ?? 0} / ${data.initial_count ?? 0}`;
  card.querySelector(".army-composition").textContent =
    composition || "无单位";
  card.querySelector(".hp-track i").style.width = `${ratio * 100}%`;
  card.querySelector(".hp-ratio").textContent = `${Math.round(ratio * 100)}%`;
  card.querySelector(".army-moving").textContent = `移动 ${data.moving ?? 0}`;
  card.querySelector(".army-stopped").textContent = `停止 ${data.stopped ?? 0}`;
  card.querySelector(".army-damage").textContent =
    `伤害 ${Math.round(data.total_damage || 0)}`;
  card.querySelector(".army-kills").textContent = `击杀 ${data.kills ?? 0}`;
}

function drawFrame(frame) {
  const { width, height, scale, offsetX, offsetY } = state.viewport;
  ctx.clearRect(0, 0, width, height);
  if (!frame) {
    setStatus("等待模拟数据…");
    return;
  }

  const fieldWidth = frame.field.width * scale;
  const fieldHeight = frame.field.height * scale;
  ctx.fillStyle = "#111a15";
  ctx.fillRect(offsetX, offsetY, fieldWidth, fieldHeight);
  ctx.strokeStyle = "#435248";
  ctx.lineWidth = 1;
  ctx.strokeRect(offsetX + 0.5, offsetY + 0.5, fieldWidth - 1, fieldHeight - 1);

  const units = frame.units || [];
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  const attackTargets = [];

  for (const unit of units) {
    const targetId = unit.target_id || unit.move_target_id;
    const target = targetId ? byId.get(targetId) : null;
    if (!target) continue;
    attackTargets.push({ unit, target });
  }

  ctx.lineWidth = 0.75;
  for (const { unit, target } of attackTargets) {
    const from = toScreen(unit.x, unit.y);
    const to = toScreen(target.x, target.y);
    ctx.strokeStyle =
      unit.target_id != null
        ? unit.side === "red"
          ? "rgba(239,83,80,0.20)"
          : "rgba(76,141,255,0.20)"
        : unit.side === "red"
          ? "rgba(239,83,80,0.08)"
          : "rgba(76,141,255,0.08)";
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
  }

  const radius = Math.max(2.3, 0.46 * scale);
  for (const unit of units) {
    const point = toScreen(unit.x, unit.y);
    const hpRatio = unit.max_hp > 0 ? unit.hp / unit.max_hp : 0;
    const color = unit.side === "red" ? "#ef5350" : "#4c8dff";

    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.42 + hpRatio * 0.58;
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 1;

    ctx.beginPath();
    ctx.strokeStyle = unit.stopped ? "#eef4f0" : "rgba(238,244,240,0.34)";
    ctx.lineWidth = unit.stopped ? 1.15 : 0.8;
    if (!unit.stopped) ctx.setLineDash([2, 2]);
    ctx.arc(point.x, point.y, radius + 1.4, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    if (unit.id === state.selectedUnitId) {
      ctx.beginPath();
      ctx.strokeStyle = "#62d68b";
      ctx.lineWidth = 2;
      ctx.arc(point.x, point.y, radius + 4.5, 0, Math.PI * 2);
      ctx.stroke();
    }

    if (unit.has_ranged && !unit.has_melee) {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(255,255,255,0.62)";
      ctx.lineWidth = 1;
      ctx.arc(point.x, point.y, radius * 0.36, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  const summary = frame.summary || {};
  matchLabel.textContent = frame.match_label || "二维战场";
  renderArmyCard("red", frame.sides?.red);
  renderArmyCard("blue", frame.sides?.blue);
  timeLabel.textContent = `t = ${Number(frame.time || 0).toFixed(1)}s`;
  metrics.tick.textContent = frame.tick;
  metrics.alive.textContent = `${summary.alive_red ?? 0} / ${summary.alive_blue ?? 0}`;
  metrics.movers.textContent = summary.movers ?? "—";
  metrics.blocked.textContent = summary.blocked ?? "—";
  metrics.noProgress.textContent = summary.no_progress_units ?? "—";
  metrics.overlap.textContent = Number(summary.max_overlap || 0).toFixed(3);

  if (frame.status === "finished") {
    const winner = frame.winner === "red" ? "红方胜利" : frame.winner === "blue" ? "蓝方胜利" : "平局";
    setStatus(`已结束 · ${winner}`, "finished");
  } else {
    setStatus(`模拟中 · ${summary.attackers || 0} 个单位正在攻击`, "running");
  }

  if (state.selectedUnitId != null) {
    renderUnitDetail(byId.get(state.selectedUnitId));
  }
}

function renderUnitDetail(unit) {
  if (!unit) {
    unitDetail.className = "empty";
    unitDetail.textContent = "选中单位已不在场上";
    return;
  }
  unitDetail.className = "";
  unitDetail.innerHTML = `
    <dl class="detail-grid">
      <dt>编号</dt><dd>#${unit.id}</dd>
      <dt>阵营</dt><dd>${unit.side === "red" ? "红方" : "蓝方"}</dd>
      <dt>兵种</dt><dd>${escapeHtml(unit.name)}</dd>
      <dt>HP</dt><dd>${unit.hp} / ${unit.max_hp}</dd>
      <dt>状态</dt><dd>${unit.stopped ? "停止攻击" : "移动中"}</dd>
      <dt>转向</dt><dd>${escapeHtml(unit.steer_reason || "—")}</dd>
      <dt>攻击目标</dt><dd>${unit.target_id ?? "—"}</dd>
      <dt>移动目标</dt><dd>${unit.move_target_id ?? "—"}</dd>
      <dt>无进展</dt><dd>${unit.no_progress_ticks} tick</dd>
      <dt>伤害</dt><dd>${unit.damage}</dd>
      <dt>击杀</dt><dd>${unit.kills}</dd>
    </dl>
  `;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function updateTimeline(frame) {
  const max = Math.max(0, state.frames.length - 1);
  timeline.max = String(max);
  timeline.value = String(Math.min(state.frameIndex, max));
  timeline.disabled = max === 0;
  if (frame) {
    timeLabel.textContent = `t = ${Number(frame.time || 0).toFixed(1)}s`;
  }
}

function setPlaying(playing) {
  state.playing = playing;
  pauseButton.textContent = playing ? "暂停" : "播放";
  liveButton.classList.toggle("active", playing);
  timeline.disabled = playing || state.frames.length <= 1;
}

function selectAt(clientX, clientY) {
  const frame = currentFrame();
  if (!frame) return;
  const world = toWorld(clientX, clientY);
  let best = null;
  let bestDistance = Infinity;
  for (const unit of frame.units || []) {
    const distance = Math.hypot(unit.x - world.x, unit.y - world.y);
    if (distance < bestDistance) {
      best = unit;
      bestDistance = distance;
    }
  }
  if (best && bestDistance <= 1.1) {
    state.selectedUnitId = best.id;
    renderUnitDetail(best);
  } else {
    state.selectedUnitId = null;
    unitDetail.className = "empty";
    unitDetail.textContent = "点击战场单位查看详情";
  }
}

async function fetchFrame(index) {
  try {
    const response = await fetch(`/api/frame?index=${index}`, { cache: "no-store" });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  }
}

async function fillFrames() {
  while (state.frames.length < state.remoteCount) {
    const frame = await fetchFrame(state.frames.length);
    if (!frame) break;
    if (frame.tick !== state.frames.length) {
      break;
    }
    state.frames.push(frame);
  }
  if (state.playing) {
    // Never seek ahead when new frames arrive.  A monotonic cursor prevents
    // the timeline from jumping backwards or skipping death frames.
    state.frameIndex = Math.min(
      state.frameIndex,
      state.frames.length - 1,
    );
  }
  state.frameIndex = Math.min(state.frameIndex, state.frames.length - 1);
  updateTimeline(currentFrame());
}

async function refreshMeta() {
  if (state.fetchInFlight) return;
  state.fetchInFlight = true;
  const generation = state.generation;
  try {
    const response = await fetch("/api/meta", { cache: "no-store" });
    const meta = await response.json();
    if (generation !== state.generation) return;
    state.remoteCount = Number(meta.frames || 0);
    await fillFrames();
  } catch {
    setStatus("等待本地模拟服务…");
  } finally {
    if (generation === state.generation) {
      state.fetchInFlight = false;
    }
  }
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  unitsSetup.classList.toggle("hidden", mode !== "units");
  civWarSetup.classList.toggle("hidden", mode !== "civ_war");
  setupRowMain.classList.toggle("civ-war-row", mode === "civ_war");
}

async function restartSimulation() {
  const collisionMode = collisionModeSelect.value;
  const payload =
    state.mode === "civ_war"
      ? {
          mode: "civ_war",
          red_civ: redCivSelect.value,
          blue_civ: blueCivSelect.value,
          age: Number(ageSelect.value),
          seed: Number(seedInput.value),
          collision_mode: collisionMode,
        }
      : {
          mode: "units",
          red: `${redUnitInput.value.trim()}:${Number(redCountInput.value)}`,
          blue: `${blueUnitInput.value.trim()}:${Number(blueCountInput.value)}`,
          seed: Number(seedInput.value),
          collision_mode: collisionMode,
        };
  restartButton.disabled = true;
  restartButton.textContent = "准备中…";
  try {
    if (
      state.mode === "civ_war"
      && redCivSelect.value === blueCivSelect.value
    ) {
      throw new Error("红方和蓝方必须选择不同文明");
    }
    const response = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) {
      throw new Error(result.error || "start failed");
    }
    state.frames = [];
    state.frameIndex = 0;
    state.remoteCount = 0;
    state.generation += 1;
    state.fetchInFlight = false;
    state.elapsedAccumulator = 0;
    state.selectedUnitId = null;
    setPlaying(true);
    await refreshMeta();
  } catch (error) {
    setStatus(`启动失败：${error.message}`, "finished");
  } finally {
    restartButton.disabled = false;
    restartButton.textContent = "重新模拟";
  }
}

function animationLoop(now) {
  resizeCanvas();
  const delta = Math.min(250, now - state.lastAnimationTime);
  state.lastAnimationTime = now;
  const frameIntervalMs = 100;
  if (state.playing && state.frames.length > 1) {
    state.elapsedAccumulator += delta * state.speed;
    while (state.elapsedAccumulator >= frameIntervalMs) {
      state.elapsedAccumulator -= frameIntervalMs;
      state.frameIndex = Math.min(
        state.frameIndex + 1,
        state.frames.length - 1,
      );
    }
    updateTimeline(currentFrame());
  }
  const frame = currentFrame();
  updateViewport(frame);
  drawFrame(frame);
  requestAnimationFrame(animationLoop);
}

pauseButton.addEventListener("click", () => setPlaying(!state.playing));
liveButton.addEventListener("click", () => {
  setPlaying(true);
  state.frameIndex = Math.max(0, state.frames.length - 1);
  state.elapsedAccumulator = 0;
});
stepBackButton.addEventListener("click", () => {
  setPlaying(false);
  state.frameIndex = Math.max(0, state.frameIndex - 1);
  updateTimeline();
});
stepForwardButton.addEventListener("click", () => {
  setPlaying(false);
  state.frameIndex = Math.min(state.frames.length - 1, state.frameIndex + 1);
  updateTimeline();
});
speedSelect.addEventListener("change", () => {
  state.speed = Number(speedSelect.value) || 1;
});
timeline.addEventListener("input", () => {
  setPlaying(false);
  state.frameIndex = Number(timeline.value);
  updateTimeline(state.frames[state.frameIndex]);
});
canvas.addEventListener("click", (event) => {
  selectAt(event.clientX, event.clientY);
});
window.addEventListener("resize", resizeCanvas);
document.querySelectorAll(".mode-tab").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
restartButton.addEventListener("click", restartSimulation);
redCivSelect.addEventListener("change", () => {
  if (redCivSelect.value === blueCivSelect.value) {
    blueCivSelect.value =
      state.catalog.civs.find((civ) => civ.id !== redCivSelect.value)?.id || "";
  }
});
blueCivSelect.addEventListener("change", () => {
  if (blueCivSelect.value === redCivSelect.value) {
    redCivSelect.value =
      state.catalog.civs.find((civ) => civ.id !== blueCivSelect.value)?.id || "";
  }
});

let bootstrapped = false;

function bootViewer() {
  if (bootstrapped) return;
  bootstrapped = true;
  populateCivSelects(FALLBACK_CIVS);
  setInterval(refreshMeta, 180);
  bootstrapCatalog().then(() => {
    refreshMeta();
    requestAnimationFrame(animationLoop);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootViewer, { once: true });
} else {
  bootViewer();
}
