const state = {
  bootstrap: null,
  snapshot: null,
  civ: "DEEthiopians",
  age: 3,
  localOnly: false,
  includeConsulate: true,
  activeTab: "national",
  editorTactic: null,
  deleteArmed: false,
};

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function roleLabel(role) {
  return state.bootstrap.roles[role].label;
}

function iconMarkup(unit, small = false) {
  const sizeClass = small ? " small-icon" : "";
  if (unit.icon) {
    return `<img class="unit-icon${sizeClass}" src="${unit.icon}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'), {className:'unit-icon fallback${sizeClass}',textContent:'${escapeHtml(unit.name.slice(0, 1))}'}))" />`;
  }
  return `<span class="unit-icon fallback${sizeClass}" aria-hidden="true">${escapeHtml(unit.name.slice(0, 1))}</span>`;
}

function roleChips(roles) {
  if (!roles.length) return '<span class="muted">未命中通用生态位</span>';
  return `<div class="role-chips">${roles.map((role) => `<span class="role-chip role-${role}">${roleLabel(role)}</span>`).join("")}</div>`;
}

function candidateRoleChips(unit) {
  const primary = unit.slot_role;
  const secondary = unit.roles.filter((role) => role !== primary);
  const primaryChip = primary ? `<span class="role-chip role-${primary}">主：${roleLabel(primary)}</span>` : "";
  const secondaryChips = secondary.map((role) => `<span class="role-chip role-${role}">次：${roleLabel(role)}</span>`).join("");
  return `<div class="role-chips">${primaryChip || '<span class="muted">无主生态位</span>'}${secondaryChips}</div>`;
}

function formatCost(cost) {
  const labels = { food: "食", wood: "木", gold: "金", export: "贸", influence: "影" };
  return Object.entries(cost || {}).map(([kind, value]) => `${value}${labels[kind] || kind}`).join(" ") || "无费用";
}

function unitRow(unit) {
  const counters = [...unit.ranged_counters, ...unit.melee_counters];
  const why = Object.entries(unit.role_explanations)
    .map(([role, explanation]) => `<div><strong>${roleLabel(role)}：</strong>${escapeHtml(explanation)}</div>`)
    .join("") || "未命中本期通用生态位。";
  return `
    <details class="unit-row">
      <summary>
        ${iconMarkup(unit)}
        <div>
          <div class="unit-name-line"><span class="unit-name">${escapeHtml(unit.name)}</span>${unit.is_consulate ? '<span class="consulate-flag">领事馆</span>' : ""}</div>
          <div class="unit-en">${escapeHtml(unit.name_en)}</div>
          <div class="unit-meta"><span>登场 ${unit.age} 时</span><span>当前 ${unit.current_age} 时数值</span><span>${formatCost(unit.cost)}</span><span>${unit.hp} HP</span><span>速 ${unit.speed}</span></div>
          ${roleChips(unit.roles)}
        </div>
      </summary>
      <div class="unit-detail">
        <div class="detail-block"><span class="detail-label">生态位判定</span>${why}</div>
        <div class="detail-block"><span class="detail-label">关键 type 标签</span><div class="tags">${unit.type.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("") || "-"}</div></div>
        <div class="detail-block"><span class="detail-label">倍率证据</span>${counters.length ? escapeHtml(counters.join("；")) : "当前攻击数据没有相关正倍率"}</div>
      </div>
    </details>`;
}

function candidateCard(candidate) {
  return `
    <article class="candidate-card">
      <div class="candidate-header">
        <span class="candidate-id">${escapeHtml(candidate.id)}</span>
        ${candidate.uses_consulate ? '<span class="consulate-flag">使用领事馆</span>' : '<span class="fixed-badge">非领事馆组合</span>'}
      </div>
      <div class="candidate-units">
        ${candidate.units.map((unit) => `
          <div class="candidate-unit">
            ${iconMarkup(unit, true)}
            <div>
              <div class="candidate-unit-name"><span class="unit-name">${escapeHtml(unit.name)}</span><span class="unit-en">${escapeHtml(unit.name_en)}</span></div>
              ${candidateRoleChips(unit)}
            </div>
          </div>`).join("")}
      </div>
      <div class="share-row" aria-label="待定资源占比">
        <span class="share-label">资源占比</span>
        ${candidate.default_shares.map((share) => `<input class="share-input" value="${share}%" readonly aria-label="待定资源占比 ${share}%" />`).join("")}
        <span class="share-note">待定</span>
      </div>
    </article>`;
}

