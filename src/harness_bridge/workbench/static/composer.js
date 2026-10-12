'use strict';
/* Conversation composer: the input box, attachments, @ file references, / commands, and the
   model / reasoning-effort / permission-mode selectors.

   Options come only from the harness's own catalog (S.state.catalogs: Claude Code's initialize
   response, Codex's model/list). A choice goes to the App's settings API, which applies it with
   the harness's own requests; the selectors then show what the harness reported back, with a
   marker while a choice is only selected, being applied, or was refused. Loaded before app.js
   and uses its helpers (h, icon, api, S, …) only when called. */

// Effort levels keep the harness's own names (low … xhigh, max; some Codex models also list ultra).
// Only the levels the harness lists for the model are offered. A level's description is the
// harness's own (Codex model/list) or, for Claude Code, its documented guidance for that level
// (code.claude.com/docs/en/model-config). Claude's Ultracode is a separate switch, never a level.
const CLAUDE_EFFORT_HINT = {
  low: '快速往返，适合逐步审阅',
  medium: '日常工作，范围清楚',
  high: '需要验证、边界情况多',
  xhigh: '更深入的推理，消耗更多 token',
  max: '最难的问题；可能想得过多',
};
const FIELD_NAME = { model: '模型', effort: '思考强度', mode: '权限模式', claude_ultracode: 'Ultracode' };
const FIELD_STATE = {
  selected: '已选择，尚未生效',
  applying: '正在应用…',
  confirmed: '已由 CLI 确认生效',
  failed: '没有生效',
  launched: '已作为启动参数传给终端（终端里无法确认）',
};
const REVIEWER = { user: '你（在 RepoBridge 中确认）', auto_review: ' Codex 自动审查', guardian_subagent: ' Codex 审查子代理' };
const SOURCE_TEXT = {
  get_settings: 'get_settings 读回', control_response: 'CLI 回应', 'system/init': '本轮启动信息',
  'thread/start': 'thread/start 结果', 'thread/resume': 'thread/resume 结果', 'thread/read': 'thread/read 读回',
  message_start: '模型回复', 'model/rerouted': 'Codex 改道通知',
};

function composerState() {
  if (!S.attach) S.attach = new Map();
  if (!S.catalogAsked) S.catalogAsked = new Set();
  if (!S.dismissed) S.dismissed = new Set();
  if (!S.fileCache) S.fileCache = new Map();
}

// ---------------------------------------------------------------- catalog & settings model

function catalogOf(s) {
  return (S.state && S.state.catalogs && S.state.catalogs[s.harness]) || { status: 'missing', models: [], modes: [] };
}

function ensureCatalog(s) {
  composerState();
  const cat = catalogOf(s);
  if ((cat.status === 'missing' || cat.stale) && !S.catalogAsked.has(s.harness) && harnessOk(s.harness)) {
    S.catalogAsked.add(s.harness);
    api('POST', `/api/catalog/${s.harness}/refresh`, { session_id: s.session_id }).catch(() => {});
  }
}

function refreshCatalog(s) {
  composerState();
  S.catalogAsked.add(s.harness);
  guarded(`catalog:${s.harness}`, () => api('POST', `/api/catalog/${s.harness}/refresh`, { session_id: s.session_id }));
}

function settingsOf(s) {
  const st = s.settings || {};
  return { chosen: st.chosen || {}, fields: st.fields || {}, actual: st.actual || {}, notices: st.notices || [], turn_model: st.turn_model, native: st.native || {} };
}

function findModel(cat, id) {
  if (!cat || !cat.models || !id) return null;
  return cat.models.find((m) => m.id === id) || cat.models.find((m) => m.resolved === id && m.id !== 'default') || cat.models.find((m) => m.resolved === id) || null;
}

function modelNow(s) {
  const st = settingsOf(s);
  const cat = catalogOf(s);
  const id = st.chosen.model || st.actual.model || null;
  const entry = findModel(cat, id) || (!id ? findModel(cat, cat.default_model) : null);
  return { id, entry, label: entry ? entry.label : (id || '默认模型') };
}

function effortNow(s) {
  // Only an explicit choice or what the harness reported; never a guess from the catalog.
  const st = settingsOf(s);
  const level = st.chosen.effort || st.actual.effort || null;
  return { level, label: level || '默认' };
}

function effortHint(s, entry, level) {
  const own = entry && (entry.effort_descriptions || {})[level];
  return own || (s.harness === 'claude-code' ? CLAUDE_EFFORT_HINT[level] || '' : '');
}

// Claude Code's Ultracode: available only after Claude Code itself reported it (get_settings).
function ultracodeNow(s) {
  if (s.harness !== 'claude-code') return null;
  const st = settingsOf(s);
  const available = st.actual.claude_ultracode_available === true;
  const on = st.actual.claude_ultracode === true;
  const chosen = st.chosen.claude_ultracode;
  return { available, on, chosen: chosen === undefined ? null : chosen, live: !!st.actual.live };
}

function modeNow(s) {
  const st = settingsOf(s);
  const cat = catalogOf(s);
  const id = st.chosen.mode || st.actual.mode || null;
  const entry = (cat.modes || []).find((m) => m.id === id);
  let label = entry ? entry.label : null;
  if (!label && id === 'bypassPermissions') label = '跳过权限检查（来自 CLI 设置）';
  if (!label && id === 'other') label = st.actual.mode_label || '其他（来自 CLI 设置）';
  return { id, entry, label: label || (s.harness === 'codex' ? 'Codex 默认权限' : '需要时询问') };
}

// The harness's own value for the current permission mode, as it reported it.
function nativeModeText(s) {
  const n = settingsOf(s).native;
  if (s.harness === 'codex') return [n.approvalPolicy, n.sandbox && (n.sandbox.type || n.sandbox)].filter(Boolean).join(' · ');
  return n.permissionMode || '';
}

function valueLabel(s, name, value) {
  if (value === null || value === undefined) return '默认';
  if (name === 'model') { const m = findModel(catalogOf(s), value); return m ? m.label : value; }
  if (name === 'effort') return value;
  if (name === 'claude_ultracode') return value ? '开' : '关';
  const m = (catalogOf(s).modes || []).find((x) => x.id === value);
  return m ? m.label : value;
}

function currentLabel(s, name) {
  if (name === 'model') return modelNow(s).label;
  if (name === 'effort') return effortNow(s).label;
  if (name === 'claude_ultracode') { const u = ultracodeNow(s); return u && u.on ? '开' : '关'; }
  return modeNow(s).label;
}

function fieldStateText(s, name) {
  // Describes the last choice for this field; a refused choice names what was refused.
  const st = settingsOf(s);
  const rec = st.fields[name];
  if (!rec || !rec.state) return st.chosen[name] === undefined ? 'CLI 默认' : '';
  if (rec.state === 'failed') return `切换到「${valueLabel(s, name, rec.attempted)}」没有生效，仍是当前值`;
  return FIELD_STATE[rec.state] || rec.state;
}

function fieldTitle(s, name, label) {
  const st = settingsOf(s);
  const rec = st.fields[name];
  const lines = [`${FIELD_NAME[name]}：${label}`];
  if (rec && rec.state) {
    lines.push(fieldStateText(s, name));
    if (rec.note) lines.push(rec.note);
    if (rec.state === 'failed' && rec.error) lines.push(rec.error);
  } else lines.push(st.chosen[name] === undefined ? `未单独设置，使用 ${HARNESS[s.harness].label} 自己的默认值` : '');
  const src = (st.actual.sources || {})[name];
  if (src) lines.push(`${st.actual.live ? '当前值' : '上次连接时的值'}来自 ${SOURCE_TEXT[src] || src}`);
  return lines.filter(Boolean).join('\n');
}

