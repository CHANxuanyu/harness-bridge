'use strict';
/* Conversation composer: the input box, attachments, @ file references, / commands, and the
   model / reasoning-effort / permission-mode selectors.

   Options come only from the harness's own catalog (S.state.catalogs: Claude Code's initialize
   response, Codex's model/list). A choice goes to the App's settings API, which applies it with
   the harness's own requests; the selectors then show what the harness reported back, with a
   marker while a choice is only selected, being applied, or was refused. Loaded before app.js
   and uses its helpers (h, icon, api, S, …) only when called. */

const EFFORT_LABEL = { none: '关闭', minimal: '最低', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高', ultra: '极高' };
const FIELD_NAME = { model: '模型', effort: '思考强度', mode: '权限模式' };
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
  return { chosen: st.chosen || {}, fields: st.fields || {}, actual: st.actual || {}, notices: st.notices || [], turn_model: st.turn_model };
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
  return { level, label: level ? (EFFORT_LABEL[level] || level) : '默认' };
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

function fieldMark(rec) {
  if (!rec || !rec.state || rec.state === 'confirmed' || rec.state === 'default') return null;
  if (rec.state === 'applying') return stGlyph({ tone: 'idle', glyph: 'spin' });
  if (rec.state === 'failed') return h('span', { class: 'fmark bad', 'aria-hidden': 'true' }, '!');
  return h('span', { class: 'fmark ring', 'aria-hidden': 'true' });
}

function valueLabel(s, name, value) {
  if (value === null || value === undefined) return '默认';
  if (name === 'model') { const m = findModel(catalogOf(s), value); return m ? m.label : value; }
  if (name === 'effort') return EFFORT_LABEL[value] || value;
  const m = (catalogOf(s).modes || []).find((x) => x.id === value);
  return m ? m.label : value;
}

function fieldStateText(s, name) {
  // Describes the last choice for this field; a refused choice names what was refused.
  const st = settingsOf(s);
  const rec = st.fields[name];
  if (!rec || !rec.state) return st.chosen[name] === undefined ? 'CLI 默认' : '';
  if (rec.state === 'failed') return `切换到「${valueLabel(s, name, rec.attempted)}」没有生效，仍是当前值`;
  return FIELD_STATE[rec.state] || rec.state;
}

function fieldTitle(s, name, valueLabel) {
  const st = settingsOf(s);
  const rec = st.fields[name];
  const lines = [`${FIELD_NAME[name]}：${valueLabel}`];
  if (rec && rec.state) {
    lines.push(fieldStateText(s, name));
    if (rec.note) lines.push(rec.note);
    if (rec.state === 'failed' && rec.error) lines.push(rec.error);
  } else lines.push(st.chosen[name] === undefined ? `未单独设置，使用 ${HARNESS[s.harness].label} 自己的默认值` : '');
  const src = (st.actual.sources || {})[name];
  if (src) lines.push(`${st.actual.live ? '当前值' : '上次连接时的值'}来自 ${SOURCE_TEXT[src] || src}`);
  return lines.filter(Boolean).join('\n');
}

function chooseSetting(s, changes) {
  const sid = s.session_id;
  guarded(`settings:${sid}`, async () => {
    const view = await api('POST', `/api/sessions/${sid}/settings`, changes);
    const fresh = (view.notices || []).filter((n) => !S.dismissed.has(`n:${sid}:${n.at}`));
    for (const n of fresh.slice(-2)) { S.dismissed.add(`n:${sid}:${n.at}`); toast(n.text); }
  });
}

// ---------------------------------------------------------------- pickers

function picker(anchor, { title, items, footer }) {
  const el = h('div', { class: 'menu picker', role: 'menu', 'aria-label': title });
  let close = () => {};
  if (title) el.append(h('div', { class: 'menu-head' }, title));
  for (const it of items) {
    if (it === '-') { el.append(h('div', { class: 'menu-sep' })); continue; }
    if (it.head) { el.append(h('div', { class: 'menu-head' }, it.head)); continue; }
    el.append(h('button', {
      class: `menu-item pick ${it.checked ? 'checked' : ''}`, role: 'menuitemradio', 'aria-checked': String(!!it.checked),
      type: 'button', disabled: it.disabled, title: it.reason || it.desc || null,
      onclick: () => { close(); it.action(); },
    }, h('span', { class: 'pick-check' }, it.checked ? icon('check') : null),
    h('span', { class: 'grow' }, h('span', { class: 'pick-label' }, it.label), it.desc || it.reason ? h('span', { class: 'pick-desc' }, it.reason || it.desc) : null),
    it.note ? h('span', { class: 'note' }, it.note) : null));
  }
  if (footer) el.append(h('div', { class: 'menu-sep' }), footer);
  el.addEventListener('keydown', (e) => {
    const btns = [...el.querySelectorAll('.menu-item:not(:disabled)')];
    const i = btns.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); (btns[i + 1] || btns[0]).focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); (btns[i - 1] || btns[btns.length - 1]).focus(); }
  });
  close = pushLayer(el);
  place(el, anchor);
  const first = el.querySelector('.menu-item.checked:not(:disabled)') || el.querySelector('.menu-item:not(:disabled)');
  if (first) first.focus();
}

