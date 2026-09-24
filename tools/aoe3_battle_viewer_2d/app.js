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
const pathingSetup = document.getElementById("pathing-setup");
const scenarioSelect = document.getElementById("pathing-scenario");
const showTrails = document.getElementById("show-trails");
const showRoutes = document.getElementById("show-routes");
const showTargets = document.getElementById("show-targets");
const iconCache = new Map();
const PROJECTILE_LIFETIME = 0.25;
const AOE_LIFETIME = 0.5;
const DEATH_MARK_LIFETIME = 0.6;

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
      if (unit.icon_url) {
        state.unitIcons.set(unit.id, unit.icon_url);
      }
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
  trails: new Map(),
  unitIcons: new Map(),
};

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const dpr = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.max(1, Math.floor(rect.width * dpr));
  const height = Math.max(1, Math.floor(rect.height * dpr));
  if (canvas.width === width && canvas.height === height) return;
  canvas.width = width;
  canvas.height = height;
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
    `有效伤害 ${Math.round(data.total_damage || 0)} · 原始 ${Math.round(data.total_raw_damage || 0)} · 过量 ${Math.round(data.total_overkill_damage || 0)}`;
  card.querySelector(".army-kills").textContent = `击杀 ${data.kills ?? 0}`;
}

function unitIcon(unit) {
  const unitId = unit.unit_id;
  if (!unitId) return null;
  const image = iconCache.get(unitId);
  if (!image) {
    const url = state.unitIcons.get(unitId);
    if (!url) return null;
    const pending = new Image();
    pending.decoding = "async";
    iconCache.set(unitId, pending);
    pending.onload = () => {
      if (!pending.complete || pending.naturalWidth <= 0) {
        iconCache.delete(unitId);
      }
    };
    pending.onerror = () => {
      iconCache.delete(unitId);
    };
    pending.src = url;
    return null;
  }
  return image.complete && image.naturalWidth > 0 ? image : null;
}

function activeEffects(frame, type) {
  const effects = frame.visual_events || [];
  const now = Number(frame.time || 0);
  return effects.filter(
    (effect) =>
      effect.type === type
      && now >= Number(effect.time || 0)
      && now <= Number(effect.expires_at || 0),
  );
}