// When a selected (not yet applied) choice takes effect, in the harness's own terms.
function pendingWhen(s) {
  if (s.harness === 'codex') return '下一条生效';
  return s.active ? (s.turn ? '本轮后生效' : '正在应用') : '连接时生效';
}

// The short note next to a control: pending, applying or refused. Never a full-width banner.
function controlNote(s, names) {
  const st = settingsOf(s);
  const recs = names.map((n) => [n, st.fields[n]]).filter(([, r]) => r && r.state);
  if (recs.some(([, r]) => r.state === 'failed')) return { tone: 'bad', text: '未生效', title: recs.filter(([, r]) => r.state === 'failed').map(([n]) => fieldTitle(s, n, currentLabel(s, n))).join('\n\n') };
  if (recs.some(([, r]) => r.state === 'applying')) return { tone: 'idle', text: '应用中…', title: '正在请 CLI 应用并读回' };
  const pending = recs.filter(([, r]) => r.state === 'selected');
  if (pending.length) return { tone: 'pending', text: pendingWhen(s), title: pending.map(([n, r]) => `${FIELD_NAME[n]}：已选择「${valueLabel(s, n, r.value !== undefined ? r.value : st.chosen[n])}」，${pendingWhen(s)}`).join('\n') };
  return null;
}

function chooseSetting(s, changes) {
  const sid = s.session_id;
  guarded(`settings:${sid}`, async () => {
    const view = await api('POST', `/api/sessions/${sid}/settings`, changes);
    const fresh = (view.notices || []).filter((n) => !S.dismissed.has(`n:${sid}:${n.at}`));
    for (const n of fresh.slice(-2)) { S.dismissed.add(`n:${sid}:${n.at}`); toast(n.text); }
  });
}

// ---------------------------------------------------------------- menus
// One menu for every picker in the input bar: role=menu with radio/checkbox items, ↑↓/Home/End,
// Enter or Space to choose, Esc to close; the opener carries aria-haspopup/aria-expanded and gets
// focus back on close. `keep` items re-render the menu in place instead of closing it.

function menuPanel(anchor, { title, cls = '' }) {
  const el = h('div', { class: `menu picker ${cls}`.trim(), role: 'menu', 'aria-label': title });
  const opener = anchor instanceof Element ? anchor : null;
  let close = () => {};
  let paint = null;
  const items = () => [...el.querySelectorAll('.menu-item:not(:disabled)')];
  const set = (list, footer) => {
    const keep = document.activeElement && el.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const nodes = [];
    let chips = null; // consecutive `chip` items share one row (a level row, like Claude Code's Effort row)
    if (title) nodes.push(h('div', { class: 'menu-head', 'aria-hidden': 'true' }, title));
    list.forEach((it, i) => {
      if (!it) return;
      if (!it.chip) chips = null;
      if (it === '-') { nodes.push(h('div', { class: 'menu-sep', role: 'separator' })); return; }
      if (it.head) { nodes.push(h('div', { class: 'menu-head', role: 'presentation' }, it.head)); return; }
      if (it.text) { nodes.push(h('div', { class: 'menu-text hint' }, it.text)); return; }
      const role = it.kind === 'check' ? 'menuitemcheckbox' : it.kind === 'action' ? 'menuitem' : 'menuitemradio';
      const checkable = role !== 'menuitem';
      if (it.chip) {
        if (!chips) { chips = h('div', { class: 'menu-chips', role: 'group', 'aria-label': it.group || null }); nodes.push(chips); }
        chips.append(h('button', {
          class: `menu-item chip ${it.checked ? 'checked' : ''} ${it.mono ? 'mono' : ''}`.trim(), role, type: 'button',
          'aria-checked': String(!!it.checked), disabled: it.disabled, dataset: { key: it.key || `i${i}` },
          title: it.reason || it.desc || null, 'aria-description': it.desc || null,
          onclick: () => { if (it.keep) { it.action(); if (paint) paint(); } else { close(); it.action(); } },
        }, it.label));
        return;
      }
      nodes.push(h('button', {
        class: `menu-item pick ${it.checked ? 'checked' : ''} ${it.kind === 'check' ? 'switch' : ''}`.trim(), role, type: 'button',
        'aria-checked': checkable ? String(!!it.checked) : null, disabled: it.disabled, dataset: { key: it.key || `i${i}` },
        title: it.reason || it.title || null,
        onclick: () => { if (it.keep) { it.action(); if (paint) paint(); } else { close(); it.action(); } },
      },
      it.kind === 'check' ? h('span', { class: `pick-switch ${it.checked ? 'on' : ''}`, 'aria-hidden': 'true' })
        : h('span', { class: 'pick-check', 'aria-hidden': 'true' }, it.checked ? icon('check') : (it.icon ? icon(it.icon) : null)),
      h('span', { class: 'grow' }, h('span', { class: `pick-label ${it.mono ? 'mono' : ''}`.trim() }, it.label),
        it.desc || it.reason ? h('span', { class: 'pick-desc' }, it.reason || it.desc) : null),
      it.note ? h('span', { class: 'note' }, it.note) : null));
    });
    if (footer) nodes.push(h('div', { class: 'menu-sep', role: 'separator' }), footer);
    el.replaceChildren(...nodes);
    place(el, anchor); // measured with its content: opens upward from the input bar
    const again = keep && el.querySelector(`.menu-item[data-key="${CSS.escape(keep)}"]:not(:disabled)`);
    const first = again || el.querySelector('.menu-item.checked:not(:disabled)') || el.querySelector('.menu-item:not(:disabled)');
    if (first) first.focus();
  };
  el.addEventListener('keydown', (e) => {
    const btns = items();
    const i = btns.indexOf(document.activeElement);
    let next = null;
    const inRow = document.activeElement && document.activeElement.classList.contains('chip');
    if (e.key === 'ArrowDown') next = btns[i + 1] || btns[0];
    else if (e.key === 'ArrowUp') next = btns[i - 1] || btns[btns.length - 1];
    else if (inRow && e.key === 'ArrowRight') next = btns[i + 1] || null;
    else if (inRow && e.key === 'ArrowLeft') next = btns[i - 1] || null;
    else if (e.key === 'Home') next = btns[0];
    else if (e.key === 'End') next = btns[btns.length - 1];
    if (next) { e.preventDefault(); next.focus(); }
  });
  if (opener) opener.setAttribute('aria-expanded', 'true');
  close = pushLayer(el, () => { if (opener) opener.setAttribute('aria-expanded', 'false'); }, { returnFocus: opener });
  place(el, anchor);
  return { el, set, onPaint: (fn) => { paint = fn; }, close: () => close() };
}

// Simple pickers (a flat list of choices).
function picker(anchor, { title, items, footer }) {
  const m = menuPanel(anchor, { title });
  m.set(items, footer);
  return m;
}

// A test catalog's provenance (test profile only): kind, ID and version, e.g. a docs-derived demo.
const PROVENANCE_KIND = { 'docs-derived-demo': '依据官方文档的演示目录' };
function provenanceText(p) {
  if (!p) return '';
  return `${PROVENANCE_KIND[p.kind] || p.kind || '测试目录'} ${p.id || ''}${p.version ? ` · ${p.version}` : ''}`.trim();
}