function catalogFooter(s) {
  const cat = catalogOf(s);
  const label = HARNESS[s.harness].label;
  const when = cat.fetched_at ? clock(cat.fetched_at) : '';
  const line = cat.status === 'probing' ? `正在向 ${label} 读取目录…`
    : cat.error ? `读取目录失败：${cat.error}`
    : `目录来自 ${label}${cat.cli_version ? ` ${(String(cat.cli_version).match(/\d+\.\d+[\w.-]*/) || [cat.cli_version])[0]}` : ''}${when ? ` · ${when}` : ''}`;
  return h('div', { class: 'picker-foot' },
    h('div', { class: 'hint' }, line),
    h('div', { class: 'hint' }, '列表来自 CLI 自己的目录；能否使用以账号和 CLI 实际确认为准。'),
    h('button', { class: 'btn-plain', type: 'button', onclick: () => refreshCatalog(s) }, icon('refresh'), '重新读取'));
}

function openModelPicker(s, anchor) {
  const cat = catalogOf(s);
  const st = settingsOf(s);
  const now = modelNow(s);
  const items = [];
  if (s.harness === 'codex') items.push({ label: '使用 Codex 配置的默认模型', desc: '不单独指定，由 Codex 自己的配置决定', checked: !st.chosen.model, action: () => chooseSetting(s, { model: null }) });
  for (const m of cat.models || []) {
    const current = !!(now.entry && now.entry.id === m.id);
    // With no explicit choice only the "default" row is ticked; the model it resolves to says so.
    const checked = st.chosen.model ? st.chosen.model === m.id : (s.harness === 'codex' ? false : current);
    const extras = [];
    if (m.efforts && m.efforts.length) extras.push(`思考 ${m.efforts.map((e) => EFFORT_LABEL[e] || e).join('/')}`);
    if (s.harness === 'codex' && m.images === false) extras.push('不接受图片');
    items.push({
      label: m.label, desc: [m.description, extras.join(' · ')].filter(Boolean).join(' — '), checked,
      note: !st.chosen.model && current && s.harness === 'codex' ? '当前' : null,
      disabled: m.disabled, reason: m.disabled ? (m.description || '当前不可选') : null,
      action: () => chooseSetting(s, { model: m.id }),
    });
  }
  if (!items.length) items.push({ label: cat.status === 'probing' ? '正在读取…' : '没有可用的模型目录', disabled: true, action: () => {} });
  picker(anchor, { title: '模型', items, footer: catalogFooter(s) });
}

