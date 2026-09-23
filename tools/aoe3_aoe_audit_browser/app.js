const state = {
  snapshot: null,
  search: "",
  coverage: "all",
  slot: "all",
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const number = (value) => Number(value || 0).toLocaleString("zh-CN", {
  maximumFractionDigits: 2,
});

const slotLabel = (slot) => slot === "ranged" ? "远程" : "近战";

function unitIcon(slot) {
  if (slot.icon) {
    return `<img class="unit-icon" src="${escapeHtml(slot.icon)}" alt="" loading="lazy" />`;
  }
  return `<span class="unit-icon fallback">${escapeHtml(slot.name.slice(0, 1))}</span>`;
}

function renderSummary() {
  const s = state.snapshot.summary;
  $("#source").textContent = `数据源：${state.snapshot.generated_from}`;
  $("#hero-copy").textContent =
    `${s.explicit_aoe_slots} / ${s.aoe_slots} 个 AOE 槽位使用游戏原始 damagecap；` +
    `${s.fallback_aoe_slots} 个槽位走 2× fallback。`;
  $("#coverage-ring").style.setProperty("--coverage", `${s.explicit_aoe_slot_pct}%`);
  $("#coverage-ring").innerHTML =
    `<strong>${s.explicit_aoe_slot_pct.toFixed(1)}%</strong><span>显式 cap</span>`;

  const cards = [
    ["AOE 单位", s.aoe_units, "所有 AOE 槽位至少有一个的单位"],
    ["AOE 攻击槽位", s.aoe_slots, "远程与近战槽位分别计算"],
    ["显式 cap", s.explicit_aoe_slots, "会优先使用游戏原始数据"],
    ["2× fallback", s.fallback_aoe_slots, `涉及 ${s.units_with_missing_aoe_cap} 个单位`],
    ["几何参数", s.geometric_aoe_slots, `方向 ${s.directional_aoe_slots} · 圆形 ${s.radial_aoe_slots}`],
    ["外圈衰减", s.outer_falloff_aoe_slots, "已有 outerDistance / outerFactor"],
    ["cap 单位", s.cap_units, "字段中存在任意正 cap"],
    ["cap 槽位", s.cap_slots, `含 ${s.cap_without_aoe_slots} 个当前不触发 AOE`],
  ];
  $("#summary-grid").innerHTML = cards.map(([label, value, detail]) => `
    <article class="summary-card">
      <span class="summary-label">${escapeHtml(label)}</span>
      <strong class="summary-value">${number(value)}</strong>
      <small class="summary-detail">${escapeHtml(detail)}</small>
    </article>`).join("");
}

function renderMatrix() {
  const c = state.snapshot.categories;
  const total = Object.values(c).reduce((sum, value) => sum + value, 0);
  const cards = [
    {
      key: "aoe_explicit",
      title: "AOE + 显式 cap",
      count: c.aoe_explicit,
      tone: "good",
      detail: "正常触发，使用游戏数据",
    },
    {
      key: "aoe_fallback",
      title: "AOE + 2× fallback",
      count: c.aoe_fallback,
      tone: "warn",
      detail: "正常触发，cap 为模拟器估算",
    },
    {
      key: "cap_without_aoe",
      title: "cap，但无 AOE",
      count: c.cap_without_aoe,
      tone: "quiet",
      detail: "字段存在，当前攻击不触发",
    },
    {
      key: "no_aoe_no_cap",
      title: "无 AOE 且无 cap",
      count: c.no_aoe_no_cap,
      tone: "neutral",
      detail: "普通攻击槽位",
    },
  ];
  $("#coverage-matrix").innerHTML = `
    <div class="matrix-legend">总计 ${number(total)} 个攻击槽位</div>
    <div class="matrix-grid">${cards.map((card) => `
      <article class="matrix-card ${card.tone}">
        <span>${card.title}</span>
        <strong>${number(card.count)}</strong>
        <small>${card.detail}</small>
      </article>`).join("")}</div>`;
}

function ratioLabel(slot) {
  if (slot.cap_ratio == null) return "—";
  return `${number(slot.cap_ratio)}×`;
}

function deltaLabel(slot) {
  if (slot.cap_delta_from_2x == null) return "—";
  const value = slot.cap_delta_from_2x;
  const sign = value > 0 ? "+" : "";
  return `${sign}${number(value)}`;
}

function renderNonTwoX() {
  const s = state.snapshot.summary;
  const rows = state.snapshot.non_two_x_slots;
  $("#non-two-x-summary").innerHTML = `
    <span class="count-pill">${rows.length} 个显式 cap</span>
    <span class="count-pill muted-pill">低于 2× ${s.non_two_x_below}</span>
    <span class="count-pill warn-pill">高于 2× ${s.non_two_x_above}</span>`;
  $("#non-two-x-rows").innerHTML = rows.map((slot) => `
    <tr>
      <td>
        <div class="table-unit">${unitIcon(slot)}
          <div><strong>${escapeHtml(slot.name)}</strong><span>${escapeHtml(slot.unit_id)}</span></div>
        </div>
      </td>
      <td>${slotLabel(slot.slot)}</td>
      <td class="number">${number(slot.aoe_radius)}</td>
      <td class="number strong-number">${number(slot.cap)}</td>
      <td class="number">${number(slot.fallback_cap)}</td>
      <td class="number">${ratioLabel(slot)}</td>
      <td class="number ${slot.cap_delta_from_2x > 0 ? "above" : "below"}">${deltaLabel(slot)}</td>
    </tr>`).join("") || '<tr><td colspan="7" class="empty">没有非 2× 的显式 cap。</td></tr>';
}

function geometryRow(slot) {
  const mode = slot.area_sort_mode || "未标注";
  const outer = slot.outer_damage_area_distance > 0 && slot.outer_damage_area_factor > 0
    ? `${number(slot.outer_damage_area_distance)} → ${number(slot.outer_damage_area_factor)}`
    : "—";
  return `
    <tr>
      <td>
        <div class="table-unit">${unitIcon(slot)}
          <div><strong>${escapeHtml(slot.name)}</strong><span>${escapeHtml(slot.unit_id)}</span></div>
        </div>
      </td>
      <td>${slotLabel(slot.slot)}</td>
      <td class="number">${number(slot.aoe_radius)}</td>
      <td><span class="status ${mode.toLowerCase() === "directional" ? "good" : "quiet"}">${escapeHtml(mode)}</span></td>
      <td class="number">${outer}</td>
      <td class="number">${slot.basedamagecap ? "是" : "—"}</td>
    </tr>`;
}

function renderGeometry() {
  const rows = state.snapshot.geometric_aoe_slots || [];
  $("#geometry-count").textContent = `${rows.length} 个槽位`;
  $("#geometry-rows").innerHTML = rows.map(geometryRow).join("")
    || '<tr><td colspan="6" class="empty">没有几何参数。</td></tr>';
}

function fallbackRow(slot) {
  return `
    <article class="unit-row">
      ${unitIcon(slot)}
      <div class="unit-main">
        <div class="unit-title">
          <strong>${escapeHtml(slot.name)}</strong>
          <span>${slotLabel(slot.slot)} · AOE ${number(slot.aoe_radius)}</span>
        </div>
        <div class="unit-sub">${escapeHtml(slot.unit_id)} · 2× cap ${number(slot.fallback_cap)}</div>
      </div>
      <div class="unit-value">${number(slot.effective_cap)}</div>
    </article>`;
}

function capOnlyRow(slot) {
  return `
    <article class="unit-row">
      ${unitIcon(slot)}
      <div class="unit-main">
        <div class="unit-title">
          <strong>${escapeHtml(slot.name)}</strong>
          <span>${slotLabel(slot.slot)}</span>
        </div>
        <div class="unit-sub">${escapeHtml(slot.unit_id)} · 当前无 AOE 半径</div>
      </div>
      <div class="unit-value">${number(slot.cap)}</div>
    </article>`;
}

function renderLists() {
  const fallback = state.snapshot.fallback_aoe_slots;
  $("#fallback-count").textContent = `${fallback.length} 个槽位`;
  $("#fallback-list").innerHTML = fallback.map(fallbackRow).join("")
    || '<p class="empty">没有缺口。</p>';
  const capOnly = state.snapshot.cap_without_aoe_slots;
  $("#cap-only-count").textContent = `${capOnly.length} 个槽位`;
  $("#cap-only-list").innerHTML = capOnly.map(capOnlyRow).join("")
    || '<p class="empty">没有这类槽位。</p>';
}

function filteredSlots() {
  const search = state.search.trim().toLowerCase();
  return state.snapshot.slots.filter((slot) => {
    if (state.slot !== "all" && slot.slot !== state.slot) return false;
    if (state.coverage === "aoe" && slot.aoe_radius <= 0) return false;
    if (state.coverage === "non-two-x") {
      if (!(slot.aoe_radius > 0 && slot.cap > 0 && Math.abs(slot.cap - slot.fallback_cap) >= 1e-9)) {
        return false;
      }
    }
    if (state.coverage === "fallback" && !(slot.aoe_radius > 0 && slot.cap <= 0)) return false;
    if (state.coverage === "cap-only" && !(slot.cap > 0 && slot.aoe_radius <= 0)) return false;
    if (!search) return true;
    return `${slot.name} ${slot.name_en} ${slot.unit_id}`.toLowerCase().includes(search);
  });
}

function statusMarkup(slot) {
  if (slot.aoe_radius > 0 && slot.cap > 0) {
    return '<span class="status good">AOE · 显式 cap</span>';
  }
  if (slot.aoe_radius > 0) {
    return '<span class="status warn">AOE · fallback</span>';
  }
  return '<span class="status quiet">cap · 无 AOE</span>';
}

function renderTable() {
  const rows = filteredSlots();
  $("#table-meta").textContent =
    `显示 ${rows.length} / ${state.snapshot.slots.length} 个槽位；单位数、槽位数与 cap 覆盖不混算。`;
  $("#slot-rows").innerHTML = rows.map((slot) => `
    <tr>
      <td>
        <div class="table-unit">${unitIcon(slot)}
          <div><strong>${escapeHtml(slot.name)}</strong><span>${escapeHtml(slot.unit_id)}</span></div>
        </div>
      </td>
      <td>${slotLabel(slot.slot)}</td>
      <td>${statusMarkup(slot)}</td>
      <td class="number">${slot.aoe_radius > 0 ? number(slot.aoe_radius) : "—"}</td>
      <td class="number">${slot.cap > 0 ? number(slot.cap) : "—"}</td>
      <td class="number">${slot.aoe_radius > 0 || slot.cap > 0 ? number(slot.effective_cap) : "—"}</td>
      <td>${escapeHtml(slot.area_sort_mode || "—")}</td>
      <td class="number">${slot.outer_damage_area_distance > 0 || slot.outer_damage_area_factor > 0
        ? `${number(slot.outer_damage_area_distance)} → ${number(slot.outer_damage_area_factor)}`
        : "—"}</td>
      <td class="number">${number(slot.attack)} × ${number(slot.projectiles)}</td>
      <td>${escapeHtml(slot.damage_type || "—")}</td>
    </tr>`).join("") || '<tr><td colspan="10" class="empty">没有匹配的槽位。</td></tr>';
}

function wireControls() {
  $("#search").addEventListener("input", (event) => {
    state.search = event.target.value;
    renderTable();
  });
  $("#coverage-filter").addEventListener("change", (event) => {
    state.coverage = event.target.value;
    renderTable();
  });
  $("#slot-filter").addEventListener("change", (event) => {
    state.slot = event.target.value;
    renderTable();
  });
}

async function initialize() {
  try {
    const response = await fetch("/api/snapshot");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "读取审计数据失败");
    state.snapshot = payload;
    renderSummary();
    renderMatrix();
    renderNonTwoX();
    renderGeometry();
    renderLists();
    renderTable();
    wireControls();
  } catch (error) {
    $("#hero-copy").textContent = `无法读取审计数据：${error.message}`;
    $("#summary-grid").innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
  }
}

initialize();