function catalogFooter(s) {
  const cat = catalogOf(s);
  const label = HARNESS[s.harness].label;
  const when = cat.fetched_at ? clock(cat.fetched_at) : '';
  const number = cat.cli_version ? String(cat.cli_version).match(/\d+\.\d+[\w.-]*/) : null;
  const prov = cat.provenance || null;
  // A demo catalog says so (and what it is based on); a real one names the CLI version it came from.
  const source = prov ? `目录：${provenanceText(prov)}（测试数据）`
    : number ? `目录来自 ${label} ${number[0]}` : cat.cli_version ? `目录：${cat.cli_version}` : `目录来自 ${label}`;
  const line = cat.status === 'probing' ? `正在向 ${label} 读取目录…`
    : cat.error ? `读取目录失败：${cat.error}`
    : `${source}${when ? ` · ${when}` : ''}`;
  return h('div', { class: 'picker-foot' },
    h('div', { class: 'hint' }, line),
    prov && prov.scope ? h('div', { class: 'hint' }, prov.scope) : null,
    h('div', { class: 'hint' }, prov ? '这些条目只用于测试，不是当前账号的模型列表。' : '列表来自 CLI 自己的目录；能否使用以账号和 CLI 实际确认为准。'),
    h('button', { class: 'btn-plain', type: 'button', onclick: () => refreshCatalog(s) }, icon('refresh'), '重新读取'));
}

// Model, its effort levels and (Claude Code) Ultracode in one picker, as both harnesses do:
// Codex's /model picks "model and reasoning effort"; Claude Code's model button opens a picker
// with an Effort row and the Ultracode switch. Picking a model keeps the picker open on that
// model's levels; picking a level or flipping Ultracode closes it.
function openModelPicker(s, anchor, focus) {
  const sid = s.session_id;
  const panel = menuPanel(anchor, { title: `模型与思考强度 · ${HARNESS[s.harness].label}`, cls: 'model-picker' });
  let picked = null; // a model chosen in this picker, before the state stream reports it
  const draw = () => {
    const now = findSession(sid) || s;
    const cat = catalogOf(now);
    const st = settingsOf(now);
    const current = modelNow(now);
    const entry = picked ? findModel(cat, picked) : current.entry;
    const items = [{ head: '模型' }];
    if (now.harness === 'codex') {
      items.push({ key: 'm:', label: '使用 Codex 配置的默认模型', desc: '不单独指定，由 Codex 自己的配置决定', checked: picked === null && !st.chosen.model, keep: true, action: () => { picked = null; chooseSetting(now, { model: null }); } });
    }
    for (const m of cat.models || []) {
      const checked = picked ? picked === m.id : (st.chosen.model ? st.chosen.model === m.id : (now.harness === 'codex' ? false : !!(current.entry && current.entry.id === m.id)));
      const isCurrent = !st.chosen.model && !picked && current.entry && current.entry.id === m.id && now.harness === 'codex';
      const extras = [];
      if (now.harness === 'codex' && m.images === false) extras.push('不接受图片');
      items.push({
        key: `m:${m.id}`, label: m.label, desc: [m.description, ...extras].filter(Boolean).join(' · '), checked,
        title: m.resolved && m.resolved !== m.id ? `${m.id} → ${m.resolved}` : m.id,
        note: isCurrent ? '当前' : m.id,
        disabled: m.disabled, reason: m.disabled ? (m.description || '当前不可选') : null, keep: true,
        action: () => { picked = m.id; chooseSetting(now, { model: m.id }); },
      });
    }
    if (!(cat.models || []).length) items.push({ key: 'm:none', label: cat.status === 'probing' ? '正在读取…' : '没有可用的模型目录', disabled: true, action: () => {} });
    items.push('-', { head: entry ? `思考强度 · ${entry.label}` : '思考强度' });
    if (!entry) items.push({ text: '选择模型后显示它支持的强度' });
    else if (!entry.efforts.length) items.push({ text: `${entry.label} 的原生目录没有提供可选强度` });
    else {
      // The levels this model lists, by their own names, in one row; the selected one's own
      // description below it.
      const group = `思考强度 · ${entry.label}`;
      const def = entry.default_effort ? `模型默认：${entry.default_effort}` : `由 ${HARNESS[now.harness].label} 决定${st.actual.effort ? `（当前读回：${st.actual.effort}）` : '（未报告具体值）'}`;
      items.push({ key: 'e:', chip: true, group, label: '默认', desc: def, checked: !st.chosen.effort, action: () => chooseSetting(now, { effort: null }) });
      for (const level of entry.efforts) {
        items.push({ key: `e:${level}`, chip: true, group, label: level, mono: true, desc: effortHint(now, entry, level), checked: st.chosen.effort === level, action: () => chooseSetting(now, { effort: level }) });
      }
      const shown = st.chosen.effort && entry.efforts.includes(st.chosen.effort) ? st.chosen.effort : null;
      items.push({ text: shown ? `${shown}：${effortHint(now, entry, shown) || '（原生目录没有说明）'}` : def });
    }
    const u = ultracodeNow(now);
    if (u) {
      items.push('-');
      const reason = !u.live ? '连接后由 Claude Code 报告是否可用' : !u.available ? 'Claude Code 报告当前不可用（需要工作流已开启，且模型支持 xhigh）' : null;
      const checked = u.chosen === null ? u.on : u.chosen;
      items.push({
        key: 'u', kind: 'check', label: 'Ultracode', checked,
        desc: reason || 'Claude Code 为较大的任务规划工作流；不改变思考强度',
        disabled: !!reason, reason,
        action: () => chooseSetting(now, { claude_ultracode: !checked }),
      });
    }
    panel.set(items, catalogFooter(now));
    if (focus === 'effort') { const el = panel.el.querySelector('.menu-item.checked[data-key^="e:"]') || panel.el.querySelector('.menu-item[data-key^="e:"]'); if (el) el.focus(); focus = null; }
  };
  panel.onPaint(draw);
  draw();
}

// Kept for the development hook (#dev=effort): the same picker, focused on the levels.
function openEffortPicker(s, anchor) { openModelPicker(s, anchor, 'effort'); }

function openModePicker(s, anchor) {
  const cat = catalogOf(s);
  const st = settingsOf(s);
  const now = modeNow(s);
  const items = [];
  if (now.id && !(cat.modes || []).some((m) => m.id === now.id)) items.push({ head: `当前：${now.label}` });
  for (const m of cat.modes || []) {
    let available = m.available !== false;
    let reason = m.reason || null;
    if (m.id === 'auto') {
      const model = modelNow(s).entry;
      if (model && !model.auto_mode) { available = false; reason = '当前模型不支持自动模式'; }
    }
    const native = s.harness === 'codex' ? [m.approval, m.sandbox_mode].filter(Boolean).join(' · ') : m.id;
    items.push({ key: `p:${m.id}`, label: m.label, desc: [m.description, native].filter(Boolean).join(' — '), checked: (st.chosen.mode || now.id) === m.id, disabled: !available, reason, action: () => chooseSetting(s, { mode: m.id }) });
  }
  const label = HARNESS[s.harness].label;
  const reviewer = REVIEWER[st.actual.reviewer] || st.actual.reviewer;
  const native = nativeModeText(s);
  const foot = h('div', { class: 'picker-foot' },
    native ? h('div', { class: 'hint' }, `${label} 读回：${native}`) : null,
    h('div', { class: 'hint' }, s.harness === 'codex'
      ? '这些是 Codex 的审批方式与沙箱组合；完全访问（不审批、不设沙箱）不在 RepoBridge 中提供。'
      : `这些是 ${label} 自己的权限模式；跳过全部权限检查的模式不在 RepoBridge 中提供。`),
    s.harness === 'codex' && reviewer ? h('div', { class: 'hint' }, `审批由${reviewer}处理（Codex 自己的 approvals_reviewer 设置，RepoBridge 不改动）。`) : null);
  picker(anchor, { title: s.harness === 'codex' ? '权限 · Codex' : '权限模式 · Claude Code', items, footer: foot });
}

