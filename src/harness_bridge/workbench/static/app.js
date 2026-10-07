'use strict';
/* RepoBridge workbench UI. Plain DOM, no build step. All untrusted text goes through textContent. */

const LABEL = { 'claude-code': 'Claude Code', codex: 'Codex' };
const STATUS = {
  new: '未启动', starting: '启动中', running: '运行中', exited: '已退出',
  failed: '失败', stopped: '已停止', interrupted: '已中断',
};
const BINDING = {
  pending: '未知（等待首轮完成）',
  preassigned: '已预分配（等待 CLI 确认）',
  confirmed: '已由 CLI 确认',
  observed: '由 CLI 报告',
};

const S = {
  state: null,
  selected: null,
  tab: 'activity',
  terms: new Map(),
  events: new Map(),
  changes: null,
  diffPath: null,
  diffText: null,
  connected: false,
};

// ---------- helpers ----------

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (sel) => document.querySelector(sel);

class ApiError extends Error {
  constructor(error) { super(error.message || '请求失败'); this.code = error.code; this.details = error.details || {}; }
}

async function api(method, path, body) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (method !== 'GET') {
    opts.headers['Content-Type'] = 'application/json';
    opts.headers['X-RepoBridge'] = '1';
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try { res = await fetch(path, opts); } catch (e) { throw new ApiError({ message: '无法连接本地内核' }); }
  let json = null;
  try { json = await res.json(); } catch (e) { /* fallthrough */ }
  if (!json || !json.ok) throw new ApiError((json && json.error) || { message: `HTTP ${res.status}` });
  return json.result;
}

function b64bytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function toast(message, kind = 'error', actions = []) {
  const el = h('div', { class: `toast ${kind === 'info' ? 'info' : ''}` }, h('div', { text: message }));
  if (actions.length) el.append(h('div', { class: 'row' }, actions.map(([label, fn]) =>
    h('button', { class: 'btn btn-small', onclick: () => { el.remove(); fn(); } }, label))));
  $('#toasts').append(el);
  setTimeout(() => el.remove(), actions.length ? 12000 : 6000);
}