function allocationLabel(tactic) {
  if (tactic.allocation_kind === "fixed_ratio") {
    return `固定人数比 ${tactic.allocation_values.map((value) => Number(value)).join(" : ")}`;
  }
  return `资源占比 ${tactic.allocation_values.map((value) => `${Math.round(value * 100)}%`).join(" / ")}`;
}

function preferredTacticCard(tactic) {
  const status = tactic.status === "implemented"
    ? '<span class="implemented-badge">已实现固定战术</span>'
    : tactic.status === "draft"
      ? '<span class="draft-badge">审核草案</span>'
      : '<span class="implemented-badge">已启用</span>';
  return `
    <article class="preferred-card ${tactic.available ? "" : "unavailable"}">
      <header class="preferred-card-header">
        <div>
          <div class="preferred-title-row"><h3>${escapeHtml(tactic.title)}</h3>${status}</div>
          <div class="preferred-id">${escapeHtml(tactic.id)}</div>
        </div>
        <div class="preferred-card-tools">
          <div class="allocation-label">${escapeHtml(allocationLabel(tactic))}</div>
          ${tactic.status === "implemented" ? "" : `<button type="button" class="edit-command" data-edit-tactic="${escapeHtml(tactic.id)}">编辑</button>`}
        </div>
      </header>
      <div class="evidence-row">${tactic.basis.map((item) => `<span class="evidence-chip">${escapeHtml(item)}</span>`).join("")}</div>
      <p class="preferred-reason">${escapeHtml(tactic.reason)}</p>
      <div class="preferred-units">
        ${tactic.units.map((unit) => `
          <div class="preferred-unit">
            ${iconMarkup(unit)}
            <div class="preferred-unit-main">
              <div class="candidate-unit-name"><span class="unit-name">${escapeHtml(unit.name)}</span><span class="unit-en">${escapeHtml(unit.name_en)}</span></div>
              <div class="preferred-unit-stats"><span>${formatCost(unit.cost)}</span><span>${unit.hp} HP</span><span>速 ${unit.speed}</span></div>
              ${roleChips(unit.roles)}
            </div>
            <div class="preferred-count">${unit.count == null ? "未到时代" : `×${unit.count}`}</div>
          </div>`).join("")}
      </div>
      <footer class="preferred-card-footer">
        <span>${tactic.min_age} 时代起</span>
        <strong>${tactic.total_cost == null ? "当前不可用" : `总资源 ${tactic.total_cost}`}</strong>
      </footer>
    </article>`;
}

function renderUnits(snapshot) {
  $("#civ-title").textContent = `${snapshot.civ.name} / ${snapshot.civ.name_en}`;
  $("#unit-count").textContent = `${snapshot.unit_counts.shown} / ${snapshot.unit_counts.safe_regular} 个`;
  $("#unit-list").innerHTML = snapshot.units.map(unitRow).join("") || '<p class="muted">当前筛选没有可展示的正规军单位。</p>';
}

function renderQuickCivs() {
  const civById = Object.fromEntries(state.bootstrap.civs.map((civ) => [civ.id, civ]));
  $("#quick-civs").innerHTML = state.bootstrap.quick_civs.map((id) => {
    const civ = civById[id];
    return `<button type="button" class="quick-civ ${id === state.civ ? "active" : ""}" data-civ="${id}">${escapeHtml(civ.name)}</button>`;
  }).join("");
  document.querySelectorAll(".quick-civ").forEach((button) => {
    button.addEventListener("click", () => setCiv(button.dataset.civ));
  });
}