// ---------------------------------------------------------------- input bar controls

// The model button's text: the native model name, its effort level and (Claude) Ultracode, the
// way each harness labels its own model button.
function modelButtonText(s) {
  const m = modelNow(s);
  const parts = [m.label];
  if (m.entry && m.entry.efforts && m.entry.efforts.length) parts.push(effortNow(s).label);
  const u = ultracodeNow(s);
  if (u && (u.chosen === null ? u.on : u.chosen)) parts.push('Ultracode');
  return parts.join(' · ');
}

function renderControls(s) {
  const root = convEl;
  if (!root || !root._left || !root._right) return;
  ensureCatalog(s);
  const cat = catalogOf(s);
  const ready = cat.models && cat.models.length;
  const busy = S.pending.has(`settings:${s.session_id}`);
  const loading = cat.status === 'probing' && !ready;
  const unavailable = !ready ? (loading ? `正在向 ${HARNESS[s.harness].label} 读取模型目录…` : (cat.error ? `读取模型目录失败：${cat.error}` : '还没有模型目录')) : null;
  const pill = (fields, iconName, text, aria, onClick, extra = {}) => h('button', {
    class: `cpill ${extra.cls || ''}`.trim(), type: 'button', disabled: extra.disabled || busy,
    title: extra.title || fields.map((f) => fieldTitle(s, f, currentLabel(s, f))).join('\n\n'),
    'aria-label': aria, 'aria-haspopup': 'menu', 'aria-expanded': 'false',
    onclick: (e) => onClick(e.currentTarget),
  }, icon(iconName), h('span', { class: 'pill-text' }, text), icon('caret', 'pill-caret'));
  const noteEl = (note) => (note ? h('span', { class: `ctl-note ${note.tone}`, title: note.title }, note.text) : null);

  const modelFields = ['model', 'effort', ...(s.harness === 'claude-code' ? ['claude_ultracode'] : [])];
  const text = ready ? modelButtonText(s) : (loading ? '读取模型目录…' : '模型');
  const modelPill = pill(modelFields, 'spark', text, `模型与思考强度：${text}`, (a) => (ready ? openModelPicker(s, a) : refreshCatalog(s)),
    unavailable ? { cls: 'model', title: `${unavailable}${cat.error || !loading ? '（点击重新读取）' : ''}`, disabled: loading } : { cls: 'model' });
  const mode = modeNow(s);
  const modePill = pill(['mode'], 'shield', mode.label, `${s.harness === 'codex' ? '权限' : '权限模式'}：${mode.label}`, (a) => openModePicker(s, a),
    ready ? { cls: mode.id && mode.id !== 'default' && mode.id !== 'read-only' && mode.id !== 'workspace' ? 'mode accent' : 'mode' } : { cls: 'mode', disabled: true, title: unavailable });
  const modelNote = noteEl(controlNote(s, modelFields));
  const modeNote = noteEl(controlNote(s, ['mode']));
  const ctx = renderContextIndicator(s);
  // Rebuild only when something shown changed: replacing a control between mousedown and click
  // would swallow the click.
  const sig = [modePill, modeNote, ctx, modelNote, modelPill].map((el) => (el ? `${el.className}|${el.disabled}|${el.title}|${el.textContent}|${el.getAttribute('aria-label')}` : '-')).join('#');
  if (root._ctlSig === sig && root._left.firstChild === root._attachBtn && root._right.lastChild === root._send && !S.devOpen) return;
  root._ctlSig = sig;
  root._left.replaceChildren(...[root._attachBtn, root._cmdBtn, modePill, modeNote].filter(Boolean));
  root._right.replaceChildren(...[ctx, modelNote, modelPill, root._send].filter(Boolean));
  if (S.devOpen && ready) {
    // Development snapshots (#dev=model|effort|mode|context|commands): open once the controls exist.
    const which = S.devOpen;
    S.devOpen = null;
    const open = { model: () => openModelPicker(s, modelPill), effort: () => openEffortPicker(s, modelPill), mode: () => openModePicker(s, modePill), context: () => openContextPanel(s, ctx), commands: () => openCommandMenu(s, root._cmdBtn) }[which];
    if (open) queueMicrotask(open);
  }
}

// Why the input box's text was not sent (a refused "/…"): shown above the box, next to the draft
// it is about, until the draft changes or it is dismissed. A toast would cover the kept draft.
function composerNotice(sid, text) {
  if (!S.composerNotes) S.composerNotes = new Map();
  S.composerNotes.set(sid, { text, at: Date.now() });
  const s = findSession(sid);
  if (s) updateConvChrome(s, convFor(sid));
}

// A refused choice the user must notice (shown above the input box until dismissed), or null.
// Pending choices are shown next to their control instead.
function settingsStatus(s) {
  composerState();
  const st = settingsOf(s);
  for (const name of ['model', 'effort', 'mode', 'claude_ultracode']) {
    const rec = st.fields[name];
    if (rec && rec.state === 'failed' && !S.dismissed.has(`f:${s.session_id}:${name}:${rec.at}`)) {
      const tried = rec.attempted !== undefined ? `「${valueLabel(s, name, rec.attempted)}」` : '';
      return {
        tone: 'bad',
        text: `${FIELD_NAME[name]}${tried}没有生效${rec.error ? `：${rec.error}` : ''}。当前仍是「${currentLabel(s, name)}」。`,
        dismiss: `f:${s.session_id}:${name}:${rec.at}`,
      };
    }
  }
  return null;
}

// ---------------------------------------------------------------- attachments

function attachments(sid) {
  composerState();
  if (!S.attach.has(sid)) S.attach.set(sid, []);
  return S.attach.get(sid);
}