function openEffortPicker(s, anchor) {
  const st = settingsOf(s);
  const { entry } = modelNow(s);
  if (!entry || !entry.efforts.length) return;
  const def = entry.default_effort ? `（模型默认：${EFFORT_LABEL[entry.default_effort] || entry.default_effort}）` : '';
  const items = [{ label: `默认${def}`, desc: `由 ${HARNESS[s.harness].label} 按模型决定`, checked: !st.chosen.effort, action: () => chooseSetting(s, { effort: null }) }];
  for (const level of entry.efforts) {
    items.push({ label: EFFORT_LABEL[level] || level, note: level, desc: (entry.effort_descriptions || {})[level] || '', checked: st.chosen.effort === level, action: () => chooseSetting(s, { effort: level }) });
  }
  picker(anchor, { title: `思考强度 · ${entry.label}`, items });
}

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
    items.push({ label: m.label, desc: m.description, checked: (st.chosen.mode || now.id) === m.id, disabled: !available, reason, action: () => chooseSetting(s, { mode: m.id }) });
  }
  const label = HARNESS[s.harness].label;
  const reviewer = REVIEWER[st.actual.reviewer] || st.actual.reviewer;
  const foot = h('div', { class: 'picker-foot' }, h('div', { class: 'hint' },
    s.harness === 'codex'
      ? '这些是 Codex 的审批方式与沙箱组合；完全访问（不审批、不设沙箱）不在 RepoBridge 中提供。'
      : `这些是 ${label} 自己的权限模式；跳过全部权限检查的模式不在 RepoBridge 中提供。`),
  s.harness === 'codex' && reviewer ? h('div', { class: 'hint' }, `审批由${reviewer}处理（Codex 自己的 approvals_reviewer 设置，RepoBridge 不改动）。`) : null);
  picker(anchor, { title: '权限模式', items, footer: foot });
}

// ---------------------------------------------------------------- controls row

function renderControls(s) {
  const root = convEl;
  if (!root || !root._left || !root._right) return;
  ensureCatalog(s);
  const cat = catalogOf(s);
  const st = settingsOf(s);
  const ready = cat.models && cat.models.length;
  const busy = S.pending.has(`settings:${s.session_id}`);
  const loading = cat.status === 'probing' && !ready;
  const pill = (name, iconName, text, onClick, extra = {}) => h('button', {
    class: `cpill ${extra.cls || ''}`, type: 'button', disabled: extra.disabled || busy,
    title: extra.title || fieldTitle(s, name, text), 'aria-label': `${FIELD_NAME[name]}：${text}`,
    onclick: (e) => onClick(e.currentTarget),
  }, icon(iconName), h('span', { class: 'pill-text' }, text), fieldMark(st.fields[name]), icon('caret', 'pill-caret'));

  const model = modelNow(s);
  const effort = effortNow(s);
  const mode = modeNow(s);
  const unavailable = !ready ? (loading ? `正在向 ${HARNESS[s.harness].label} 读取模型目录…` : (cat.error ? `读取模型目录失败：${cat.error}` : '还没有模型目录')) : null;
  const modelPill = pill('model', 'spark', ready ? model.label : (loading ? '读取目录…' : '模型'), (a) => (ready ? openModelPicker(s, a) : refreshCatalog(s)),
    unavailable ? { title: `${unavailable}${cat.error || !loading ? '（点击重新读取）' : ''}`, disabled: loading } : {});
  const efforts = model.entry ? model.entry.efforts : [];
  const effortPill = ready && model.entry && !efforts.length
    ? h('span', { class: 'cpill static', title: `${model.entry.label} 不支持调整思考强度` }, icon('gauge'), h('span', { class: 'pill-text' }, '思考不可调'))
    : pill('effort', 'gauge', `思考 ${effort.label}`, (a) => openEffortPicker(s, a), ready && model.entry ? {} : { disabled: true, title: unavailable || '选择模型后可调整' });
  const modePill = pill('mode', 'shield', mode.label, (a) => openModePicker(s, a), ready ? { cls: mode.id && mode.id !== 'default' && mode.id !== 'read-only' && mode.id !== 'workspace' ? 'accent' : '' } : { disabled: true, title: unavailable });
  // Rebuild only when something shown changed: replacing a pill between mousedown and click
  // would swallow the click.
  const sig = [modelPill, effortPill, modePill].map((el) => `${el.className}|${el.disabled}|${el.title}|${el.textContent}|${el.querySelector('.fmark, .st') ? el.querySelector('.fmark, .st').className : ''}`).join('#');
  if (root._ctlSig === sig && root._left.firstChild === root._attachBtn && root._right.lastChild === root._send && !S.devOpen) return;
  root._ctlSig = sig;
  root._left.replaceChildren(root._attachBtn, modePill);
  root._right.replaceChildren(modelPill, effortPill, root._send);
  if (S.devOpen && ready) {
    // Development snapshots (#dev=model|effort|mode): open once the pills exist.
    const which = S.devOpen;
    S.devOpen = null;
    const open = { model: openModelPicker, effort: openEffortPicker, mode: openModePicker }[which];
    queueMicrotask(() => open(s, { model: modelPill, effort: effortPill, mode: modePill }[which]));
  }
}

