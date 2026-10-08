const canvas = document.getElementById("battlefield");
const ctx = canvas.getContext("2d");
const statusEl = document.getElementById("status");
const timeLabel = document.getElementById("time-label");
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
const unitsSetup = document.getElementById("units-setup");
const customSetup = document.getElementById("custom-setup");
const civWarSetup = document.getElementById("civ-war-setup");
const balanceBlue = document.getElementById("balance-blue");
const showTrails = document.getElementById("show-trails");
const showTargets = document.getElementById("show-targets");
const showCharge = document.getElementById("show-charge");
const chargeOnly = document.getElementById("charge-only");
const attackLog = document.getElementById("attack-log");
const iconCache = new Map();
const PROJECTILE_LIFETIME = 0.25;
const AOE_LIFETIME = 0.5;
const DEATH_MARK_LIFETIME = 0.6;
const CHARGE_COLOR = "#f2c14e";

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
  mode: "custom",
  catalog: { units: [], civs: [] },
  trails: new Map(),
  unitIcons: new Map(),
  custom: {
    red: { civ: null, units: [], counts: [], techs: new Set(), available: null, age: 3 },
    blue: { civ: null, units: [], counts: [], techs: new Set(), available: null, age: 3 },
  },
  attackEvents: [],
  seenEvents: new Set(),
};

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
  state.custom.red.civ = values[0].id;
  state.custom.blue.civ = values[1].id;
  document.querySelectorAll(".civ-select").forEach((select) => {
    select.innerHTML = "";
    for (const civ of values) {
      const option = document.createElement("option");
      option.value = civ.id;
      option.textContent = civ.name;
      select.appendChild(option);
    }
  });
  const redSelect = document.querySelector('.civ-select[data-side="red"]');
  const blueSelect = document.querySelector('.civ-select[data-side="blue"]');
  if (redSelect) redSelect.value = state.custom.red.civ;
  if (blueSelect) blueSelect.value = state.custom.blue.civ;
}