function fmtSize(n) {
  if (n >= 1 << 20) return `${(n / (1 << 20)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function renderAttachRow(sid) {
  const root = convEl;
  if (!root || !root._attRow || root.dataset.sid !== sid) return;
  const list = attachments(sid);
  root._attRow.hidden = !list.length;
  root._attRow.replaceChildren(...list.map((a) => h('div', { class: `att-chip ${a.error ? 'bad' : ''}`, title: a.error || `${a.name} · ${fmtSize(a.size || 0)}` },
    a.preview ? h('img', { src: a.preview, alt: '' }) : icon(a.kind === 'image' ? 'image' : 'file'),
    h('span', { class: 'att-name' }, a.name),
    a.uploading ? stGlyph({ tone: 'idle', glyph: 'spin' }) : h('span', { class: 'att-size' }, a.error ? '失败' : fmtSize(a.size || 0)),
    h('button', { class: 'att-x', type: 'button', title: '移除', 'aria-label': `移除 ${a.name}`, onclick: () => { list.splice(list.indexOf(a), 1); renderAttachRow(sid); updateConvChrome(findSession(sid), convFor(sid)); } }, icon('close')))));
}

function readDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取失败'));
    reader.readAsDataURL(file);
  });
}

async function uploadOne(sid, entry, body) {
  try {
    const meta = await api('POST', `/api/sessions/${sid}/attachments`, body);
    Object.assign(entry, meta, { uploading: false });
  } catch (e) {
    Object.assign(entry, { uploading: false, error: e.message || String(e) });
  }
  renderAttachRow(sid);
  updateConvChrome(findSession(sid), convFor(sid));
}

async function addFiles(sid, files) {
  const list = attachments(sid);
  for (const file of files) {
    if (list.length >= 10) { toast('一条消息最多 10 个附件', 'error'); break; }
    const entry = { name: file.name || (file.type.startsWith('image/') ? '粘贴的图片.png' : '附件'), kind: file.type.startsWith('image/') ? 'image' : 'file', size: file.size, uploading: true };
    list.push(entry);
    renderAttachRow(sid);
    let url;
    try { url = await readDataUrl(file); } catch (e) { Object.assign(entry, { uploading: false, error: '无法读取这个文件' }); renderAttachRow(sid); continue; }
    if (entry.kind === 'image' && file.size < (8 << 20)) entry.preview = url;
    const data = url.slice(url.indexOf(',') + 1);
    await uploadOne(sid, entry, { name: entry.name, data });
  }
}

async function addPaths(sid, paths) {
  const list = attachments(sid);
  for (const path of paths) {
    if (list.length >= 10) { toast('一条消息最多 10 个附件', 'error'); break; }
    const entry = { name: path.split('/').pop(), kind: 'file', size: 0, uploading: true };
    list.push(entry);
    renderAttachRow(sid);
    await uploadOne(sid, entry, { name: entry.name, path });
  }
}

async function pickFiles(sid) {
  if (hasNative('pick_files')) {
    try {
      const paths = await nativeCall('pick_files', {});
      if (paths && paths.length) await addPaths(sid, paths);
    } catch (e) { fail(e); }
    return;
  }
  const input = h('input', { type: 'file', multiple: true, style: 'display:none' });
  input.addEventListener('change', () => { if (input.files && input.files.length) addFiles(sid, [...input.files]); input.remove(); });
  document.body.append(input);
  input.click();
}

function attachMenu(s, anchor) {
  const sid = s.session_id;
  menu(anchor, [
    { icon: 'image', label: '添加图片或文件…', note: '也可粘贴或拖入', action: () => pickFiles(sid) },
    { icon: 'search', label: '引用项目文件', note: '@', action: () => insertAtCaret(sid, '@') },
  ]);
}

function insertAtCaret(sid, text, atStart = false) {
  const root = convEl;
  if (!root || root.dataset.sid !== sid || !root._ta) return;
  const ta = root._ta;
  ta.focus();
  if (atStart) { if (ta.value) return; ta.value = text; ta.setSelectionRange(1, 1); }
  else {
    const at = ta.selectionStart;
    const pad = at > 0 && !/\s$/.test(ta.value.slice(0, at)) ? ' ' : '';
    ta.setRangeText(pad + text, at, ta.selectionEnd, 'end');
  }
  ta.dispatchEvent(new Event('input'));
}

// ---------------------------------------------------------------- @ files and / commands

let mentionTimer = null;
function updateMention(sid) {
  const root = convEl;
  if (!root || root.dataset.sid !== sid || !root._ta || !root._pop) return;
  const s = findSession(sid);
  const ta = root._ta;
  const before = ta.value.slice(0, ta.selectionStart);
  const file = /(^|\s)@("?)([^\s"@]*)$/.exec(before);
  const cmd = s ? /^\/([\w:.-]*)$/.exec(before) : null;
  if (file) {
    const start = before.length - file[3].length - file[2].length - 1;
    clearTimeout(mentionTimer);
    mentionTimer = setTimeout(async () => {
      const q = file[3];
      composerState();
      const key = `${sid}:${q}`;
      let found = S.fileCache.get(key);
      if (!found) {
        try { found = await api('GET', `/api/sessions/${sid}/files?q=${encodeURIComponent(q)}`); } catch (e) { found = []; }
        S.fileCache.set(key, found);
        setTimeout(() => S.fileCache.delete(key), 15000);
      }
      if (!convEl || convEl._ta !== ta) return;
      showPop(sid, found.slice(0, 8).map((f) => ({ label: f.name, desc: f.path, value: `@${/\s/.test(f.path) ? `"${f.path}"` : f.path} ` })), start, '项目文件', q ? `没有匹配“${q}”的文件` : '项目里没有文件');
    }, 90);
    return;
  }
  if (cmd) {
    const list = slashEntries(s, cmd[1]).slice(0, 10);
    showPop(sid, list, 0, `${HARNESS[s.harness].label} 命令`, s.harness === 'codex' ? '对话视图只接入了 /model、/permissions、/compact、/status、/mention' : '没有匹配的命令');
    return;
  }
  hidePop();
}

function showPop(sid, entries, start, title, empty) {
  const root = convEl;
  if (!root || !root._pop) return;
  root._popState = { entries, start, active: 0 };
  root._pop.hidden = false;
  const paint = () => {
    const st = root._popState;
    root._pop.replaceChildren(h('div', { class: 'menu-head' }, title), ...(st.entries.length ? st.entries.map((e, i) => h('button', {
      class: `menu-item ${i === st.active ? 'active' : ''} ${e.disabled ? 'disabled' : ''}`.trim(), type: 'button', tabindex: '-1',
      role: 'option', 'aria-selected': String(i === st.active), 'aria-disabled': e.disabled ? 'true' : null,
      onmousedown: (ev) => { ev.preventDefault(); pickPop(sid, i); },
    }, h('span', { class: 'grow' }, h('span', { class: 'pick-label mono' }, e.label), e.desc ? h('span', { class: 'pick-desc' }, e.desc) : null), e.note ? h('span', { class: 'note' }, e.note) : null))
      : [h('div', { class: 'hint', style: 'padding:6px 10px' }, empty)]));
  };
  root._popPaint = paint;
  paint();
}

function hidePop() {
  const root = convEl;
  if (!root || !root._pop) return;
  root._pop.hidden = true;
  root._popState = null;
}

function pickPop(sid, index) {
  const root = convEl;
  const st = root && root._popState;
  if (!st || !st.entries[index]) return;
  const entry = st.entries[index];
  if (entry.disabled) return;
  const ta = root._ta;
  const end = ta.selectionStart;
  // A command that is an action here (compact, model, …): the typed "/…" is removed, the rest of
  // the draft stays, and the action runs; nothing is sent.
  ta.setRangeText(entry.action ? '' : entry.value, st.start, end, 'end');
  hidePop();
  ta.dispatchEvent(new Event('input'));
  ta.focus();
  if (entry.action) runSlashAction(findSession(sid), entry.action);
}

function popKey(e, sid) {
  const root = convEl;
  const st = root && root._popState;
  if (!st || root._pop.hidden) return false;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const n = st.entries.length || 1;
    st.active = (st.active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
    root._popPaint();
    return true;
  }
  if ((e.key === 'Enter' || e.key === 'Tab') && st.entries.length) { e.preventDefault(); pickPop(sid, st.active); return true; }
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); hidePop(); return true; }
  return false;
}

// ---------------------------------------------------------------- message delivery
// Every sent message is tracked by its client_id: the ID in the /send request, the user item
// `user:<client_id>` and the backend's durable receipt (docs/EXISTING_SESSIONS_API.md, "message
// receipts"). Only the receipt or the CLI decides what happened:
// - queued / sending: still open; the text and attachments stay tracked.
// - not_sent: definitely not submitted. Put back into the input box when it is empty, otherwise
//   kept in a "没有发出" list above it; never over a new draft, never twice, never resent.
// - sent: accepted by the CLI (not "the turn succeeded"); an untouched kept copy is taken out.
// - unknown: may have reached the CLI. Kept apart as "发送结果待确认"; never treated as unsent,
//   never put back as a retry, never resent. Only a receipt or the user's own check resolves it.
// A missing receipt, a failed query or an ended process is never proof either way.
// Sent is final: once any source (the /send answer, an event, a history page, a receipt query)
// confirms a message, an older queued / sending / unknown / not_sent copy of it that arrives later
// changes nothing — not the cached item, the bubble, the kept copies or the send button. That is
// the only ordering; the other states are not ranked. The functions below hold no DOM state
// (tested in Node).

function unsentStore() {
  // inflight: cid -> entry; held: sid -> [not_sent entry]; uncertain: sid -> [unknown entry];
  // placed: cid -> entry put back into the box.
  // Two separate records: confirmed (session + cid -> the sent receipt): the CLI accepted it;
  // handled (cid): its one recovery step (put back, kept above the box, removed) was taken.
  return { inflight: new Map(), held: new Map(), uncertain: new Map(), placed: new Map(), handled: new Set(), confirmed: new Map() };
}

// The client_id of a user item or receipt (`client_id`, or the `user:<client_id>` item ID).
function itemClientId(item) {
  if (!item) return null;
  if (item.client_id) return String(item.client_id);
  return typeof item.id === 'string' && item.id.startsWith('user:') ? item.id.slice(5) : null;
}

const confirmKey = (sid, cid) => `${sid}\n${cid}`;

function unsentConfirm(st, sid, cid, delivery) {
  const known = st.confirmed.get(confirmKey(sid, cid));
  if (!known || (!known.delivery && delivery)) st.confirmed.set(confirmKey(sid, cid), { delivery: delivery || null });
}

function unsentConfirmed(st, sid, cid) {
  return st.confirmed.has(confirmKey(sid, cid));
}

// How a user item is cached and shown. A sent item is recorded as confirmed; an item for a
// confirmed message that says anything else is an older copy and is shown as sent.
function deliveryView(st, sid, item) {
  const cid = item && (!item.type || item.type === 'user') ? itemClientId(item) : null;
  if (!cid) return item;
  if (deliveryOutcome(item) === 'sent') { unsentConfirm(st, sid, cid, item.delivery); return item; }
  const known = st.confirmed.get(confirmKey(sid, cid));
  if (!known) return item;
  const view = { ...item, status: 'sent' };
  if (known.delivery) view.delivery = known.delivery; else delete view.delivery;
  return view;
}

// What a receipt or user item says: 'pending' | 'not_sent' | 'sent' | 'unknown' | null.
function deliveryOutcome(item) {
  if (!item) return null;
  const state = item.delivery && item.delivery.state;
  if (state === 'queued' || state === 'sending') return 'pending';
  if (state === 'not_sent' || state === 'sent' || state === 'unknown') return state;
  return { sending: 'pending', sent: 'sent', failed: 'not_sent', unknown: 'unknown' }[item.status] || null;
}

// Returns false when the message was already confirmed (its event outran the /send answer).
function unsentTrack(st, entry) {
  if (unsentConfirmed(st, entry.sid, entry.clientId)) return false;
  st.inflight.set(entry.clientId, entry);
  return true;
}

function takeUncertain(st, cid) {
  for (const [sid, list] of st.uncertain) {
    const e = list.find((x) => x.clientId === cid);
    if (e) { st.uncertain.set(sid, list.filter((x) => x !== e)); return e; }
  }
  return null;
}

// Definitely not sent. `box` describes that session's input box now: { visible, draft, attIds }.
function unsentFail(st, sid, cid, box) {
  if (unsentConfirmed(st, sid, cid) || st.handled.has(cid)) return null;
  const e = st.inflight.get(cid) || takeUncertain(st, cid);
  if (!e) return null;
  st.inflight.delete(cid);
  st.handled.add(cid);
  if (box.visible && !box.draft.trim() && !box.attIds.length) {
    st.placed.set(cid, e);
    return { to: 'box', entry: e };
  }
  st.held.set(e.sid, [...(st.held.get(e.sid) || []), e]);
  return { to: 'held', entry: e, visible: box.visible };
}

// Result unknown. `info`: { reason, message, receipt } — receipt=true when the backend holds an
// unknown receipt (it then refuses new sends), false when RepoBridge has no receipt to consult.
// `item` adopts a receipt seen after a reload, when nothing is tracked for it here.
function unsentUnknown(st, sid, cid, info, item) {
  if (unsentConfirmed(st, sid, cid) || st.handled.has(cid)) return null;
  let e = st.inflight.get(cid);
  const tracked = !!e;
  if (e) st.inflight.delete(cid);
  else {
    for (const list of st.uncertain.values()) {
      const known = list.find((x) => x.clientId === cid);
      if (known) { Object.assign(known, info); return { to: 'uncertain', entry: known, updated: true }; }
    }
    if (!item) return null;
    e = { sid, clientId: cid, text: item.text || '', atts: (item.attachments || []).filter((a) => a.id), at: 0 };
  }
  Object.assign(e, info);
  st.uncertain.set(e.sid, [...(st.uncertain.get(e.sid) || []), e]);
  return { to: 'uncertain', entry: e, adopted: !tracked };
}

// Accepted by the CLI (now, or as a late receipt). Remembered even when nothing is kept for it
// here (e.g. first seen after a reload), so an older copy arriving later cannot undo it.
function unsentDelivered(st, sid, cid, box, delivery) {
  unsentConfirm(st, sid, cid, delivery);
  if (st.inflight.delete(cid)) return { to: 'delivered' };
  const u = takeUncertain(st, cid);
  if (u) return { to: 'resolved', entry: u };
  for (const [hsid, list] of st.held) {
    const e = list.find((x) => x.clientId === cid);
    if (e) { st.held.set(hsid, list.filter((x) => x !== e)); return { to: 'unheld', entry: e }; }
  }
  const p = st.placed.get(cid);
  if (!p) return null;
  st.placed.delete(cid);
  // Only an untouched copy is taken out of the box; an edited one is the user's text now.
  return box.draft === p.text ? { to: 'cleared', entry: p } : { to: 'edited', entry: p };
}

function unsentTake(st, sid, cid) {
  const list = st.held.get(sid) || [];
  const e = list.find((x) => x.clientId === cid) || null;
  if (e) st.held.set(sid, list.filter((x) => x !== e));
  return e;
}

// The user checked the history and removes a copy RepoBridge holds no receipt for. A copy backed by
// an unknown receipt cannot be dismissed here: only native evidence resolves it.
function unsentDismiss(st, sid, cid) {
  const list = st.uncertain.get(sid) || [];
  const e = list.find((x) => x.clientId === cid && !x.receipt) || null;
  if (e) { st.uncertain.set(sid, list.filter((x) => x !== e)); st.handled.add(cid); }
  return e;
}

// A send in this session must wait while the backend holds an unknown receipt (delivery_unknown).
function unsentBlocking(st, sid) {
  return (st.uncertain.get(sid) || []).find((x) => x.receipt) || null;
}

// The user sent from the box again: copies put back there are theirs from now on.
function unsentReleaseBox(st, sid) {
  for (const [cid, e] of st.placed) if (e.sid === sid) st.placed.delete(cid);
}

function mergeAttachments(list, atts) {
  const added = atts.filter((a) => !(a.id && list.some((x) => x.id === a.id)));
  list.push(...added);
  return added;
}

// ---------------------------------------------------------------- composer

// A key that belongs to an input method composition (pinyin, kana…). WebKit — the native window —
// delivers the Enter or Escape that confirms or cancels a candidate with isComposing=false and
// keyCode 229, so both count. Text fields never act on such a key.
function composingKey(e) {
  return !!(e && (e.isComposing || e.keyCode === 229));
}

function buildComposer(s) {
  const sid = s.session_id;
  const label = HARNESS[s.harness].label;
  const ta = h('textarea', { rows: '1', 'aria-label': `给 ${label} 发消息` });
  ta.value = S.drafts.get(sid) || '';
  const send = h('button', { class: 'send-btn', type: 'button' });
  const status = h('div', { class: 'conv-status', 'aria-live': 'polite' });
  const pop = h('div', { class: 'menu mention-pop', hidden: true, role: 'listbox' });
  const attRow = h('div', { class: 'att-row', hidden: true });
  const attachBtn = h('button', { class: 'icon-btn', type: 'button', title: '添加附件、引用文件', 'aria-label': '添加附件、引用文件', 'aria-haspopup': 'menu', 'aria-expanded': 'false', onclick: (e) => attachMenu(findSession(sid), e.currentTarget) }, icon('clip'));
  // The harness's own commands and context actions, the way both harnesses open them with "/".
  const cmdBtn = h('button', { class: 'icon-btn', type: 'button', title: `${label} 命令与上下文（也可输入 /）`, 'aria-label': `${label} 命令与上下文`, 'aria-haspopup': 'menu', 'aria-expanded': 'false', onclick: (e) => openCommandMenu(findSession(sid), e.currentTarget) }, icon('slash'));
  const left = h('div', { class: 'cb-left' });
  const right = h('div', { class: 'cb-right' });
  const box = h('div', { class: 'composer' }, pop, attRow, ta, h('div', { class: 'composer-bar' }, left, right));
  const unsent = h('div', { class: 'unsent-list', hidden: true, role: 'region', 'aria-label': '没有发出的消息' });
  const wrap = h('div', { class: 'composer-wrap' }, status, unsent, box);
  const root = convRoot();
  Object.assign(root, { _ta: ta, _send: send, _status: status, _box: box, _pop: pop, _attRow: attRow, _attachBtn: attachBtn, _cmdBtn: cmdBtn, _left: left, _right: right, _unsent: unsent, _popState: null });
  ta.addEventListener('input', () => {
    S.drafts.set(sid, ta.value);
    if (S.composerNotes) S.composerNotes.delete(sid); // a refusal is about the text as it was
    autosize(ta); updateMention(sid); updateConvChrome(findSession(sid), convFor(sid));
  });
  ta.addEventListener('click', () => updateMention(sid));
  ta.addEventListener('blur', () => setTimeout(hidePop, 120));
  ta.addEventListener('keydown', (e) => {
    if (composingKey(e)) return;
    if (popKey(e, sid)) return;
    const now = findSession(sid);
    const running = !!(now && now.turn);
    if (e.key === 'Enter' && !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey) { e.preventDefault(); if (!running) sendFromComposer(sid); }
    else if (e.key === 'Escape' && running) { e.preventDefault(); e.stopPropagation(); interruptTurn(sid); }
  });
  ta.addEventListener('paste', (e) => {
    const dt = e.clipboardData;
    if (!dt) return;
    const files = [...dt.items].filter((x) => x.kind === 'file').map((x) => x.getAsFile()).filter(Boolean);
    if (files.length && !dt.getData('text/plain')) { e.preventDefault(); addFiles(sid, files); }
  });
  const dragOn = (e) => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { e.preventDefault(); box.classList.add('dropping'); } };
  box.addEventListener('dragover', dragOn);
  box.addEventListener('dragenter', dragOn);
  box.addEventListener('dragleave', (e) => { if (!box.contains(e.relatedTarget)) box.classList.remove('dropping'); });
  box.addEventListener('drop', (e) => { box.classList.remove('dropping'); if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); addFiles(sid, [...e.dataTransfer.files]); } });
  send.addEventListener('click', () => { const now = findSession(sid); if (now && now.turn) interruptTurn(sid); else sendFromComposer(sid); });
  setTimeout(() => { autosize(ta); renderAttachRow(sid); renderUnsent(sid); }, 0);
  return wrap;
}

// The kept copies for one session, above its input box. Every button is the user's own action.
function renderUnsent(sid) {
  const root = convEl;
  if (!root || !root._unsent || root.dataset.sid !== sid) return;
  const held = S.unsent.held.get(sid) || [];
  const uncertain = S.unsent.uncertain.get(sid) || [];
  root._unsent.hidden = !held.length && !uncertain.length;
  const preview = (e) => {
    const text = e.text.trim();
    return h('div', { class: 'unsent-text selectable', title: text }, text || '（只有附件）');
  };
  const copyBtn = (e) => h('button', { class: 'icon-btn small', type: 'button', title: '复制文字', 'aria-label': '复制这条消息的文字', onclick: () => copyText(e.text, '已复制') }, icon('copy'));
  root._unsent.replaceChildren(
    ...uncertain.map((e) => h('div', { class: 'unsent-item uncertain', dataset: { cid: e.clientId }, role: 'status' },
      icon('info'),
      h('div', { class: 'unsent-body' },
        h('div', { class: 'unsent-head' }, '发送结果待确认', e.atts.length ? h('span', { class: 'hint' }, ` · ${e.atts.length} 个附件`) : null),
        h('div', { class: 'unsent-why' }, e.message || '这条消息可能已经送达，但没有收到确认。请核对历史，不要重复发送。'),
        preview(e)),
      h('div', { class: 'unsent-actions' },
        h('button', { class: 'btn btn-small', type: 'button', title: '重新查询接收记录，并重新读取原生历史', onclick: (ev) => recheckDelivery(sid, e.clientId, ev.currentTarget) }, '刷新结果'),
        copyBtn(e),
        e.receipt ? null : h('button', { class: 'icon-btn small', type: 'button', title: '已在历史中核对过：移除这份留存（不发送、不撤回任何内容）', 'aria-label': '移除这份留存', onclick: (ev) => confirmPopover(ev.currentTarget, {
          title: '移除这份留存？', text: '只移除 RepoBridge 里保留的副本，不会发送、重发或撤回任何内容。请先在历史中核对它是否已经送达。', confirm: '移除', danger: true,
          onConfirm: () => { unsentDismiss(S.unsent, sid, e.clientId); renderUnsent(sid); updateConvChrome(findSession(sid), convFor(sid)); },
        }) }, icon('close'))))),
    ...held.map((e) => h('div', { class: 'unsent-item', dataset: { cid: e.clientId } },
      icon('warning'),
      h('div', { class: 'unsent-body' },
        h('div', { class: 'unsent-head' }, '没有发出的消息', e.atts.length ? h('span', { class: 'hint' }, ` · ${e.atts.length} 个附件`) : null),
        preview(e)),
      h('div', { class: 'unsent-actions' },
        h('button', { class: 'btn btn-small', type: 'button', title: '放到输入框里；输入框已有文字时接在后面，不覆盖', onclick: () => putBackUnsent(sid, e.clientId) }, '放回输入框'),
        copyBtn(e),
        h('button', { class: 'icon-btn small', type: 'button', title: '丢弃这条没有发出的消息', 'aria-label': '丢弃这条没有发出的消息', onclick: (ev) => confirmPopover(ev.currentTarget, {
          title: '丢弃这条消息？', text: '它没有发给 CLI。丢弃后无法从 RepoBridge 找回（可以先复制文字）。', confirm: '丢弃', danger: true,
          onConfirm: () => { unsentTake(S.unsent, sid, e.clientId); renderUnsent(sid); },
        }) }, icon('close'))))));
}

function putBackUnsent(sid, cid) {
  const root = convEl;
  if (!root || root.dataset.sid !== sid || !root._ta) return;
  const e = unsentTake(S.unsent, sid, cid);
  if (!e) return;
  S.unsent.placed.set(cid, e); // a late delivery report can still take an untouched copy back out
  const ta = root._ta;
  ta.value = ta.value.trim() ? `${ta.value.replace(/\s+$/, '')}\n\n${e.text}` : e.text;
  S.drafts.set(sid, ta.value);
  mergeAttachments(attachments(sid), e.atts);
  autosize(ta);
  renderAttachRow(sid);
  renderUnsent(sid);
  updateConvChrome(findSession(sid), convFor(sid));
  ta.focus();
}

// ---------------------------------------------------------------- native questions and forms

function questionCard(s, it, answer) {
  const codex = it.answer_key === 'id';
  const picked = new Map();
  const typed = new Map();
  const submit = h('button', { class: 'btn btn-primary btn-small', type: 'button', disabled: true }, '提交回答');
  const questions = it.questions || [];
  const keyOf = (q) => (codex ? q.id : q.question);
  const valuesOf = (q) => {
    const vals = [...(picked.get(keyOf(q)) || [])];
    const t = (typed.get(keyOf(q)) || '').trim();
    if (t) vals.push(t);
    return vals;
  };
  const refresh = () => {
    const answered = questions.filter((q) => valuesOf(q).length).length;
    submit.disabled = codex ? answered === 0 : answered < questions.length;
  };
  const blocks = questions.map((q) => {
    const multi = !!q.multiSelect;
    const opts = h('div', { class: 'q-opts' }, (q.options || []).map((o) => {
      const b = h('button', { class: 'btn btn-small', type: 'button', 'aria-pressed': 'false', title: o.description || null }, o.label);
      b.addEventListener('click', () => {
        const cur = picked.get(keyOf(q)) || [];
        const next = multi ? (cur.includes(o.label) ? cur.filter((x) => x !== o.label) : [...cur, o.label]) : (cur[0] === o.label ? [] : [o.label]);
        picked.set(keyOf(q), next);
        for (const other of opts.querySelectorAll('button')) other.setAttribute('aria-pressed', String(next.includes(other.textContent)));
        refresh();
      });
      return b;
    }));
    const allowText = codex ? (q.other || !(q.options || []).length) : true;
    const input = allowText ? h('input', {
      class: 'input q-other', type: q.secret ? 'password' : 'text', autocomplete: 'off',
      placeholder: (q.options || []).length ? '其他回答（可选）' : '输入回答', 'aria-label': q.question,
    }) : null;
    if (input) input.addEventListener('input', () => { typed.set(keyOf(q), input.value); refresh(); });
    return h('div', { class: 'q' },
      q.header ? h('div', { class: 'q-head' }, q.header) : null,
      h('div', { class: 'q-title selectable' }, q.question),
      (q.options || []).length ? opts : null,
      input,
      q.secret ? h('div', { class: 'hint' }, '这个回答只发给 CLI，RepoBridge 不保存。') : null);
  });
  submit.addEventListener('click', () => {
    if (codex) answer('answer', Object.fromEntries(questions.map((q) => [q.id, valuesOf(q)])));
    else answer('allow', Object.fromEntries(questions.map((q) => [q.question, valuesOf(q).join(', ')])));
  });
  return [...blocks, h('div', { class: 'actions' }, h('button', { class: 'btn btn-small', type: 'button', onclick: () => answer('deny') }, '不回答'), submit)];
}

function formCard(s, it, answer) {
  const form = it.form || { mode: 'form', fields: [] };
  const out = [];
  const opt = (id) => (it.options || []).find((o) => o.id === id) || { id, label: id };
  if (form.mode === 'url') {
    out.push(h('div', { class: 'mono selectable', style: 'font:12.5px var(--mono);overflow-wrap:anywhere' }, form.url),
      h('div', { class: 'hint' }, '在浏览器里完成后，回到这里点“已完成”。RepoBridge 不会代你填写或登录。'),
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-small', type: 'button', onclick: () => answer('cancel') }, opt('cancel').label),
        h('button', { class: 'btn btn-small', type: 'button', onclick: () => answer('decline') }, opt('decline').label),
        h('button', { class: 'btn btn-small', type: 'button', onclick: () => openLink(form.url) }, icon('external'), '打开链接'),
        h('button', { class: 'btn btn-primary btn-small', type: 'button', onclick: () => answer('accept') }, opt('accept').label)));
    return out;
  }
  const values = {};
  const grid = h('div', { class: 'form-grid' });
  for (const f of form.fields || []) {
    let input;
    if (f.type === 'boolean') {
      input = h('input', { type: 'checkbox', checked: f.default === true });
      values[f.name] = f.default === true;
      input.addEventListener('change', () => { values[f.name] = input.checked; });
    } else if (f.choices && f.choices.length) {
      input = h('select', { class: 'input' }, f.required ? null : h('option', { value: '' }, '（不填）'), f.choices.map((c) => h('option', { value: c.value, selected: f.default === c.value }, c.label)));
      values[f.name] = input.value;
      input.addEventListener('change', () => { values[f.name] = input.value; });
    } else {
      const type = f.type === 'number' || f.type === 'integer' ? 'number' : ({ email: 'email', uri: 'url', date: 'date' }[f.format] || 'text');
      input = h('input', { class: 'input', type, value: f.default ?? '', min: f.minimum ?? null, max: f.maximum ?? null, step: f.type === 'integer' ? '1' : null });
      values[f.name] = input.value;
      input.addEventListener('input', () => { values[f.name] = input.value; });
    }
    grid.append(h('label', { class: 'form-row' }, h('span', { class: 'form-label' }, f.title, f.required ? h('span', { class: 'req' }, ' *') : null), input,
      f.description ? h('span', { class: 'hint' }, f.description) : null));
  }
  out.push(grid, h('div', { class: 'actions' },
    h('button', { class: 'btn btn-small', type: 'button', onclick: () => answer('cancel') }, opt('cancel').label),
    h('button', { class: 'btn btn-small', type: 'button', onclick: () => answer('decline') }, opt('decline').label),
    h('button', { class: 'btn btn-primary btn-small', type: 'button', onclick: () => answer('accept', { ...values }) }, opt('accept').label)));
  return out;
}