function renderLineups(snapshot) {
  const total = Object.values(snapshot.candidate_counts).reduce((sum, value) => sum + value, 0);
  $("#lineup-summary").textContent = `${total} 条合法候选；本国非领事馆组合排在前`;
  $("#archetype-list").innerHTML = state.bootstrap.archetypes.map((archetype) => {
    const candidates = snapshot.candidates[archetype.id] || [];
    const skeleton = archetype.roles.map(roleLabel).join(" + ");
    return `
      <section class="archetype-section">
        <div class="archetype-heading">
          <h3>${escapeHtml(archetype.title)}</h3>
          <span class="skeleton">${skeleton} · ${candidates.length} 条</span>
        </div>
        ${candidates.length ? `<div class="candidate-grid">${candidates.map(candidateCard).join("")}</div>` : '<div class="empty-candidates">当前兵池缺少该骨架所需生态位。</div>'}
      </section>`;
  }).join("");
}

function renderNational(snapshot) {
  const counts = Object.values(state.bootstrap.preferred_counts);
  const total = counts.reduce((sum, value) => sum + value, 0);
  const drafts = snapshot.preferred_tactics.filter((tactic) => tactic.status === "draft").length;
  $("#preferred-summary").textContent = `24 个文明 · ${total} 套策略 · 当前文明 ${drafts} 套草案`;
  $("#preferred-note").textContent = state.bootstrap.preferred_draft_note;
  $("#preferred-civ-title").textContent = `${snapshot.civ.name} · ${snapshot.preferred_tactics.length} 套`;
  $("#preferred-civ-nav").innerHTML = state.bootstrap.civs.map((civ) => `
    <button type="button" class="preferred-civ-button ${civ.id === state.civ ? "active" : ""}" data-preferred-civ="${civ.id}">
      <span>${escapeHtml(civ.name.replace(/人$/, ""))}</span>
      <strong>${state.bootstrap.preferred_counts[civ.id] || 0}</strong>
    </button>`).join("");
  document.querySelectorAll("[data-preferred-civ]").forEach((button) => {
    button.addEventListener("click", () => setCiv(button.dataset.preferredCiv));
  });
  $("#preferred-list").innerHTML = snapshot.preferred_tactics.length
    ? snapshot.preferred_tactics.map(preferredTacticCard).join("")
    : '<div class="empty-candidates">当前文明尚无优势策略。</div>';
  document.querySelectorAll("[data-edit-tactic]").forEach((button) => {
    button.addEventListener("click", () => {
      const tactic = snapshot.preferred_tactics.find((item) => item.id === button.dataset.editTactic);
      if (tactic) openTacticEditor(tactic);
    });
  });
}

function editorUnitOptions(selected = "", optional = false) {
  const units = state.snapshot?.preferred_unit_options || state.snapshot?.units || [];
  const empty = optional ? '<option value="">不使用第三兵种</option>' : '<option value="">选择兵种</option>';
  return empty + units.map((unit) => `<option value="${escapeHtml(unit.id)}" ${unit.id === selected ? "selected" : ""}>${escapeHtml(unit.base_name)} / ${escapeHtml(unit.name_en)}</option>`).join("");
}

function renderEditorUnitRows(tactic) {
  const unitIds = tactic?.units?.map((unit) => unit.id) || [""];
  const shares = tactic?.allocation_values?.map((value) => Math.round(value * 100)) || [100];
  while (unitIds.length < 3) unitIds.push("");
  while (shares.length < 3) shares.push(0);
  $("#editor-unit-rows").innerHTML = [0, 1, 2].map((index) => `
    <div class="editor-unit-row">
      <span class="editor-slot">${index + 1}</span>
      <select class="editor-unit-select" data-editor-unit="${index}" ${index === 0 ? "required" : ""}>${editorUnitOptions(unitIds[index], index > 0)}</select>
      <label class="share-editor"><input type="number" min="0" max="100" step="1" value="${shares[index]}" data-editor-share="${index}" /><span>%</span></label>
    </div>`).join("");
  document.querySelectorAll("[data-editor-share], [data-editor-unit]").forEach((input) => {
    input.addEventListener("input", updateShareTotal);
    input.addEventListener("change", updateShareTotal);
  });
  updateShareTotal();
}