function fail(err) {
  const actions = [];
  if (err.details && err.details.busy_session_id) {
    actions.push(['切换到占用会话', () => select(err.details.busy_session_id)]);
  }
  toast(err.message || String(err), 'error', actions);
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function shortId(id) { return id ? id.slice(0, 8) : '—'; }

function allSessions() {
  return S.state ? S.state.projects.flatMap((p) => p.sessions) : [];
}
function findSession(id) { return allSessions().find((s) => s.session_id === id) || null; }
function findProject(id) { return S.state ? S.state.projects.find((p) => p.project_id === id) || null : null; }
function harnessInfo(kind) { return S.state ? S.state.harnesses.find((x) => x.kind === kind) : null; }

// ---------- stream ----------

function connect() {
  const es = new EventSource('/api/stream');
  es.addEventListener('open', () => setConn(true));
  es.addEventListener('error', () => setConn(false));
  es.addEventListener('state', (e) => onState(JSON.parse(e.data)));
  es.addEventListener('reset', (e) => onReset(JSON.parse(e.data)));
  es.addEventListener('output', (e) => onOutput(JSON.parse(e.data)));
  es.addEventListener('activity', (e) => onActivity(JSON.parse(e.data)));
  es.addEventListener('ended', (e) => onEnded(JSON.parse(e.data)));
}

function setConn(ok) {
  S.connected = ok;
  $('#conn').classList.toggle('down', !ok);
  $('#conn').title = ok ? '已连接本地内核' : '与本地内核的连接已断开，正在重连…';
}

function onState(state) {
  S.state = state;
  if (S.selected && !findSession(S.selected)) S.selected = null;
  for (const s of allSessions()) {
    const t = S.terms.get(s.session_id);
    if (t) t.term.options.disableStdin = !s.attached;
  }
  render();
}

// ---------- terminals ----------

function termFor(sessionId) {
  let t = S.terms.get(sessionId);
  if (t) return t;
  const el = h('div', { class: 'term-host' });
  $('#terminals').append(el);
  const term = new Terminal({
    fontFamily: 'Menlo, "SF Mono", Monaco, "Cascadia Mono", monospace',
    fontSize: 13,
    lineHeight: 1.12,
    cursorBlink: true,
    scrollback: 8000,
    allowProposedApi: false,
    theme: {
      background: '#0f1115', foreground: '#d9dce3', cursor: '#d9dce3',
      selectionBackground: '#33415e', black: '#1b1f29', brightBlack: '#5d6474',
    },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(el);
  t = { term, fit, el, runId: null, end: 0, queue: [], flushing: false, sent: '' };
  term.onData((d) => enqueueInput(sessionId, { data: d }));
  term.onBinary((d) => enqueueInput(sessionId, { b64: btoa(d) }));
  term.attachCustomKeyEventHandler((ev) => {
    // Shift+Enter inserts a newline in both TUIs via Ctrl+J (line feed).
    if (ev.type === 'keydown' && ev.key === 'Enter' && ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      enqueueInput(sessionId, { data: '\n' });
      return false;
    }
    return true;
  });
  S.terms.set(sessionId, t);
  return t;
}

function enqueueInput(sessionId, item) {
  const s = findSession(sessionId);
  if (!s || !s.attached) return;
  const t = termFor(sessionId);
  const last = t.queue[t.queue.length - 1];
  if (item.data !== undefined && last && last.data !== undefined) last.data += item.data;
  else t.queue.push(item);
  if (!t.flushing) flushInput(sessionId, t);
}

async function flushInput(sessionId, t) {
  t.flushing = true;
  try {
    while (t.queue.length) {
      const item = t.queue.shift();
      try { await api('POST', `/api/sessions/${sessionId}/input`, item); } catch (e) { t.queue.length = 0; fail(e); }
    }
  } finally { t.flushing = false; }
}

function writeChunk(t, runId, offset, bytes) {
  if (t.runId !== runId) {
    if (t.runId !== null) t.term.write('\r\n\x1b[2m──────── 新的运行 ────────\x1b[0m\r\n');
    t.runId = runId;
    t.end = offset;
    t.sent = '';
  }
  const end = offset + bytes.length;
  if (end <= t.end) return;
  const slice = offset < t.end ? bytes.subarray(t.end - offset) : bytes;
  t.term.write(slice);
  t.end = end;
}

function onReset(msg) {
  const t = termFor(msg.session_id);
  const bytes = b64bytes(msg.data);
  if (t.runId === msg.run_id && t.end >= msg.offset) {
    writeChunk(t, msg.run_id, msg.offset, bytes);
  } else {
    t.term.reset();
    t.runId = msg.run_id;
    t.end = msg.offset;
    t.term.write(bytes);
    t.end = msg.offset + bytes.length;
    t.sent = '';
  }
  if (msg.session_id === S.selected) requestAnimationFrame(syncSize);
}

function onOutput(msg) {
  const t = termFor(msg.session_id);
  writeChunk(t, msg.run_id, msg.offset, b64bytes(msg.data));
  if (msg.session_id === S.selected && !t.sent) requestAnimationFrame(syncSize);
}

function onEnded(msg) {
  const t = S.terms.get(msg.session_id);
  if (t) t.term.write('\r\n\x1b[2m[会话进程已结束]\x1b[0m\r\n');
}

async function loadHistory(sessionId) {
  const t = termFor(sessionId);
  t.loaded = true;
  try {
    const out = await api('GET', `/api/sessions/${sessionId}/output`);
    if (!out.run_id || t.runId !== null) return;
    t.term.reset();
    t.runId = out.run_id;
    const bytes = b64bytes(out.data);
    t.term.write(bytes);
    t.end = out.offset + bytes.length;
    if (!out.live) t.term.write('\r\n\x1b[2m[以上为上次运行的终端输出]\x1b[0m\r\n');
  } catch (e) { fail(e); }
}

function syncSize() {
  const s = S.selected && findSession(S.selected);
  const t = s && S.terms.get(s.session_id);
  if (!t || !t.el.classList.contains('visible')) return;
  try { t.fit.fit(); } catch (e) { return; }
  const size = `${t.term.cols}x${t.term.rows}`;
  if (s.attached && t.sent !== `${t.runId}:${size}`) {
    t.sent = `${t.runId}:${size}`;
    api('POST', `/api/sessions/${s.session_id}/resize`, { cols: t.term.cols, rows: t.term.rows }).catch(() => {});
  }
}

// ---------- actions ----------

function select(sessionId) {
  S.selected = sessionId;
  S.changes = null; S.diffPath = null; S.diffText = null;
  render();
  if (sessionId) {
    loadEvents(sessionId);
    if (S.tab === 'changes') loadChanges();
    focusTerminal(sessionId);
  }
}

async function loadEvents(sessionId) {
  try {
    const events = await api('GET', `/api/sessions/${sessionId}/activity`);
    S.events.set(sessionId, events);
    if (S.selected === sessionId) renderPanel();
  } catch (e) { fail(e); }
}

function onActivity(ev) {
  const list = S.events.get(ev.session_id);
  if (list && !list.some((x) => x.seq === ev.seq)) list.push(ev);
  if (ev.session_id === S.selected) {
    if (S.tab === 'activity') renderPanel();
    if (S.tab === 'changes') scheduleChanges();
  }
}

let changesTimer = null;
function scheduleChanges() {
  clearTimeout(changesTimer);
  changesTimer = setTimeout(loadChanges, 1200);
}

async function loadChanges() {
  const sid = S.selected;
  if (!sid) return;
  try {
    S.changes = await api('GET', `/api/sessions/${sid}/changes`);
    if (S.diffPath && !S.changes.files.some((f) => f.path === S.diffPath)) { S.diffPath = null; S.diffText = null; }
    if (S.diffPath) await loadDiff(S.diffPath, false);
    if (S.selected === sid && S.tab === 'changes') renderPanel();
  } catch (e) { fail(e); }
}

async function loadDiff(path, rerender = true) {
  try {
    const d = await api('GET', `/api/sessions/${S.selected}/diff?path=${encodeURIComponent(path)}`);
    S.diffPath = path; S.diffText = d.diff + (d.truncated ? '\n… (已截断)' : '');
    if (rerender) renderPanel();
  } catch (e) { fail(e); }
}

async function newSession(projectId, harness) {
  try {
    const s = await api('POST', '/api/sessions', { project_id: projectId, harness });
    select(s.session_id);
  } catch (e) { fail(e); }
}

async function startRun(sessionId, kind) {
  try { await api('POST', `/api/sessions/${sessionId}/start`, { kind }); } catch (e) { fail(e); }
  setTimeout(() => focusTerminal(sessionId), 300);
}

async function stopSession(sessionId) {
  try { await api('POST', `/api/sessions/${sessionId}/stop`, {}); } catch (e) { fail(e); }
}

async function renameSession(s) {
  const title = window.prompt('会话标题', s.title);
  if (title === null || !title.trim()) return;
  try { await api('POST', `/api/sessions/${s.session_id}/rename`, { title }); } catch (e) { fail(e); }
}

async function archiveSession(s) {
  if (!window.confirm(`从列表中移除会话「${s.title}」？原生 CLI 中的历史不受影响。`)) return;
  try {
    await api('POST', `/api/sessions/${s.session_id}/archive`, {});
    if (S.selected === s.session_id) select(null);
  } catch (e) { fail(e); }
}

async function archiveProject(p) {
  if (!window.confirm(`从 RepoBridge 中移除项目「${p.name}」？不会删除任何文件。`)) return;
  try { await api('POST', `/api/projects/${p.project_id}/archive`, {}); } catch (e) { fail(e); }
}

// ---------- rendering ----------

function render() {
  renderTop();
  renderSidebar();
  renderMain();
  const s = S.selected && findSession(S.selected);
  const sig = s ? [S.tab, s.session_id, s.status, s.native_session_id, s.native_binding,
    s.turns_observed, s.run && s.run.seq, s.attention ? 1 : 0].join('|') : '';
  if (S.tab !== 'details' || sig !== S.panelSig) renderPanel();
  S.panelSig = sig;
}

function renderTop() {
  const chips = $('#harness-chips');
  chips.replaceChildren();
  if (!S.state) return;
  for (const hinfo of S.state.harnesses) {
    chips.append(h('span', {
      class: `chip ${hinfo.available ? '' : 'bad'}`,
      title: hinfo.available ? `${hinfo.binary}\n点击重新检测` : `${hinfo.problem}\n点击重新检测`,
    },
    h('span', { class: `dot ${hinfo.available ? hinfo.kind : 'off'}` }),
    h('button', { onclick: refreshHarnesses }, hinfo.label),
    h('span', { class: 'ver', text: hinfo.available ? (hinfo.version || '') : '未找到' })));
  }
  const env = $('#env-chips');
  env.replaceChildren();
  const e = S.state.environment;
  if (e.stripped_env.length) {
    env.append(h('span', {
      class: 'chip warn',
      title: '这些变量可能把订阅会话切换为 API 计费。RepoBridge 启动会话时不传递它们（只显示名称）。',
    }, `未传递 API 变量：${e.stripped_env.join(', ')}`));
  }
}

async function refreshHarnesses() {
  try { await api('POST', '/api/harnesses/refresh', {}); toast('已重新检测 CLI', 'info'); } catch (e) { fail(e); }
}

function statusChip(s) {
  if (s.attention) return h('span', { class: 'status attention', title: s.attention.message || '' }, '等待权限');
  if (s.stopping && s.active) return h('span', { class: 'status running' }, '停止中');
  return h('span', { class: `status ${s.status}` }, STATUS[s.status] || s.status);
}

function renderSidebar() {
  const list = $('#project-list');
  list.replaceChildren();
  if (!S.state) return;
  for (const p of S.state.projects) {
    const box = h('div', { class: 'project' },
      h('div', { class: 'project-head' },
        h('div', { class: 'project-name', title: p.root_path }, p.name),
        h('button', { class: 'btn btn-small', title: '从列表移除项目', onclick: () => archiveProject(p) }, '⋯')),
      // The LRM keeps the leading "/" in place while the CSS truncates from the left.
      h('div', { class: 'project-path', title: p.root_path }, `\u200e${p.root_path}`),
      h('div', { class: 'project-actions' },
        h('button', { class: 'btn btn-small btn-claude', onclick: () => newSession(p.project_id, 'claude-code') }, '＋ Claude Code'),
        h('button', { class: 'btn btn-small btn-codex', onclick: () => newSession(p.project_id, 'codex') }, '＋ Codex')));
    for (const s of p.sessions) {
      const from = s.handoff_from && findSession(s.handoff_from);
      box.append(h('div', {
        class: `session ${s.session_id === S.selected ? 'selected' : ''}`,
        onclick: () => select(s.session_id),
        title: s.title,
      },
      h('span', { class: `dot ${s.harness}` }),
      h('span', { class: 'session-title' }, s.title),
      statusChip(s),
      from ? h('span', { class: 'session-sub' }, `↳ 交接自「${from.title}」`) : null));
    }
    list.append(box);
  }
}

function renderMain() {
  const s = S.selected && findSession(S.selected);
  for (const [id, t] of S.terms) t.el.classList.toggle('visible', !!s && id === s.session_id);
  renderSessionBar(s);
  renderBanner(s);
  const empty = $('#empty-state');
  empty.replaceChildren();
  if (!S.state) return;
  if (!s) {
    empty.append(emptyCard());
    return;
  }
  const t = termFor(s.session_id);
  t.el.classList.add('visible');
  t.term.options.disableStdin = !s.attached;
  if (!t.loaded && t.runId === null) loadHistory(s.session_id);
  requestAnimationFrame(syncSize);
}

function focusTerminal(sessionId) {
  requestAnimationFrame(() => {
    const t = S.terms.get(sessionId);
    const s = findSession(sessionId);
    if (t && s && s.attached && !document.querySelector('.modal')) t.term.focus();
  });
}

function emptyCard() {
  const projects = S.state.projects;
  if (!projects.length) {
    return h('div', { class: 'empty-card' },
      h('h2', {}, '添加一个项目开始'),
      h('p', {}, '项目是一个本地目录（通常是 Git 仓库顶层）。在项目里打开 Claude Code 或 Codex 的原生会话，用各自已有的登录与订阅。'),
      h('div', { class: 'empty-actions' }, h('button', { class: 'btn btn-primary', onclick: openAddProject }, '＋ 添加项目')));
  }
  return h('div', { class: 'empty-card' },
    h('h2', {}, '选择或新建一个会话'),
    h('p', {}, '每个会话固定一种 harness。换 harness 时请用“交接”在同一项目中新建会话。'),
    h('div', { class: 'empty-actions' },
      projects.slice(0, 3).flatMap((p) => [
        h('button', { class: 'btn btn-claude', onclick: () => newSession(p.project_id, 'claude-code') }, `${p.name} · ＋ Claude Code`),
        h('button', { class: 'btn btn-codex', onclick: () => newSession(p.project_id, 'codex') }, `${p.name} · ＋ Codex`),
      ])));
}

function renderSessionBar(s) {
  const bar = $('#session-bar');
  bar.replaceChildren();
  if (!s) return;
  const actions = h('div', { class: 'sb-actions' });
  if (s.active) {
    actions.append(h('button', { class: 'btn btn-danger', disabled: s.stopping && s.attached, onclick: () => stopSession(s.session_id) }, s.attached ? '停止' : '终止'));
  } else {
    if (s.can_resume) actions.append(h('button', { class: 'btn btn-primary', onclick: () => startRun(s.session_id, 'resume') }, '恢复'));
    else if (s.can_start_fresh) actions.append(h('button', { class: 'btn btn-primary', onclick: () => startRun(s.session_id, 'new') }, s.status === 'new' ? '启动' : '重新启动'));
  }
  actions.append(h('button', { class: 'btn', onclick: () => openHandoff(s) }, '交接…'));
  if (!s.active) actions.append(h('button', { class: 'btn btn-small', title: '从列表移除', onclick: () => archiveSession(s) }, '移除'));
  bar.append(
    h('span', { class: `dot ${s.harness}` }),
    h('span', { class: 'sb-title', title: '点击重命名', onclick: () => renameSession(s) }, s.title),
    statusChip(s),
    h('span', { class: 'sb-meta', title: s.workdir }, `${s.harness_label} · ${s.workdir} · 原生 ID ${shortId(s.native_session_id)}`),
    actions);
}

function renderBanner(s) {
  const el = $('#banner');
  el.replaceChildren();
  const env = S.state && S.state.environment;
  if (env && env.refusal) el.append(h('div', { class: 'bar bad' }, `当前环境不能启动原生会话：${env.refusal}`));
  if (!s) return;
  if (s.attention) {
    el.append(h('div', { class: 'bar warn' }, `${s.harness_label} 正在等待权限确认：${s.attention.message || ''}。请在下方终端中回答。`));
  }
  if (s.active && !s.attached) {
    el.append(h('div', { class: 'bar warn' }, '该会话由之前的 RepoBridge 进程启动，仍被记录为运行中；本窗口无法接管其终端。可点击“终止”结束它。'));
  }
  const run = s.run;
  if (!s.active && run && (run.status === 'failed' || run.status === 'interrupted')) {
    const hint = s.can_resume ? '可点击“恢复”以原生方式继续同一会话。' : (s.can_start_fresh ? '尚无原生对话，可重新启动。' : '');
    el.append(h('div', { class: `bar ${run.status === 'failed' ? 'bad' : 'warn'}` },
      `${STATUS[run.status]}：${run.failure || ''} ${hint}`));
  }
  if (s.status === 'new' && !s.active) {
    el.append(h('div', { class: 'bar info' }, '会话尚未启动。点击“启动”在 App 终端中打开原生 CLI。'));
  }
}

function renderPanel() {
  const prev = $('#panel');
  const keep = prev.scrollTop;
  const atBottom = keep + prev.clientHeight >= prev.scrollHeight - 48;
  for (const b of document.querySelectorAll('#tabs .tab')) b.classList.toggle('active', b.dataset.tab === S.tab);
  const panel = $('#panel');
  panel.replaceChildren();
  const s = S.selected && findSession(S.selected);
  if (!s) { panel.append(h('div', { class: 'panel-empty' }, '选择一个会话查看活动、文件变更和恢复状态。')); return; }
  if (S.tab === 'activity') panel.append(...activityPanel(s));
  else if (S.tab === 'changes') panel.append(...changesPanel(s));
  else panel.append(...detailsPanel(s));
  panel.scrollTop = S.tab === 'activity' && atBottom ? panel.scrollHeight : keep;
}

function eventView(ev, tools) {
  const p = ev.payload || {};
  let icon = '·', cls = 'sys', text = null;
  if (ev.kind === 'activity') {
    const src = p.source, name = p.event;
    if (src === 'claude-hook') {
      if (name === 'SessionStart') { icon = '◆'; text = `会话开始（${p.start_source || '—'}）· ID ${shortId(p.native_session_id)}`; }
      else if (name === 'UserPromptSubmit') { icon = '›'; cls = 'user'; text = p.prompt || '(空)'; }
      else if (name === 'PreToolUse') {
        icon = '▸'; cls = '';
        const el = h('div', { class: 'ev' }, h('div', { class: 'ev-icon' }, icon),
          h('div', { class: 'ev-body' }, h('div', { class: 'ev-text' }, h('code', {}, p.tool_name || '工具'), p.summary ? ` ${p.summary}` : '')));
        if (p.tool_use_id) tools.set(p.tool_use_id, el);
        return el;
      } else if (name === 'PostToolUse' || name === 'PostToolUseFailure') {
        const prev = p.tool_use_id && tools.get(p.tool_use_id);
        const ok = name === 'PostToolUse';
        if (prev) { prev.querySelector('.ev-text').append(h('span', { class: ok ? 'done' : 'fail' }, ok ? '✓' : `✗ ${p.error || ''}`)); return null; }
        if (ok) return null;
        icon = '✗'; cls = 'bad'; text = `${p.tool_name || '工具'} 失败：${p.error || ''}`;
      } else if (name === 'PermissionRequest') { icon = '!'; cls = 'perm'; text = `请求权限：${p.tool_name || ''} ${p.summary || ''}`; }
      else if (name === 'Notification') {
        const perm = p.notification_type === 'permission_prompt';
        icon = perm ? '!' : '◦'; cls = perm ? 'perm' : 'sys'; text = p.message || p.notification_type || '通知';
      } else if (name === 'Stop') { icon = '■'; text = '本轮结束'; }
      else if (name === 'SessionEnd') { icon = '◇'; text = `会话结束（${p.reason || '—'}）`; }
      else { text = name || '事件'; }
    } else if (src === 'codex-notify') {
      icon = '■'; cls = '';
      text = `本轮完成${p.message ? `：${p.message}` : ''}`;
      if (p.prompt) return [h('div', { class: 'ev user' }, h('div', { class: 'ev-icon' }, '›'), h('div', { class: 'ev-body' }, h('div', { class: 'ev-text' }, p.prompt))),
        h('div', { class: 'ev' }, h('div', { class: 'ev-icon' }, icon), h('div', { class: 'ev-body' }, h('div', { class: 'ev-text' }, text)))];
    } else if (src === 'terminal') {
      const perm = /permission|approv|权限|批准/i.test(p.message || '');
      icon = perm ? '!' : '◦'; cls = perm ? 'perm' : 'sys'; text = p.message || '终端通知';
    }
  } else if (ev.kind === 'run_started') {
    icon = '▶'; cls = 'ok';
    text = `${p.kind === 'resume' ? '原生恢复' : '启动'} ${p.handoff_prompt ? '（发送交接说明）' : ''}`;
    if (p.stripped_env && p.stripped_env.length) text += ` · 未传递：${p.stripped_env.join(', ')}`;
  } else if (ev.kind === 'run_ended') {
    const bad = p.status === 'failed';
    icon = bad ? '✗' : '◼'; cls = bad ? 'bad' : 'sys';
    text = `${STATUS[p.status] || p.status}${p.exit_code !== null && p.exit_code !== undefined ? ` · 退出码 ${p.exit_code}` : ''}${p.failure ? ` · ${p.failure}` : ''}`;
  } else {
    const labels = {
      session_created: '会话已创建', stop_requested: '已请求停止', writer_refused: '启动被拒绝：工作目录已有写入会话',
      native_session_observed: `观察到原生会话 ID ${shortId(p.to)}`,
      native_session_changed: `原生会话 ID 已变化：${shortId(p.from)} → ${shortId(p.to)}（例如 /clear 或 /resume）`,
      handoff_out: `已交接到新会话（${LABEL[p.target] || p.target}）`, handoff_in: `由交接创建${p.send_as_prompt ? '，启动时发送交接说明' : ''}`,
      run_interrupted: 'App 退出时会话被中断', exit_unconfirmed: '退出不明：进程组仍有成员', orphan_stopped: '已结束之前 App 进程留下的会话',
      run_failed: `启动失败：${p.failure || ''}`,
    };
    text = labels[ev.kind] || ev.kind;
    if (ev.kind === 'run_failed' || ev.kind === 'writer_refused' || ev.kind === 'exit_unconfirmed') cls = 'bad';
  }
  if (text === null) return null;
  return h('div', { class: `ev ${cls}`, title: fmtTime(ev.created_at) },
    h('div', { class: 'ev-icon' }, icon),
    h('div', { class: 'ev-body' }, h('div', { class: 'ev-text' }, text), h('div', { class: 'ev-time' }, fmtTime(ev.created_at))));
}

function activityPanel(s) {
  const events = S.events.get(s.session_id);
  if (!events) return [h('div', { class: 'panel-empty' }, '加载中…')];
  const tools = new Map();
  const nodes = events.flatMap((ev) => eventView(ev, tools) || []);
  const note = s.harness === 'codex'
    ? 'Codex 旁路只报告每轮完成与终端通知（含审批请求）；逐个工具的活动请看终端。'
    : 'Claude Code 旁路来自只记录的 hooks：请求、工具、权限与停止。';
  if (!nodes.length) return [h('div', { class: 'panel-tools' }, note), h('div', { class: 'panel-empty' }, '还没有活动。')];
  const box = h('div', {}, nodes);
  return [h('div', { class: 'panel-tools' }, note), box];
}

function changesPanel(s) {
  const tools = h('div', { class: 'panel-tools' }, h('span', { class: 'mono' }, s.workdir.split('/').slice(-2).join('/')),
    h('button', { class: 'btn btn-small', onclick: loadChanges }, '刷新'));
  const c = S.changes;
  if (!c) { if (!changesTimer) loadChanges(); return [tools, h('div', { class: 'panel-empty' }, '加载中…')]; }
  if (!c.git) return [tools, h('div', { class: 'panel-empty' }, c.error || '该目录不是 Git 仓库，无法显示变更。')];
  const head = h('div', { class: 'note' }, `${c.branch || '(detached)'} · ${c.head ? c.head.slice(0, 10) : '无提交'} · ${c.files.length} 个文件有变更`);
  if (!c.files.length) return [tools, head, h('div', { class: 'panel-empty' }, '工作区没有未提交的变更。')];
  const files = c.files.map((f) => h('div', {
    class: `file ${f.path === S.diffPath ? 'selected' : ''}`, onclick: () => loadDiff(f.path),
  },
  h('span', { class: `file-kind ${f.kind}` }, kindLabel(f.kind)),
  h('span', { class: 'file-path' }, f.from ? `${f.from} → ${f.path}` : f.path),
  f.added !== undefined ? h('span', { class: 'file-stat' }, `+${f.added} −${f.removed}`) : null));
  const out = [tools, head, h('div', {}, files)];
  if (S.diffPath && S.diffText !== null) out.push(diffView(S.diffText));
  return out;
}

function kindLabel(kind) {
  return { modified: '修改', added: '新增', deleted: '删除', renamed: '重命名', copied: '复制', untracked: '未跟踪', unmerged: '冲突', 'type changed': '类型' }[kind] || kind;
}

function diffView(text) {
  const pre = h('div', { class: 'diff' });
  for (const line of text.split('\n')) {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) cls = 'meta';
    else if (line.startsWith('+')) cls = 'add';
    else if (line.startsWith('-')) cls = 'del';
    else if (line.startsWith('@@')) cls = 'hunk';
    pre.append(h('span', { class: cls }, line + '\n'));
  }
  return pre;
}

function detailsPanel(s) {
  const p = findProject(s.project_id);
  const resumeHint = s.harness === 'claude-code'
    ? `claude --resume ${s.native_session_id}`
    : `codex resume ${s.native_session_id}`;
  const out = [
    h('div', { class: 'kv' },
      h('div', { class: 'k' }, 'Harness'), h('div', { class: 'v' }, s.harness_label),
      h('div', { class: 'k' }, '项目'), h('div', { class: 'v' }, p ? p.name : s.project_id),
      h('div', { class: 'k' }, '工作目录'), h('div', { class: 'v mono' }, s.workdir),
      h('div', { class: 'k' }, '原生会话 ID'), h('div', { class: 'v mono' }, s.native_session_id || '未知'),
      h('div', { class: 'k' }, 'ID 绑定'), h('div', { class: 'v' }, BINDING[s.native_binding] || s.native_binding),
      h('div', { class: 'k' }, '已观察轮次'), h('div', { class: 'v' }, String(s.turns_observed)),
      h('div', { class: 'k' }, '恢复状态'), h('div', { class: 'v' }, recoveryText(s))),
  ];
  if (s.native_session_id && s.can_resume) {
    out.push(h('div', { class: 'note' }, '也可以在普通终端中用原生命令继续：'), h('pre', { class: 'tail' }, resumeHint));
  }
  const chain = [];
  if (s.handoff_from) {
    const from = findSession(s.handoff_from);
    chain.push(h('div', {}, '交接自：', h('button', { class: 'link', onclick: () => select(s.handoff_from) }, from ? from.title : s.handoff_from)));
  }
  const outs = p ? p.handoffs.filter((x) => x.from_session_id === s.session_id) : [];
  for (const x of outs) {
    const to = findSession(x.to_session_id);
    chain.push(h('div', {}, '交接到：', h('button', { class: 'link', onclick: () => select(x.to_session_id) }, to ? to.title : x.to_session_id), ` · ${fmtTime(x.created_at)}`));
  }
  if (chain.length) out.push(h('div', { class: 'h3' }, '交接链'), ...chain,
    h('div', { class: 'note' }, '交接会新建原生会话，不继承原会话的原生上下文。'));
  out.push(h('div', { class: 'h3' }, '运行记录'));
  const runsBox = h('div', { class: 'note' }, '加载中…');
  out.push(runsBox);
  api('GET', `/api/sessions/${s.session_id}`).then((d) => {
    const table = h('table', { class: 'runs' }, h('tr', {}, h('th', {}, '#'), h('th', {}, '方式'), h('th', {}, '状态'), h('th', {}, '时间')));
    for (const r of d.runs.slice().reverse()) {
      table.append(h('tr', {},
        h('td', {}, String(r.seq)),
        h('td', {}, r.kind === 'resume' ? '恢复' : '新建'),
        h('td', {}, `${STATUS[r.status] || r.status}${r.exit_code !== null ? ` (${r.exit_code})` : ''}${r.exit_signal !== null ? ` 信号 ${r.exit_signal}` : ''}`,
          r.failure ? h('div', { class: 'note' }, r.failure) : null,
          r.stripped_env && r.stripped_env.length ? h('div', { class: 'note' }, `未传递：${r.stripped_env.join(', ')}`) : null),
        h('td', {}, fmtTime(r.started_at))));
    }
    runsBox.replaceWith(d.runs.length ? table : h('div', { class: 'note' }, '尚未运行。'));
    const last = d.runs[d.runs.length - 1];
    if (last && last.output_tail && last.status === 'failed') {
      $('#panel').append(h('div', { class: 'h3' }, '最后输出'), h('pre', { class: 'tail' }, last.output_tail));
    }
  }).catch(fail);
  return out;
}

function recoveryText(s) {
  if (s.active) return s.attached ? '运行中（本窗口终端）' : '记录为运行中（之前的 App 进程）';
  if (s.can_resume) return '可原生恢复同一会话';
  if (s.can_start_fresh) return s.status === 'new' ? '未启动' : '尚无原生对话；可重新启动';
  if (!s.native_session_id) return '未观察到原生会话 ID，不能恢复';
  return '不可恢复';
}

// ---------- modals ----------

function modal(content, small = false) {
  const root = $('#modal-root');
  const box = h('div', { class: `modal ${small ? 'small' : ''}` }, content);
  const back = h('div', { class: 'modal-backdrop', onmousedown: (e) => { if (e.target === back) close(); } }, box);
  function close() { root.replaceChildren(); document.removeEventListener('keydown', onKey); }
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);
  root.replaceChildren(back);
  return close;
}

function openAddProject() {
  const path = h('input', { placeholder: '/Users/you/code/my-project', spellcheck: 'false' });
  const name = h('input', { placeholder: '默认使用目录名' });
  const picker = window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder;
  const pick = picker ? h('button', { class: 'btn', onclick: async () => {
    try { const p = await window.pywebview.api.pick_folder(); if (p) path.value = p; } catch (e) { fail(e); }
  } }, '选择…') : null;
  const submit = async () => {
    try {
      const p = await api('POST', '/api/projects', { path: path.value, name: name.value || null });
      close();
      toast(p.created ? `已添加项目 ${p.name}` : `项目 ${p.name} 已存在`, 'info');
    } catch (e) { fail(e); }
  };
  path.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
  const close = modal([
    h('h2', {}, '添加项目'),
    h('div', { class: 'sub' }, '选择本地目录；如果是 Git 仓库，请选择仓库顶层。RepoBridge 不会修改目录内容。'),
    h('div', { class: 'field' }, h('label', {}, '目录（绝对路径）'), h('div', { class: 'row' }, path, pick)),
    h('div', { class: 'field' }, h('label', {}, '名称（可选）'), name),
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: () => close() }, '取消'),
      h('button', { class: 'btn btn-primary', onclick: submit }, '添加')),
  ], true);
  setTimeout(() => path.focus(), 0);
}