async function bootstrapCatalog() {
  try {
    const response = await fetch("/api/catalog", { cache: "no-store" });
    if (!response.ok) throw new Error(`catalog HTTP ${response.status}`);
    const catalog = await response.json();
    state.catalog = catalog;
    unitOptions.innerHTML = "";
    for (const unit of catalog.units || []) {
      const option = document.createElement("option");
      option.value = unit.id;
      option.label = `${unit.name} · ${unit.name_en}`;
      unitOptions.appendChild(option);
      if (unit.icon_url) state.unitIcons.set(unit.id, unit.icon_url);
    }
    populateCivSelects(catalog.civs || []);
    await refreshLoadout("red");
    await refreshLoadout("blue");
    setStatus("阵容选择已加载", "running");
  } catch (error) {
    setStatus(`目录加载失败：${error.message}`, "finished");
  }
}

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
  card.querySelector(".army-composition").textContent = composition || "无单位";
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
      if (!pending.complete || pending.naturalWidth <= 0) iconCache.delete(unitId);
    };
    pending.onerror = () => iconCache.delete(unitId);
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
    if (fromWorld.x == null || toWorld.x == null) continue;
    const from = toScreen(fromWorld.x, fromWorld.y);
    const to = toScreen(toWorld.x, toWorld.y);
    const mode = effect.mode || "ranged";
    const isCharge = Boolean(effect.action_charge);
    const progress = Math.max(
      0,
      Math.min(1, (Number(frame.time || 0) - Number(effect.time || 0)) / PROJECTILE_LIFETIME),
    );
    if (mode === "melee") {
      ctx.beginPath();
      ctx.strokeStyle = isCharge ? CHARGE_COLOR : "rgba(216,207,186,0.8)";
      ctx.lineWidth = isCharge ? 3 : 2;
      const angle = Math.atan2(to.y - from.y, to.x - from.x);
      ctx.arc(from.x, from.y, isCharge ? 17 : 13, angle - 0.8, angle + 0.8);
      ctx.stroke();
    } else {
      const tip = {
        x: from.x + (to.x - from.x) * progress,
        y: from.y + (to.y - from.y) * progress,
      };
      const tail = {
        x: from.x + (to.x - from.x) * Math.max(0, progress - 0.2),
        y: from.y + (to.y - from.y) * Math.max(0, progress - 0.2),
      };
      ctx.beginPath();
      ctx.strokeStyle = isCharge ? CHARGE_COLOR : "rgba(235,225,190,0.9)";
      ctx.lineWidth = isCharge ? 3 : 2;
      ctx.moveTo(tail.x, tail.y);
      ctx.lineTo(tip.x, tip.y);
      ctx.stroke();
      ctx.beginPath();
      ctx.fillStyle = isCharge ? CHARGE_COLOR : "rgba(235,225,190,0.9)";
      ctx.arc(tip.x, tip.y, isCharge ? 3 : 2, 0, Math.PI * 2);
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

function drawChargeRing(unit, point, radius) {
  const charge = unit.charge;
  if (!charge) return;
  const ready = Boolean(charge.ready);
  const ratio = Math.max(0, Math.min(1, Number(charge.ratio || 0)));
  ctx.beginPath();
  ctx.strokeStyle = ready ? CHARGE_COLOR : "rgba(242,193,78,0.35)";
  ctx.lineWidth = ready ? 2.5 : 2;
  ctx.arc(point.x, point.y, radius + 4, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * ratio);
  ctx.stroke();
}

function collectAttackEvents(frame) {
  const units = frame.units || [];
  const byId = new Map(units.map((unit) => [unit.id, unit]));
  for (const effect of activeEffects(frame, "attack")) {
    const key = [
      effect.event_id,
      effect.attacker_id,
      effect.target_id,
      effect.time,
      effect.action_name,
    ].join(":");
    if (state.seenEvents.has(key)) continue;
    state.seenEvents.add(key);
    const attacker = byId.get(effect.attacker_id);
    state.attackEvents.unshift({
      time: Number(effect.time || 0),
      side: attacker?.side || "red",
      attacker: attacker?.name || `#${effect.attacker_id}`,
      action: effect.action_name || (effect.mode === "melee" ? "近战" : "远程"),
      charge: Boolean(effect.action_charge),
    });
    if (state.attackEvents.length > 60) state.attackEvents.pop();
  }
}

function renderAttackLog() {
  const rows = state.attackEvents.filter(
    (event) => !chargeOnly.checked || event.charge,
  );
  if (!rows.length) {
    attackLog.className = "attack-log empty";
    attackLog.textContent = chargeOnly.checked ? "暂无蓄力攻击…" : "等待攻击…";
    return;
  }
  attackLog.className = "attack-log";
  attackLog.innerHTML = rows
    .slice(0, 30)
    .map(
      (event) => `
      <div class="attack-log-row ${event.side} ${event.charge ? "charge" : ""}">
        <span class="who">${event.time.toFixed(1)}s</span>
        <span class="what">${escapeHtml(event.attacker)} · ${escapeHtml(event.action)}${event.charge ? " · 蓄力" : ""}</span>
      </div>`,
    )
    .join("");
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
      const target = unit.target_id ? byId.get(unit.target_id) : null;
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

  if (showTrails.checked) {
    for (const unit of units) {
      const selected = unit.id === state.selectedUnitId;
      if (!selected && !frame.diagnostic) continue;
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
  }

  for (const unit of units) {
    const radius = Math.max(4, Math.min(32, Math.round((unit.radius || 0.46) * scale)));
    const point = toScreen(unit.x, unit.y);
    const hpRatio = unit.max_hp > 0 ? unit.hp / unit.max_hp : 0;
    const color = unit.side === "red" ? "#ef5350" : "#4c8dff";
    const icon = unitIcon(unit);

    if (icon) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
      ctx.clip();
      ctx.globalAlpha = 0.42 + hpRatio * 0.58;
      ctx.drawImage(icon, point.x - radius, point.y - radius, radius * 2, radius * 2);
      ctx.restore();
    } else {
      ctx.beginPath();
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

    if (showCharge.checked) drawChargeRing(unit, point, radius);

    if (unit.id === state.selectedUnitId) {
      ctx.beginPath();
      ctx.strokeStyle = "#62d68b";
      ctx.lineWidth = 2;
      ctx.arc(point.x, point.y, radius + 4.5, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  const summary = frame.summary || {};
  matchLabel.textContent = frame.match_label || "二维战场";
  renderArmyCard("red", frame.sides?.red);
  renderArmyCard("blue", frame.sides?.blue);
  timeLabel.textContent = `t = ${Number(frame.time || 0).toFixed(1)}s`;
  collectAttackEvents(frame);
  renderAttackLog();

  if (frame.status === "error") {
    setStatus(`模拟失败：${frame.error || "未知错误"}`, "finished");
  } else if (frame.status === "finished") {
    const winner = frame.winner === "red" ? "红方胜利" : frame.winner === "blue" ? "蓝方胜利" : "平局";
    setStatus(`已结束 · ${winner}`, "finished");
  } else {
    setStatus(`模拟中 · ${summary.attackers || 0} 个单位正在攻击`, "running");
  }

  if (state.selectedUnitId != null) renderUnitDetail(byId.get(state.selectedUnitId), frame);
}

function renderUnitDetail(unit, frame) {
  if (!unit) {
    unitDetail.className = "empty";
    unitDetail.textContent = "选中单位已不在场上";
    return;
  }
  unitDetail.className = "";
  const preparation = unit.prepared_mode === "melee"
    ? "近战"
    : unit.prepared_mode === "ranged" ? "远程" : "未准备";
  const actionState = unit.stopped
    ? Number(unit.aim_cd || 0) > 0
      ? "抬手准备"
      : Number(unit.attack_cd || 0) > 0 ? "等待 ROF" : "准备出手"
    : unit.steer_reason === "minimum_range" ? "最小射程内待命"
      : unit.prepared_mode ? "保持准备姿态" : "移动中";
  const template = frame?.unit_templates?.[unit.unit_id];
  const charge = unit.charge;
  const chargeLine = charge
    ? `<div class="detail-sub">蓄力：${escapeHtml(charge.name)} · ${
        charge.ready ? "就绪" : `冷却 ${Number(charge.remaining).toFixed(1)}s`
      }</div>
      <div class="charge-bar"><i style="width:${Math.round((charge.ratio || 0) * 100)}%"></i></div>`
    : "";
  const modes = (template?.attacks || [])
    .filter((action) => action.enabled)
    .map(
      (action) => `
      <div class="mode-row ${action.charge ? "charge" : ""}">
        <span class="mode-name">${escapeHtml(action.name)}</span>
        <span class="mode-tag ${action.charge ? "charge" : ""}">${
          action.charge ? "蓄力" : action.damage_type || "—"
        }</span>
        <span class="mode-name">${action.damage} 伤 · ${action.range_min}–${action.range_max} · ${action.rof}s</span>
        <span class="mode-tag">优先级 ${action.priority}</span>
      </div>`,
    )
    .join("");
  unitDetail.innerHTML = `
    <dl class="detail-grid">
      <dt>编号</dt><dd>#${unit.id}</dd>
      <dt>阵营</dt><dd>${unit.side === "red" ? "红方" : "蓝方"}</dd>
      <dt>兵种</dt><dd>${escapeHtml(unit.name)}</dd>
      <dt>HP</dt><dd>${unit.hp} / ${unit.max_hp}</dd>
      <dt>状态</dt><dd>${actionState}</dd>
      <dt>动作</dt><dd>${escapeHtml(unit.prepared_action_name || "—")}</dd>
      <dt>准备方式</dt><dd>${preparation}</dd>
      <dt>ROF 剩余</dt><dd>${Number(unit.attack_cd || 0).toFixed(2)} s</dd>
      <dt>抬手剩余</dt><dd>${unit.aim_cd == null ? "未准备" : `${Number(unit.aim_cd).toFixed(2)} s`}</dd>
      <dt>攻击目标</dt><dd>${unit.target_id ?? "—"}</dd>
      <dt>有效伤害</dt><dd>${unit.damage}</dd>
      <dt>击杀</dt><dd>${unit.kills}</dd>
    </dl>
    ${chargeLine}
    <div class="detail-sub">可用攻击模式（${(template?.attacks || []).filter((a) => a.enabled).length}）</div>
    <div class="mode-list">${modes || '<div class="tech-empty">无</div>'}</div>
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
      `第 ${state.frameIndex + 1} / ${state.frames.length} 帧 · t = ${Number(frame.time || 0).toFixed(1)}s`;
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
    renderUnitDetail(best, frame);
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
    if (generation === state.generation) state.fetchInFlight = false;
  }
}

function setMode(mode) {
  state.mode = mode;
  document.querySelectorAll(".mode-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === mode);
  });
  customSetup.classList.toggle("hidden", mode !== "custom");
  unitsSetup.classList.toggle("hidden", mode !== "units");
  civWarSetup.classList.toggle("hidden", mode !== "civ_war");
}

async function refreshLoadout(side) {
  const entry = state.custom[side];
  const civ = entry.civ;
  if (!civ) return;
  const units = entry.units.filter(Boolean).join(",");
  try {
    const response = await fetch(
      `/api/loadout?civ=${encodeURIComponent(civ)}&age=${entry.age}&units=${encodeURIComponent(units)}`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error("loadout failed");
    entry.available = await response.json();
    const validIds = new Set((entry.available.units || []).map((unit) => unit.id));
    entry.units = entry.units.filter((unitId) => validIds.has(unitId));
    if (!entry.units.length && entry.available.units?.length) {
      entry.units = [entry.available.units[0].id];
    }
    if (entry.counts.length !== entry.units.length) {
      entry.counts = entry.units.map((_id, index) => entry.counts[index] || 20);
    }
    if (!units && entry.units.length) {
      // The default unit was picked after this fetch; refetch with it so the
      // technology list reflects the actual lineup.
      await refreshLoadout(side);
      return;
    }
    renderCustomSide(side);
  } catch {
    entry.available = { units: [], techs: [] };
    renderCustomSide(side);
  }
}

function renderCustomSide(side) {
  const entry = state.custom[side];
  const container = document.querySelector(`.custom-units[data-side="${side}"]`);
  if (!container) return;
  const available = entry.available?.units || [];
  const maxUnits = 3;
  if (entry.units.length > maxUnits) entry.units = entry.units.slice(0, maxUnits);
  container.innerHTML = entry.units
    .map(
      (selectedId, index) => `
      <div class="unit-row">
        <select class="unit-pick" data-side="${side}" data-index="${index}">
          ${available
            .map(
              (unit) =>
                `<option value="${unit.id}" ${unit.id === selectedId ? "selected" : ""}>${escapeHtml(unit.name)}</option>`,
            )
            .join("")}
        </select>
        <input class="unit-count" type="number" min="1" max="1000" value="${entry.counts[index] || 20}" data-side="${side}" data-index="${index}" />
        <button type="button" class="remove" data-side="${side}" data-index="${index}" title="移除">×</button>
      </div>`,
    )
    .join("");
  const addButton = document.querySelector(`.add-unit[data-side="${side}"]`);
  if (addButton) addButton.disabled = entry.units.length >= maxUnits;

  const techContainer = document.querySelector(`.tech-select[data-side="${side}"]`);
  if (!techContainer) return;
  const techs = entry.available?.techs || [];
  if (!techs.length) {
    techContainer.innerHTML = '<div class="tech-empty">先选择兵种以显示可用科技</div>';
    return;
  }
  techContainer.innerHTML = `
    <div class="tech-empty">可选科技（已选 ${entry.techs.size}，不限数量）</div>
    ${techs
      .map(
        (tech) => `
        <label class="tech-option ${entry.techs.has(tech.id) ? "selected" : ""}" data-side="${side}">
          <input type="checkbox" class="tech-check" data-side="${side}" value="${tech.id}" ${entry.techs.has(tech.id) ? "checked" : ""} />
          <span>
            <span class="tech-name">${escapeHtml(tech.name)}${tech.specific ? " · 专属" : " · 通用"}</span>
            <span class="tech-summary">${escapeHtml(tech.summary || "")}</span>
            ${(tech.mechanisms || [])
              .map((m) => `<span class="tech-mechanism">${escapeHtml(m)}</span>`)
              .join("")}
          </span>
        </label>`,
      )
      .join("")}
  `;
}

function customPayload() {
  const build = (side) => {
    const entry = state.custom[side];
    const counts = entry.units.map((_id, index) => {
      const input = document.querySelector(
        `.unit-count[data-side="${side}"][data-index="${index}"]`,
      );
      return Math.max(1, Number(input?.value) || entry.counts[index] || 20);
    });
    return {
      civ: entry.civ,
      age: entry.age,
      units: entry.units,
      counts,
      techs: Array.from(entry.techs),
    };
  };
  return {
    mode: "custom",
    balance_blue: balanceBlue.checked,
    red: build("red"),
    blue: build("blue"),
  };
}

async function restartSimulation() {
  let payload;
  if (state.mode === "custom") {
    payload = { ...customPayload(), seed: Number(seedInput.value) };
  } else if (state.mode === "civ_war") {
    payload = {
      mode: "civ_war",
      red_civ: redCivSelect.value,
      blue_civ: blueCivSelect.value,
      age: Number(ageSelect.value),
      seed: Number(seedInput.value),
    };
  } else {
    payload = {
      mode: "units",
      red: `${redUnitInput.value.trim()}:${Number(redCountInput.value)}`,
      blue: `${blueUnitInput.value.trim()}:${Number(blueCountInput.value)}`,
      seed: Number(seedInput.value),
    };
  }
  restartButton.disabled = true;
  restartButton.textContent = "准备中…";
  state.generation += 1;
  state.fetchInFlight = true;
  try {
    if (state.mode === "civ_war" && redCivSelect.value === blueCivSelect.value) {
      throw new Error("红方和蓝方必须选择不同文明");
    }
    const response = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || "start failed");
    state.frames = [];
    state.trails.clear();
    state.frameIndex = 0;
    state.remoteCount = 0;
    state.attackEvents = [];
    state.seenEvents.clear();
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
    restartButton.textContent = "开始模拟";
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
      state.frameIndex = Math.min(state.frameIndex + 1, state.frames.length - 1);
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
canvas.addEventListener("click", (event) => selectAt(event.clientX, event.clientY));
window.addEventListener("resize", resizeCanvas);
chargeOnly.addEventListener("change", renderAttackLog);
document.querySelectorAll(".mode-tab").forEach((button) => {
  button.addEventListener("click", () => setMode(button.dataset.mode));
});
restartButton.addEventListener("click", restartSimulation);

document.querySelectorAll(".civ-select").forEach((select) => {
  select.addEventListener("change", () => {
    const side = select.dataset.side;
    state.custom[side].civ = select.value;
    state.custom[side].units = [];
    state.custom[side].counts = [];
    state.custom[side].techs.clear();
    refreshLoadout(side);
  });
});
document.querySelectorAll(".side-age").forEach((select) => {
  select.addEventListener("change", () => {
    const side = select.dataset.side;
    state.custom[side].age = Number(select.value) || 3;
    state.custom[side].units = [];
    state.custom[side].counts = [];
    state.custom[side].techs.clear();
    refreshLoadout(side);
  });
});
document.querySelectorAll(".add-unit").forEach((button) => {
  button.addEventListener("click", () => {
    const side = button.dataset.side;
    const entry = state.custom[side];
    const available = entry.available?.units || [];
    if (!available.length) return;
    const used = new Set(entry.units);
    const next = available.find((unit) => !used.has(unit.id));
    if (next) {
      entry.units.push(next.id);
      entry.counts.push(20);
    }
    renderCustomSide(side);
    refreshLoadout(side);
  });
});
customSetup.addEventListener("change", (event) => {
  const target = event.target;
  const side = target.dataset.side;
  if (!side) return;
  const index = Number(target.dataset.index);
  const entry = state.custom[side];
  if (target.classList.contains("unit-pick")) {
    entry.units[index] = target.value;
    entry.techs.clear();
    refreshLoadout(side);
  } else if (target.classList.contains("unit-count")) {
    entry.counts[index] = Math.max(1, Number(target.value) || 1);
  } else if (target.classList.contains("tech-check")) {
    if (target.checked) entry.techs.add(target.value);
    else entry.techs.delete(target.value);
    renderCustomSide(side);
  }
});
customSetup.addEventListener("click", (event) => {
  const remove = event.target.closest(".remove");
  if (!remove) return;
  const side = remove.dataset.side;
  const index = Number(remove.dataset.index);
  state.custom[side].units.splice(index, 1);
  state.custom[side].counts.splice(index, 1);
  state.custom[side].techs.clear();
  refreshLoadout(side);
});
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
  setMode("custom");
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