function updateShareTotal() {
  const rows = [0, 1, 2].map((index) => ({
    unit: document.querySelector(`[data-editor-unit="${index}"]`)?.value || "",
    share: Number(document.querySelector(`[data-editor-share="${index}"]`)?.value || 0),
  }));
  const total = rows.filter((row) => row.unit).reduce((sum, row) => sum + row.share, 0);
  const totalNode = $("#share-total");
  totalNode.textContent = `合计 ${total}%`;
  totalNode.classList.toggle("invalid", total !== 100);
}

function openTacticEditor(tactic = null) {
  state.editorTactic = tactic;
  state.deleteArmed = false;
  $("#editor-heading").textContent = tactic ? `编辑 · ${tactic.title}` : `新增 · ${state.snapshot.civ.name}`;
  $("#editor-id").value = tactic?.id || `draft_${Date.now().toString(36)}`;
  $("#editor-title").value = tactic?.title || "";
  $("#editor-age").value = String(tactic?.min_age || 3);
  $("#editor-basis").value = tactic?.basis?.join(", ") || "";
  $("#editor-approved").checked = tactic?.status !== "draft";
  $("#editor-reason").value = tactic?.reason || "";
  $("#editor-error").textContent = "";
  $("#delete-tactic").hidden = !tactic;
  $("#delete-tactic").textContent = "删除策略";
  renderEditorUnitRows(tactic);
  $("#tactic-editor").showModal();
}

function readEditorTactic() {
  const units = [];
  const values = [];
  for (let index = 0; index < 3; index += 1) {
    const unit = document.querySelector(`[data-editor-unit="${index}"]`).value;
    const share = Number(document.querySelector(`[data-editor-share="${index}"]`).value || 0);
    if (unit) {
      units.push(unit);
      values.push(share / 100);
    }
  }
  if (units.length < 1 || new Set(units).size !== units.length) throw new Error("请选择 1~3 个不同兵种");
  if (Math.round(values.reduce((sum, value) => sum + value, 0) * 100) !== 100) throw new Error("资源占比合计必须为 100%");
  return {
    id: $("#editor-id").value,
    status: $("#editor-approved").checked ? "approved" : "draft",
    title: $("#editor-title").value.trim(),
    min_age: Number($("#editor-age").value),
    unit_ids: units,
    allocation: { kind: "resource_shares", values },
    basis: $("#editor-basis").value.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
    reason: $("#editor-reason").value.trim(),
  };
}

async function postTactic(payload) {
  const response = await fetch("/api/preferred-tactic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "保存失败");
  const bootstrapResponse = await fetch("/api/bootstrap");
  state.bootstrap = await bootstrapResponse.json();
  await loadSnapshot();
}

function wireEditor() {
  $("#add-preferred").addEventListener("click", () => openTacticEditor());
  ["#close-editor", "#cancel-editor"].forEach((selector) => {
    $(selector).addEventListener("click", () => $("#tactic-editor").close());
  });
  $("#tactic-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const tactic = readEditorTactic();
      await postTactic({ action: "save", civ_id: state.civ, tactic });
      $("#tactic-editor").close();
    } catch (error) {
      $("#editor-error").textContent = error.message;
    }
  });
  $("#delete-tactic").addEventListener("click", async () => {
    if (!state.editorTactic) return;
    if (!state.deleteArmed) {
      state.deleteArmed = true;
      $("#delete-tactic").textContent = "再次点击确认删除";
      return;
    }
    try {
      await postTactic({ action: "delete", civ_id: state.civ, tactic_id: state.editorTactic.id });
      $("#tactic-editor").close();
    } catch (error) {
      $("#editor-error").textContent = error.message;
    }
  });
}