function openHandoff(source) {
  const other = source.harness === 'claude-code' ? 'codex' : 'claude-code';
  let target = other;
  const progress = h('textarea', { rows: 3, placeholder: '例如：登录接口已完成，单元测试有 2 个失败（test_auth.py），下一步修复令牌过期判断。' });
  const note = h('textarea', { rows: 16, spellcheck: 'false' });
  const send = h('input', { type: 'checkbox', checked: true });
  const status = h('div');
  const radios = h('div', { class: 'radio-row' });
  const submitBtn = h('button', { class: 'btn btn-primary' }, '创建交接会话');

  function drawRadios() {
    radios.replaceChildren(...['claude-code', 'codex'].map((k) => {
      const info = harnessInfo(k);
      return h('label', { class: `radio ${k === target ? 'checked' : ''}`, onclick: () => { target = k; drawRadios(); draft(); } },
        h('span', { class: `dot ${k}` }), LABEL[k],
        info && !info.available ? h('span', { class: 'note' }, '（未找到）') : null,
        k === source.harness ? h('span', { class: 'note' }, '（同一 harness）') : null);
    }));
  }

  function drawStatus() {
    const s = findSession(source.session_id);
    status.replaceChildren();
    if (s && s.active) {
      status.append(h('div', { class: 'callout warn' },
        '原会话仍在运行。同一工作目录只允许一个写入会话，请先停止原会话。 ',
        h('button', { class: 'btn btn-small', onclick: async () => { await stopSession(source.session_id); setTimeout(drawStatus, 600); } }, '停止原会话')));
      submitBtn.disabled = true;
      setTimeout(() => { if (document.body.contains(status)) drawStatus(); }, 800);
    } else {
      submitBtn.disabled = false;
    }
  }

  async function draft() {
    try {
      const d = await api('POST', `/api/sessions/${source.session_id}/handoff/draft`, { target, progress: progress.value });
      note.value = d.note;
    } catch (e) { fail(e); }
  }

  submitBtn.addEventListener('click', async () => {
    submitBtn.disabled = true;
    try {
      const r = await api('POST', `/api/sessions/${source.session_id}/handoff`, { target, note: note.value, send_as_prompt: send.checked });
      close();
      select(r.session.session_id);
      toast(`已在同一项目中创建 ${LABEL[target]} 会话`, 'info');
    } catch (e) { submitBtn.disabled = false; fail(e); }
  });

  const close = modal([
    h('h2', {}, '交接到新会话'),
    h('div', { class: 'sub' }, `从「${source.title}」（${LABEL[source.harness]}）交接。新会话在同一项目中启动，不继承原会话的原生上下文；它会阅读代码和这份说明后继续。原会话保留，可以之后恢复查看。`),
    status,
    h('div', { class: 'field' }, h('label', {}, '目标 harness'), radios),
    h('div', { class: 'field' }, h('label', {}, '进度与下一步（会写进说明）'), progress,
      h('div', {}, h('button', { class: 'btn btn-small', onclick: draft }, '重新生成说明'))),
    h('div', { class: 'field' }, h('label', {}, '交接说明（可编辑；保存在 RepoBridge 状态目录，不写入仓库）'), note),
    h('label', { class: 'check' }, send, h('span', {}, '启动后把说明作为第一条消息发送给新会话（会产生一次模型调用）。不勾选则只启动，你可以自己粘贴。')),
    h('div', { class: 'modal-actions' }, h('button', { class: 'btn', onclick: () => close() }, '取消'), submitBtn),
  ]);
  drawRadios();
  drawStatus();
  draft();
}

// ---------- boot ----------

document.querySelectorAll('#tabs .tab').forEach((b) => b.addEventListener('click', () => {
  S.tab = b.dataset.tab;
  if (S.tab === 'changes') { S.changes = null; loadChanges(); }
  renderPanel();
}));
$('#add-project').addEventListener('click', openAddProject);
new ResizeObserver(() => requestAnimationFrame(syncSize)).observe($('#terminals'));
setConn(false);
connect();