function settingsStatus(s) {
  // A refused or pending choice the user should notice, or null.
  composerState();
  const st = settingsOf(s);
  for (const name of ['model', 'effort', 'mode']) {
    const rec = st.fields[name];
    if (rec && rec.state === 'failed' && !S.dismissed.has(`f:${s.session_id}:${name}:${rec.at}`)) {
      return { tone: 'bad', text: rec.error || `${FIELD_NAME[name]}没有生效`, dismiss: `f:${s.session_id}:${name}:${rec.at}` };
    }
  }
  const pending = ['model', 'effort', 'mode'].filter((n) => st.fields[n] && st.fields[n].state === 'selected');
  if (pending.length) {
    const names = pending.map((n) => FIELD_NAME[n]).join('、');
    const when = s.harness === 'codex' ? '会随下一条消息一起发给 Codex' : (s.active ? (s.turn ? '会在这一轮结束后应用' : '正在应用') : '会在连接时应用');
    return { tone: 'idle', text: `已选择新的${names}，${when}` };
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
    s.harness === 'claude-code' && (catalogOf(s).commands || []).length ? { icon: 'terminal', label: '使用命令', note: '/', action: () => insertAtCaret(sid, '/', true) } : null,
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
  const cmd = s && s.harness === 'claude-code' ? /^\/([\w:.-]*)$/.exec(before) : null;
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
    const q = cmd[1].toLowerCase();
    const list = (catalogOf(s).commands || []).filter((c) => c.name.toLowerCase().includes(q)).slice(0, 8);
    showPop(sid, list.map((c) => ({ label: `/${c.name}`, desc: c.description, note: c.hint, value: `/${c.name} ` })), 0, `${HARNESS[s.harness].label} 命令`, '没有匹配的命令');
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
      class: `menu-item ${i === st.active ? 'active' : ''}`, type: 'button', tabindex: '-1',
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
  const ta = root._ta;
  const end = ta.selectionStart;
  ta.setRangeText(st.entries[index].value, st.start, end, 'end');
  hidePop();
  ta.dispatchEvent(new Event('input'));
  ta.focus();
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

// ---------------------------------------------------------------- composer

function buildComposer(s) {
  const sid = s.session_id;
  const label = HARNESS[s.harness].label;
  const ta = h('textarea', { rows: '1', 'aria-label': `给 ${label} 发消息` });
  ta.value = S.drafts.get(sid) || '';
  const send = h('button', { class: 'send-btn', type: 'button' });
  const hint = h('span', { class: 'hint composer-hint' });
  const status = h('div', { class: 'conv-status', 'aria-live': 'polite' });
  const pop = h('div', { class: 'menu mention-pop', hidden: true, role: 'listbox' });
  const attRow = h('div', { class: 'att-row', hidden: true });
  const attachBtn = h('button', { class: 'icon-btn', type: 'button', title: '添加附件、引用文件', 'aria-label': '添加附件、引用文件', onclick: (e) => attachMenu(findSession(sid), e.currentTarget) }, icon('clip'));
  const left = h('div', { class: 'cb-left' });
  const right = h('div', { class: 'cb-right' });
  const box = h('div', { class: 'composer' }, pop, attRow, ta, h('div', { class: 'composer-bar' }, left, hint, right));
  const wrap = h('div', { class: 'composer-wrap' }, status, box);
  const root = convRoot();
  Object.assign(root, { _ta: ta, _send: send, _hint: hint, _status: status, _box: box, _pop: pop, _attRow: attRow, _attachBtn: attachBtn, _left: left, _right: right, _popState: null });
  ta.addEventListener('input', () => { S.drafts.set(sid, ta.value); autosize(ta); updateMention(sid); updateConvChrome(findSession(sid), convFor(sid)); });
  ta.addEventListener('click', () => updateMention(sid));
  ta.addEventListener('blur', () => setTimeout(hidePop, 120));
  ta.addEventListener('keydown', (e) => {
    if (e.isComposing || e.keyCode === 229) return;
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
  setTimeout(() => { autosize(ta); renderAttachRow(sid); }, 0);
  return wrap;
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