function renderAudit(snapshot) {
  const maxCandidate = Math.max(1, ...Object.values(snapshot.candidate_counts));
  $("#candidate-counts").innerHTML = state.bootstrap.archetypes.map((archetype) => {
    const count = snapshot.candidate_counts[archetype.id];
    return `<div class="audit-row ${count === 0 ? "empty" : ""}"><span>${escapeHtml(archetype.title)}</span><div class="audit-bar"><span style="width:${Math.max(count ? 8 : 0, (count / maxCandidate) * 100)}%"></span></div><strong>${count}</strong></div>`;
  }).join("");
  const maxRole = Math.max(1, ...Object.values(snapshot.role_coverage));
  $("#role-coverage").innerHTML = Object.entries(snapshot.role_coverage).map(([role, count]) => `
    <div class="audit-row ${count === 0 ? "empty" : ""}"><span>${roleLabel(role)}${count === 0 ? "（缺口）" : ""}</span><div class="audit-bar"><span style="width:${Math.max(count ? 8 : 0, (count / maxRole) * 100)}%"></span></div><strong>${count}</strong></div>`).join("");
  $("#excluded-count").textContent = `${snapshot.excluded.length} 项`;
  $("#excluded-list").innerHTML = snapshot.excluded.length ? snapshot.excluded.map((item) => `
    <div class="excluded-row"><div><div class="excluded-name">${escapeHtml(item.name)}</div><div class="excluded-id">${escapeHtml(item.id)}${item.name_en ? ` · ${escapeHtml(item.name_en)}` : ""}</div></div><div class="excluded-reason">${escapeHtml(item.reason)}</div></div>`).join("") : '<p class="muted">当前文明的 seed 单位没有触发已记录的排除或时代门槛。</p>';
}

function renderSnapshot(snapshot) {
  state.snapshot = snapshot;
  renderQuickCivs();
  renderUnits(snapshot);
  renderLineups(snapshot);
  renderNational(snapshot);
  renderAudit(snapshot);
}

async function loadSnapshot() {
  const params = new URLSearchParams({
    civ: state.civ,
    age: state.age,
    local_only: state.localOnly,
    include_consulate: state.includeConsulate,
  });
  $("#unit-list").innerHTML = '<p class="muted">正在按真实规则解析…</p>';
  const response = await fetch(`/api/civ?${params}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "读取审查数据失败");
  renderSnapshot(payload);
}

async function setCiv(civId) {
  const known = state.bootstrap.civs.some((civ) => civ.id === civId);
  if (!known) return;
  state.civ = civId;
  const civ = state.bootstrap.civs.find((item) => item.id === civId);
  $("#civ-search").value = `${civ.name} / ${civ.name_en}`;
  await loadSnapshot();
}

function setActiveTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `${tab}-view`));
}

function wireControls() {
  document.querySelectorAll("[data-age]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.age = Number(button.dataset.age);
      document.querySelectorAll("[data-age]").forEach((item) => item.classList.toggle("active", item === button));
      await loadSnapshot();
    });
  });
  $("#local-only").addEventListener("change", async (event) => {
    state.localOnly = event.target.checked;
    await loadSnapshot();
  });
  $("#include-consulate").addEventListener("change", async (event) => {
    state.includeConsulate = event.target.checked;
    await loadSnapshot();
  });
  $("#civ-search").addEventListener("change", async (event) => {
    const value = event.target.value.trim().toLowerCase();
    const match = state.bootstrap.civs.find((civ) => [civ.id, civ.name, civ.name_en, `${civ.name} / ${civ.name_en}`].some((candidate) => candidate.toLowerCase() === value));
    if (match) await setCiv(match.id);
    else if (state.snapshot) event.target.value = `${state.snapshot.civ.name} / ${state.snapshot.civ.name_en}`;
  });
  document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => setActiveTab(button.dataset.tab)));
}

async function initialize() {
  try {
    const response = await fetch("/api/bootstrap");
    state.bootstrap = await response.json();
    $("#civ-options").innerHTML = state.bootstrap.civs.map((civ) => `<option value="${escapeHtml(civ.name)} / ${escapeHtml(civ.name_en)}"></option>`).join("");
    wireEditor();
    await setCiv(state.civ);
    wireControls();
  } catch (error) {
    $("#unit-list").innerHTML = `<p class="muted">无法加载审查数据：${escapeHtml(error.message)}</p>`;
  }
}

initialize();