function drawAttackEffects(frame) {
  const units = frame.units || [];
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  for (const effect of activeEffects(frame, "attack")) {
    const unit = byId.get(effect.attacker_id);
    const target = byId.get(effect.target_id);
    const fromWorld = unit || { x: effect.attacker_x, y: effect.attacker_y };
    const toWorld = target || { x: effect.x, y: effect.y };
    if (fromWorld.x == null || fromWorld.y == null || toWorld.x == null || toWorld.y == null) continue;
    const from = toScreen(fromWorld.x, fromWorld.y);
    const to = toScreen(toWorld.x, toWorld.y);
    const mode = effect.mode || "ranged";
    const progress = Math.max(
      0,
      Math.min(1, (Number(frame.time || 0) - Number(effect.time || 0)) / PROJECTILE_LIFETIME),
    );
    if (mode === "melee") {
      ctx.beginPath();
      ctx.strokeStyle = "rgba(216,207,186,0.8)";
      ctx.lineWidth = 2;
      const angle = Math.atan2(to.y - from.y, to.x - from.x);
      ctx.arc(from.x, from.y, 13, angle - 0.8, angle + 0.8);
      ctx.stroke();
    } else {
      const tip = { x: from.x + (to.x - from.x) * progress, y: from.y + (to.y - from.y) * progress };
      const tail = {
        x: from.x + (to.x - from.x) * Math.max(0, progress - 0.2),
        y: from.y + (to.y - from.y) * Math.max(0, progress - 0.2),
      };
      ctx.beginPath();
      ctx.strokeStyle = "rgba(235,225,190,0.9)";
      ctx.lineWidth = 2;
      ctx.moveTo(tail.x, tail.y);
      ctx.lineTo(tip.x, tip.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.fillStyle = "rgba(235,225,190,0.9)";
      ctx.arc(tip.x, tip.y, 2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

function drawAoeEffects(frame) {
  const drawnGroups = new Set();
  for (const effect of activeEffects(frame, "aoe")) {
    const groupId = effect.aoe_group_id || effect.event_id;
    if (drawnGroups.has(groupId)) continue;
    drawnGroups.add(groupId);
    if (effect.x == null || effect.y == null) continue;
    const progress = Math.max(
      0,
      Math.min(1, (Number(frame.time || 0) - Number(effect.time || 0)) / AOE_LIFETIME),
    );
    const point = toScreen(effect.x, effect.y);
    const radius = Math.max(
      6,
      Number(effect.radius || 2) * state.viewport.scale * (0.45 + progress * 0.55),
    );
    ctx.beginPath();
    ctx.fillStyle = `rgba(235,176,88,${0.12 * (1 - progress)})`;
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.beginPath();
    ctx.strokeStyle = `rgba(242,184,92,${0.95 - 0.35 * progress})`;
    ctx.lineWidth = 3;
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.stroke();
  }
}

function drawDeathMarks(frame) {
  for (const effect of activeEffects(frame, "death")) {
    if (effect.x == null || effect.y == null) continue;
    const progress = Math.max(
      0,
      Math.min(1, (Number(frame.time || 0) - Number(effect.time || 0)) / DEATH_MARK_LIFETIME),
    );
    const point = toScreen(effect.x, effect.y);
    ctx.beginPath();
    ctx.strokeStyle = `rgba(226,205,160,${0.75 * (1 - progress)})`;
    ctx.lineWidth = 2;
    ctx.moveTo(point.x - 5, point.y - 5);
    ctx.lineTo(point.x + 5, point.y + 5);
    ctx.moveTo(point.x - 5, point.y + 5);
    ctx.lineTo(point.x + 5, point.y - 5);
    ctx.stroke();
  }
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
  ctx.fillStyle = "#2d383b";
  ctx.fillRect(offsetX, offsetY, fieldWidth, fieldHeight);
  ctx.strokeStyle = "#3a474b";
  ctx.lineWidth = 1;
  ctx.strokeRect(offsetX + 0.5, offsetY + 0.5, fieldWidth - 1, fieldHeight - 1);

  const units = frame.units || [];
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  if (showTargets.checked) {
    ctx.lineWidth = 0.75;
    for (const unit of units) {
      const targetId = unit.target_id;
      const target = targetId ? byId.get(targetId) : null;
      if (!target) continue;
      const from = toScreen(unit.x, unit.y);
      const to = toScreen(target.x, target.y);
      ctx.strokeStyle = unit.side === "red" ? "rgba(239,83,80,0.14)" : "rgba(76,141,255,0.14)";
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
    }
  }
  drawAttackEffects(frame);
  drawAoeEffects(frame);
  drawDeathMarks(frame);

  for (const unit of units) {
    const selected = unit.id === state.selectedUnitId;
    if (showTrails.checked && (selected || frame.diagnostic)) {
      const samples = (state.trails.get(unit.id) || []).filter(
        (p) => p.index <= state.frameIndex && p.index >= state.frameIndex - 160,
      );
      ctx.strokeStyle = selected ? "#62d68b" : unit.side === "red" ? "#f09b81" : "#78b5ef";
      ctx.lineWidth = selected ? 2.2 : 1.4;
      ctx.beginPath();
      samples.forEach((sample, i) => {
        const p = toScreen(sample.x, sample.y);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      });
      ctx.stroke();
    }
    if (showRoutes.checked && unit.detour_path?.length) {
      const start = toScreen(unit.x, unit.y);
      ctx.strokeStyle = selected ? "#62d68b" : "#e8b95b";
      ctx.lineWidth = selected ? 2 : 1;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(start.x, start.y);
      for (const [x, y] of unit.detour_path) {
        const p = toScreen(x, y);
        ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      for (const [x, y] of unit.detour_path) {
        const p = toScreen(x, y);
        ctx.strokeRect(p.x - 3, p.y - 3, 6, 6);
      }
    }
  }

  for (const unit of units) {
    const radius = Math.max(4, Math.min(32, Math.round((unit.radius || 0.46) * scale)));
    const point = toScreen(unit.x, unit.y);
    const hpRatio = unit.max_hp > 0 ? unit.hp / unit.max_hp : 0;
    const color = unit.unit_id === "pathing_wall" ? "#899a90" : unit.side === "red" ? "#ef5350" : "#4c8dff";
    const icon = unitIcon(unit);

    ctx.beginPath();
    if (icon) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      ctx.clip();
      ctx.globalAlpha = 0.42 + hpRatio * 0.58;
      ctx.drawImage(icon, point.x - radius, point.y - radius, radius * 2, radius * 2);
      ctx.restore();
    } else {
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.42 + hpRatio * 0.58;
      ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.arc(point.x, point.y, radius + 1, 0, Math.PI * 2);
    ctx.stroke();

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

  if (frame.status === "error") {
    setStatus(`模拟失败：${frame.error || "未知错误"}`, "finished");
  } else if (frame.diagnostic) {
    setStatus(`${frame.status === "finished" ? "检验结束" : "检验中"} · 越过障碍 ${frame.diagnostic.reached}/${frame.diagnostic.total}`, frame.status);
  } else if (frame.status === "finished") {
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
  const preparation = unit.prepared_mode === "melee" ? "近战" : unit.prepared_mode === "ranged" ? "远程" : "未准备";
  const actionState = unit.stopped
    ? Number(unit.aim_cd || 0) > 0 ? "抬手准备" : Number(unit.attack_cd || 0) > 0 ? "等待 ROF" : "准备出手"
    : unit.steer_reason === "minimum_range" ? "最小射程内待命"
      : unit.prepared_mode ? "保持准备姿态" : "移动中";
  unitDetail.innerHTML = `
    <dl class="detail-grid">
      <dt>编号</dt><dd>#${unit.id}</dd>
      <dt>阵营</dt><dd>${unit.side === "red" ? "红方" : "蓝方"}</dd>
      <dt>兵种</dt><dd>${escapeHtml(unit.name)}</dd>
      <dt>HP</dt><dd>${unit.hp} / ${unit.max_hp}</dd>
      <dt>状态</dt><dd>${actionState}</dd>
      <dt>ROF 剩余</dt><dd>${Number(unit.attack_cd || 0).toFixed(2)} s</dd>
      <dt>抬手剩余</dt><dd>${unit.aim_cd == null ? "未准备" : `${Number(unit.aim_cd).toFixed(2)} s`}</dd>
      <dt>准备方式</dt><dd>${preparation}</dd>
      <dt>近战射程</dt><dd>${unit.has_melee ? unit.melee_range ?? "—" : "无"}</dd>
      <dt>远程射程</dt><dd>${unit.has_ranged ? `${unit.ranged_range_min ?? 0} – ${unit.ranged_range ?? "—"}` : "无"}</dd>
      <dt>转向</dt><dd>${escapeHtml(unit.steer_reason || "—")}</dd>
      <dt>攻击目标</dt><dd>${unit.target_id ?? "—"}</dd>
      <dt>移动目标</dt><dd>${unit.move_target_id ?? "—"}</dd>
      <dt>无进展</dt><dd>${unit.no_progress_ticks} tick</dd>
      <dt>绕行选择</dt><dd>${unit.detour_path?.length ? `${unit.detour_sign > 0 ? "正侧" : "负侧"} · ${unit.detour_path.length} 路点` : "无"}</dd>
      <dt>实际位置</dt><dd>${unit.x.toFixed(2)}, ${unit.y.toFixed(2)}</dd>
      <dt>有效伤害</dt><dd>${unit.damage}</dd>
      <dt>原始伤害</dt><dd>${unit.raw_damage ?? "—"}</dd>
      <dt>过量伤害</dt><dd>${unit.overkill_damage ?? "—"}</dd>
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
    timeLabel.textContent =
      `第 ${state.frameIndex + 1} / ${state.frames.length} 帧 · `
      + `t = ${Number(frame.time || 0).toFixed(1)}s`;
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

async function fillFrames(generation) {
  while (state.frames.length < state.remoteCount) {
    const frame = await fetchFrame(state.frames.length);
    if (generation !== state.generation) return;
    if (!frame) break;
    for (const unit of frame.units || []) {
      unitIcon(unit);
      if (!state.trails.has(unit.id)) state.trails.set(unit.id, []);
      state.trails.get(unit.id).push({ x: unit.x, y: unit.y, index: state.frames.length });
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
    await fillFrames(generation);
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
  pathingSetup.classList.toggle("hidden", mode !== "pathing");
  setupRowMain.classList.toggle("civ-war-row", mode === "civ_war");
}

async function restartSimulation() {
  const collisionMode = collisionModeSelect.value;
  const payload =
    state.mode === "pathing"
      ? { mode: "pathing", scenario: scenarioSelect.value, seed: Number(seedInput.value), collision_mode: collisionMode }
      : state.mode === "civ_war"
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
  state.generation += 1;
  state.fetchInFlight = true;
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
    state.trails.clear();
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
    state.fetchInFlight = false;
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
  const scenario = new URLSearchParams(location.search).get("scenario");
  if (Array.from(scenarioSelect.options).some(option => option.value === scenario)) {
    setMode("pathing");
    scenarioSelect.value = scenario;
  }
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
