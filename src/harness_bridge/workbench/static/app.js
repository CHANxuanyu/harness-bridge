'use strict';
/* RepoBridge workbench UI — plain DOM, no build step. Untrusted text only via textContent.
   The terminal is the native CLI itself; everything around it organises, explains and recovers. */

// ---------------------------------------------------------------- constants

const HARNESS = {
  'claude-code': { label: 'Claude Code', short: 'Claude', resume: (id) => `claude --resume ${id}` },
  codex: { label: 'Codex', short: 'Codex', resume: (id) => `codex resume ${id}` },
};
const KEY_LABELS = [
  ['新建会话', '⌘N'], ['显示/隐藏变更', '⌘⇧D'], ['显示/隐藏活动', '⌘⇧A'], ['显示/隐藏详情', '⌘⇧I'],
  ['关闭辅助面板', '⌘\\'], ['显示/隐藏侧边栏', '⌃⌘S'], ['下一个 / 上一个会话', '⌃Tab / ⌃⇧Tab'],
  ['设置', '⌘,'], ['键盘快捷键', '⌘/'], ['终端内换行', '⇧↩'], ['强制选择终端文本', '⌥ + 拖动'],
  ['对话：发送 / 换行', '↩ / ⇧↩'], ['对话：停止这一轮', 'Esc'],
];
const LIGHT_TERM = {
  background: '#fbfaf8', foreground: '#1f1e1c', cursor: '#1f1e1c', cursorAccent: '#fbfaf8',
  selectionBackground: 'rgba(47, 98, 201, 0.22)',
  black: '#1f1e1c', red: '#b3261e', green: '#1f7a46', yellow: '#8a5a00', blue: '#2a5bc4',
  magenta: '#8a3fa8', cyan: '#0d7480', white: '#6e6b65',
  brightBlack: '#7c7973', brightRed: '#d0392f', brightGreen: '#238a51', brightYellow: '#9c6a00',
  brightBlue: '#346ad8', brightMagenta: '#9b4fbd', brightCyan: '#118a95', brightWhite: '#8f8b84',
};
const DARK_TERM = {
  background: '#1c1b1a', foreground: '#e6e3dc', cursor: '#e6e3dc', cursorAccent: '#1c1b1a',
  selectionBackground: 'rgba(122, 162, 255, 0.32)',
  black: '#2b2a28', red: '#ec7a72', green: '#7ccb93', yellow: '#e6bb62', blue: '#7aa7ec',
  magenta: '#c9a0e4', cyan: '#62c6bc', white: '#d9d5cd',
  brightBlack: '#77746d', brightRed: '#f4958e', brightGreen: '#98dbab', brightYellow: '#f0cd85',
  brightBlue: '#9cc0f5', brightMagenta: '#dab8ef', brightCyan: '#86d6cd', brightWhite: '#f5f3ee',
};

// ---------------------------------------------------------------- state

const S = {
  state: null,
  prefs: null,
  prefsLocalAt: 0,
  sel: null,              // {type: 'session'|'project', id}
  terms: new Map(),
  events: new Map(),
  changes: new Map(),     // session_id -> changes payload
  diff: null,             // {sid, path, text}
  details: new Map(),     // session_id -> detail payload
  filter: '',
  pending: new Set(),
  sidebarOverlayOpen: false,
  renaming: false,
  connected: false,
  lastTitle: '',
  pendingFocus: null,
  convs: new Map(),       // session_id -> conversation view state
  drafts: new Map(),      // session_id -> unsent composer text
  openItems: new Set(),   // expanded tool / reasoning items
  switching: new Set(),   // sessions changing view
  unsent: unsentStore(),  // sent messages until delivered; kept copies of undelivered ones (composer.js)
};

// ---------------------------------------------------------------- helpers

const $ = (sel, root = document) => root.querySelector(sel);

// Boolean attributes are present or absent: a falsy value such as 0 (SQLite flags) must not set
// them (an attribute "disabled=0" still disables the element).
const BOOL_ATTRS = new Set(['disabled', 'checked', 'selected', 'hidden', 'multiple', 'readonly', 'required', 'open', 'autofocus']);

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (BOOL_ATTRS.has(k) && !v) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

function icon(name, cls = '') {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', `i ${cls}`.trim());
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

function glyph(kind) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 12 12');
  svg.setAttribute('aria-hidden', 'true');
  const add = (tag, attrs) => {
    const el = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    svg.append(el);
    return el;
  };
  const stroke = { fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5', 'stroke-linecap': 'round' };
  if (kind === 'dot') add('circle', { cx: 6, cy: 6, r: 3.5, fill: 'currentColor' });
  else if (kind === 'ring') add('circle', { cx: 6, cy: 6, r: 4, ...stroke });
  else if (kind === 'dashed') add('circle', { cx: 6, cy: 6, r: 4, ...stroke, 'stroke-dasharray': '2 2.2' });
  else if (kind === 'ringdot') { add('circle', { cx: 6, cy: 6, r: 4, ...stroke }); add('circle', { cx: 6, cy: 6, r: 1.4, fill: 'currentColor' }); }
  else if (kind === 'spin') { const c = add('circle', { cx: 6, cy: 6, r: 4, ...stroke, 'stroke-dasharray': '15 10' }); c.setAttribute('class', 'spin'); }
  else if (kind === 'alert') {
    add('circle', { cx: 6, cy: 6, r: 5.25, fill: 'currentColor' });
    add('path', { d: 'M6 3.3v3.3M6 8.6v.1', fill: 'none', stroke: 'var(--bg)', 'stroke-width': '1.6', 'stroke-linecap': 'round' });
  } else if (kind === 'check') {
    add('circle', { cx: 6, cy: 6, r: 5.25, fill: 'currentColor' });
    add('path', { d: 'M3.6 6.2 5.3 7.8 8.5 4.4', fill: 'none', stroke: 'var(--bg)', 'stroke-width': '1.4', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  } else if (kind === 'half') {
    add('circle', { cx: 6, cy: 6, r: 4, ...stroke });
    add('path', { d: 'M6 2a4 4 0 0 1 0 8z', fill: 'currentColor' });
  } else if (kind === 'x') {
    add('circle', { cx: 6, cy: 6, r: 5.25, fill: 'currentColor' });
    add('path', { d: 'M4.2 4.2l3.6 3.6M7.8 4.2 4.2 7.8', fill: 'none', stroke: 'var(--bg)', 'stroke-width': '1.4', 'stroke-linecap': 'round' });
  }
  return svg;
}

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
  try { res = await fetch(path, opts); } catch (e) { throw new ApiError({ message: '无法连接 RepoBridge 本地服务' }); }
  let json = null;
  try { json = await res.json(); } catch (e) { /* not JSON */ }
  if (!json || !json.ok) throw new ApiError((json && json.error) || { message: `请求失败（HTTP ${res.status}）` });
  return json.result;
}

function b64bytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function homeify(path) {
  const home = S.state && S.state.home;
  if (home && (path === home || path.startsWith(home + '/'))) return '~' + path.slice(home.length);
  return path;
}

// Paths inside the session's folder read better relative to it; others are shown from ~.
function relText(s, text) {
  if (!text || !s) return text || '';
  let out = String(text);
  const roots = [s.workdir];
  for (const root of roots) if (root) out = out.split(`${root}/`).join('');
  const home = S.state && S.state.home;
  if (home) out = out.split(`${home}/`).join('~/');
  return out;
}

function shortPath(path, max = 48) {
  const p = homeify(path);
  if (p.length <= max) return p;
  const parts = p.split('/');
  const last = parts.pop();
  let head = parts[0] === '' ? '/' + (parts[1] || '') : parts[0];
  if (head.length + last.length + 4 > max) head = parts[0] === '~' ? '~' : '';
  return `${head}/…/${last}`;
}

function clock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const now = new Date();
  const same = d.toDateString() === now.toDateString();
  const t = d.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' });
  return same ? t : `${d.getMonth() + 1}月${d.getDate()}日 ${t}`;
}

function allSessions(includeArchived = true) {
  if (!S.state) return [];
  const list = S.state.projects.flatMap((p) => p.sessions);
  return includeArchived ? list : list.filter((s) => !s.archived);
}
const findSession = (id) => allSessions().find((s) => s.session_id === id) || null;
const findProject = (id) => (S.state ? S.state.projects.find((p) => p.project_id === id) || null : null);
const harnessInfo = (kind) => (S.state ? S.state.harnesses.find((x) => x.kind === kind) : null);
const harnessOk = (kind) => { const x = harnessInfo(kind); return !!(x && x.available); };
const selectedSession = () => (S.sel && S.sel.type === 'session' ? findSession(S.sel.id) : null);
const selectedProject = () => {
  if (!S.sel) return null;
  if (S.sel.type === 'project') return findProject(S.sel.id);
  const s = findSession(S.sel.id);
  return s ? findProject(s.project_id) : null;
};
const busySessionIn = (project) => (project ? project.sessions.find((s) => s.active) || null : null);

function statusOf(s) {
  const label = HARNESS[s.harness].label;
  if (s.active && !s.attached) return { key: 'orphan', label: '后台遗留进程', tone: 'warn', glyph: 'alert' };
  if (s.active && s.stopping) return { key: 'stopping', label: '正在停止…', tone: 'idle', glyph: 'spin' };
  if (s.attention) return { key: 'attention', label: '需要你确认', tone: 'warn', glyph: 'alert' };
  if (S.switching.has(s.session_id)) return { key: 'switching', label: '正在切换视图…', tone: 'idle', glyph: 'spin' };
  if (s.active && s.transport === 'structured') {
    if (s.phase === 'starting') return { key: 'starting', label: `正在连接 ${label}…`, tone: 'ok', glyph: 'spin' };
    if (s.turn) return { key: 'working', label: '工作中', tone: 'ok', glyph: 'spin' };
    return { key: 'waiting', label: '已连接，等待输入', tone: 'ok', glyph: 'dot' };
  }
  if (s.active) {
    if (s.phase === 'starting') return { key: 'starting', label: `正在启动 ${label}…`, tone: 'ok', glyph: 'spin' };
    if (s.phase === 'working') return { key: 'working', label: '工作中', tone: 'ok', glyph: 'spin' };
    if (s.phase === 'waiting') return { key: 'waiting', label: '等待输入', tone: 'ok', glyph: 'dot' };
    return { key: 'running', label: '运行中', tone: 'ok', glyph: 'dot' };
  }
  if (linkHold(s)) return { key: 'external', label: '外部可能在使用', tone: 'idle', glyph: 'half' };
  if (s.external) return { key: 'external', label: `已在 ${s.external.app} 中打开`, tone: 'idle', glyph: 'half' };
  if (wasUnlinked(s)) return { key: 'unlinked', label: '已移除关联', tone: 'idle', glyph: 'ring' };
  if (isLinked(s) && s.status === 'new') return { key: 'linked', label: '已添加，未连接', tone: 'idle', glyph: 'dashed' };
  return {
    new: { key: 'new', label: '未启动', tone: 'idle', glyph: 'dashed' },
    exited: { key: 'exited', label: '已退出', tone: 'idle', glyph: 'ring' },
    stopped: { key: 'stopped', label: '已停止', tone: 'idle', glyph: 'ring' },
    failed: { key: 'failed', label: '失败', tone: 'bad', glyph: 'x' },
    interrupted: { key: 'interrupted', label: '已中断', tone: 'warn', glyph: 'ringdot' },
  }[s.status] || { key: s.status, label: s.status, tone: 'idle', glyph: 'ring' };
}

function stGlyph(st) { return h('span', { class: `st st-${st.tone}`, title: st.label || null }, glyph(st.glyph)); }

// ---------------------------------------------------------------- prefs & theme

let prefsTimer = null;
const prefsQueue = {};
function setPref(key, value) {
  if (!S.prefs) return;
  S.prefs[key] = value;
  S.prefsLocalAt = Date.now();
  prefsQueue[key] = value;
  clearTimeout(prefsTimer);
  prefsTimer = setTimeout(() => {
    const body = { ...prefsQueue };
    for (const k of Object.keys(prefsQueue)) delete prefsQueue[k];
    api('POST', '/api/prefs', body).catch(() => {});
  }, 250);
}

const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
function resolvedTheme() {
  const mode = S.prefs ? S.prefs.appearance : 'system';
  return mode === 'system' ? (darkQuery.matches ? 'dark' : 'light') : mode;
}
function termTheme() {
  return (S.prefs && S.prefs.terminal_theme === 'dark') || resolvedTheme() === 'dark' ? DARK_TERM : LIGHT_TERM;
}
function applyTheme() {
  document.documentElement.dataset.theme = resolvedTheme();
  const theme = termTheme();
  for (const t of S.terms.values()) {
    t.term.options.theme = theme;
    t.term.options.minimumContrastRatio = theme === LIGHT_TERM ? 4.5 : 1;
    if (S.prefs) t.term.options.fontSize = S.prefs.terminal_font_size;
  }
  $('#stage').style.background = theme.background;
  if (S.prefs) nativeCall('appearance', { mode: S.prefs.appearance });
  scheduleFit();
}
darkQuery.addEventListener('change', applyTheme);

// Native window integration goes through the authenticated loopback API (no page eval/JS bridge).
function hasNative(name) { return !!(S.state && S.state.native && S.state.native.includes(name)); }
function nativeCall(name, body) {
  const route = { title: 'title', appearance: 'appearance', pick_folder: 'pick-folder', open_url: 'open-url' }[name];
  if (!hasNative(name)) return Promise.resolve(null);
  return api('POST', `/api/native/${route}`, body || {}).catch(() => null);
}

function updateWindowTitle(force = false) {
  const s = selectedSession();
  const p = selectedProject();
  const title = s ? `${s.title} — ${p ? p.name : ''}` : (p ? p.name : 'RepoBridge');
  document.title = title;
  if (force || title !== S.lastTitle) nativeCall('title', { title });
  S.lastTitle = title;
}

// ---------------------------------------------------------------- stream

function connect() {
  const es = new EventSource('/api/stream');
  es.addEventListener('open', () => {
    const missed = S.wasDisconnected;
    S.connected = true;
    S.wasDisconnected = false;
    renderNotice();
    if (missed) checkInflight({ force: true }); // events may have been missed while away
  });
  es.addEventListener('error', () => { S.connected = false; S.wasDisconnected = true; renderNotice(); });
  es.addEventListener('state', (e) => onState(JSON.parse(e.data)));
  es.addEventListener('reset', (e) => onReset(JSON.parse(e.data)));
  es.addEventListener('output', (e) => onOutput(JSON.parse(e.data)));
  es.addEventListener('activity', (e) => onActivity(JSON.parse(e.data)));
  es.addEventListener('ended', (e) => onEnded(JSON.parse(e.data)));
  es.addEventListener('conv', (e) => onConv(JSON.parse(e.data)));
}

function onState(state) {
  const first = !S.state;
  S.state = state;
  if (first || Date.now() - S.prefsLocalAt > 1500) {
    const before = S.prefs ? `${S.prefs.appearance}|${S.prefs.terminal_theme}|${S.prefs.terminal_font_size}` : '';
    S.prefs = { ...state.prefs };
    if (!first && before !== `${S.prefs.appearance}|${S.prefs.terminal_theme}|${S.prefs.terminal_font_size}`) applyTheme();
  }
  if (first) {
    // Development snapshots must not depend on animation frames (a covered window or a
    // sleeping display does not advance them, leaving fade-ins at opacity 0).
    if (state.dev) document.documentElement.classList.add('dev-still');
    applyTheme();
    updateWindowTitle(true);
    const want = S.prefs.selected_session && findSession(S.prefs.selected_session);
    if (want) S.sel = { type: 'session', id: want.session_id };
    else if (state.projects.length) S.sel = { type: 'project', id: state.projects[0].project_id };
  }
  if (S.pendingSelect) {
    const want = S.pendingSelect;
    if (findSession(want.id)) { S.pendingSelect = null; queueMicrotask(() => select({ type: 'session', id: want.id })); } else if (Date.now() > want.until) S.pendingSelect = null;
  }
  if (S.sel && S.sel.type === 'session' && !findSession(S.sel.id)) S.sel = null;
  if (S.sel && S.sel.type === 'project' && !findProject(S.sel.id)) S.sel = null;
  for (const s of allSessions()) {
    const t = S.terms.get(s.session_id);
    if (t) { t.term.options.disableStdin = !s.attached; t.el.classList.toggle('readonly', !s.attached); }
  }
  render();
  checkInflight();
  if (first && selectedSession()) { loadForSession(selectedSession()); focusTerminal(S.sel.id); }
  if (S.pendingFocus) setTimeout(tryPendingFocus, 0);
  if (first) runDevHash();
}

// ---------------------------------------------------------------- terminals

function termFor(sessionId) {
  let t = S.terms.get(sessionId);
  if (t) return t;
  const el = h('div', { class: 'term-host readonly', dataset: { session: sessionId } });
  $('#terminals').append(el);
  const theme = termTheme();
  const term = new Terminal({
    fontFamily: 'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Monaco, monospace',
    fontSize: S.prefs ? S.prefs.terminal_font_size : 13,
    lineHeight: 1.15,
    cursorBlink: true,
    scrollback: 10000,
    macOptionClickForcesSelection: true,
    minimumContrastRatio: theme === LIGHT_TERM ? 4.5 : 1,
    theme,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(el);
  t = { term, fit, el, runId: null, end: 0, queue: [], flushing: false, sent: '', loaded: false };
  term.onData((d) => enqueueInput(sessionId, { data: d }));
  term.onBinary((d) => enqueueInput(sessionId, { b64: btoa(d) }));
  term.attachCustomKeyEventHandler((ev) => {
    if (ev.type === 'keydown' && ev.key === 'Enter' && ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      enqueueInput(sessionId, { data: '\n' }); // Ctrl+J: newline in both TUIs
      return false;
    }
    return true;
  });
  S.terms.set(sessionId, t);
  return t;
}

function disposeTerm(sessionId) {
  const t = S.terms.get(sessionId);
  if (!t) return;
  t.term.dispose();
  t.el.remove();
  S.terms.delete(sessionId);
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
    // A new run (start/resume) is a new native process: start clean; the CLI redraws its history.
    t.term.reset();
    t.runId = runId;
    t.end = offset;
    t.sent = '';
  }
  const end = offset + bytes.length;
  if (end <= t.end) return;
  t.term.write(offset < t.end ? bytes.subarray(t.end - offset) : bytes);
  t.end = end;
}

function onReset(msg) {
  const t = termFor(msg.session_id);
  const bytes = b64bytes(msg.data);
  if (t.runId === msg.run_id && t.end >= msg.offset) writeChunk(t, msg.run_id, msg.offset, bytes);
  else { t.term.reset(); t.runId = msg.run_id; t.end = msg.offset; t.term.write(bytes); t.end = msg.offset + bytes.length; t.sent = ''; }
  t.loaded = true;
  if (S.sel && msg.session_id === S.sel.id) scheduleFit();
}

function onOutput(msg) {
  const t = termFor(msg.session_id);
  const fresh = t.runId !== msg.run_id;
  const wasEmpty = t.end === 0;
  writeChunk(t, msg.run_id, msg.offset, b64bytes(msg.data));
  t.loaded = true;
  if (S.sel && msg.session_id === S.sel.id) {
    if (fresh || !t.sent) scheduleFit();
    if (fresh || wasEmpty) renderOverlay();
  }
}

// Message delivery (composer.js holds the rules): every source of a receipt goes through
// noteDelivery — the /send answer, user items from the conversation and its SSE stream, history
// reloads and GET …/delivery. An ended run, a missing receipt or a failed query proves nothing.
// Every user item written to the conversation cache goes through deliveryView, so a confirmed
// message is never shown, kept or blocking as anything but sent.
function boxOf(sid) {
  const root = convEl;
  const visible = !!(root && !root.hidden && root.dataset.sid === sid && root._ta);
  return { visible, draft: visible ? root._ta.value : (S.drafts.get(sid) || ''), attIds: attachments(sid).map((a) => a.id || a.name) };
}

function noteDelivery(sid, item) {
  const cid = itemClientId(item);
  if (!cid || (item.type && item.type !== 'user')) return;
  const outcome = deliveryOutcome(item);
  const d = item.delivery || {};
  if (outcome === 'sent') applyUnsent(sid, unsentDelivered(S.unsent, sid, cid, boxOf(sid), item.delivery));
  else if (outcome === 'not_sent') applyUnsent(sid, unsentFail(S.unsent, sid, cid, boxOf(sid)));
  else if (outcome === 'unknown') {
    // Only a backend receipt can be adopted after a reload; a bare status is not one.
    const info = { receipt: !!item.delivery, reason: d.reason || null, message: d.message || null };
    applyUnsent(sid, unsentUnknown(S.unsent, sid, cid, info, item.delivery ? item : null));
  }
  syncBubble(sid, cid, item);
}

// A receipt that did not come with the item itself (the /send answer, a query) moves the cached
// bubble forward only: from waiting to the receipt's state, or to sent once confirmed. Unknown and
// not_sent do not replace each other here; events and history pages carry those.
function syncBubble(sid, cid, receipt) {
  const c = S.convs.get(sid);
  const id = `user:${cid}`;
  const it = c && c.items.get(id);
  const was = deliveryOutcome(it);
  const now = deliveryOutcome(receipt);
  if (!it || !now || now === 'pending' || now === was || (was && was !== 'pending' && now !== 'sent')) return;
  const status = receipt.status || { sent: 'sent', not_sent: 'failed', unknown: 'unknown' }[now];
  c.items.set(id, deliveryView(S.unsent, sid, { ...it, status, ...(receipt.delivery ? { delivery: receipt.delivery } : {}) }));
  queuePatch(sid, id);
}

// A history page (first page, refresh, older page) is cached through deliveryView. The sent items
// in it are recorded first, including those the pager skipped because their ID was already loaded:
// the loaded copy keeps its content and place, and is shown as sent. Returns the page's user item
// IDs and those whose cached copy changed.
function viewPage(sid, c, items) {
  const ids = [];
  for (const it of items) if (it && it.type === 'user') { deliveryView(S.unsent, sid, it); ids.push(it.id); }
  const changed = [];
  for (const id of ids) {
    const it = c.items.get(id);
    const v = it ? deliveryView(S.unsent, sid, it) : it;
    if (v !== it) { c.items.set(id, v); changed.push(id); }
  }
  return { ids, changed };
}

// After a page of history arrives (reload, restart, refresh, older page): settle what it confirms
// and pick up receipts the backend keeps for unresolved messages.
function reconcileDeliveries(sid, items) {
  for (const it of items) {
    if (!it || it.type !== 'user') continue;
    const cid = itemClientId(it);
    if (it.delivery || (cid && (S.unsent.inflight.has(cid) || S.unsent.placed.has(cid) || [...S.unsent.uncertain.values(), ...S.unsent.held.values()].some((l) => l.some((e) => e.clientId === cid))))) noteDelivery(sid, it);
  }
}

let inflightTimer = null;
function scheduleInflightCheck(ms = 2000) {
  clearTimeout(inflightTimer);
  if (S.unsent.inflight.size) inflightTimer = setTimeout(() => checkInflight(), ms);
}

// Open messages are settled by their receipt: when the run has ended, when no answer came for a
// while (a missed SSE event), or on demand (reconnect, "刷新结果").
function checkInflight({ force = false } = {}) {
  for (const e of [...S.unsent.inflight.values()]) {
    const c = S.convs.get(e.sid);
    const it = c && c.items.get(`user:${e.clientId}`);
    const outcome = deliveryOutcome(it);
    if (outcome && outcome !== 'pending') { noteDelivery(e.sid, it); continue; }
    const s = findSession(e.sid);
    if (!s) { S.unsent.inflight.delete(e.clientId); continue; }
    const due = force || !s.active || Date.now() - e.at > 8000;
    if (due && !e.checking && Date.now() >= (e.nextCheck || 0)) queryReceipt(e);
  }
  scheduleInflightCheck();
}

async function queryReceipt(e) {
  e.checking = true;
  let receipt = null;
  let error = null;
  try {
    receipt = await api('GET', `/api/sessions/${e.sid}/delivery?client_id=${encodeURIComponent(e.clientId)}`);
  } catch (x) { error = x; }
  e.checking = false;
  if (!S.unsent.inflight.has(e.clientId)) return;
  const outcome = deliveryOutcome(receipt);
  if (outcome && outcome !== 'pending') { noteDelivery(e.sid, receipt); return; }
  e.tries = (e.tries || 0) + 1;
  e.nextCheck = Date.now() + Math.min(30000, 1000 * 2 ** e.tries);
  const s = findSession(e.sid);
  const missing = error && error.details && error.details.reason === 'message_not_found';
  if (s && s.active && !(missing && e.lostAnswer)) { scheduleInflightCheck(Math.max(500, e.nextCheck - Date.now())); return; }
  // Nothing settles it (the connection has ended, or the answer was lost and no receipt exists):
  // keep the message apart as unknown.
  const label = s ? HARNESS[s.harness].label : 'CLI';
  let message = null;
  if (receipt) message = e.tries >= 5 ? `接收记录仍显示“正在发送”，但连接已经结束；无法确认 ${label} 是否收到。请核对历史。` : null;
  else if (missing) message = `RepoBridge 没有这条消息的接收记录，连接在确认前结束了；无法确认 ${label} 是否收到。请核对历史，不要直接重发。`;
  else if (e.tries >= 3) message = `暂时查询不到这条消息的接收结果；无法确认 ${label} 是否收到。可以稍后刷新结果，或核对历史。`;
  if (message) applyUnsent(e.sid, unsentUnknown(S.unsent, e.sid, e.clientId, { receipt: false, reason: missing ? 'message_not_found' : null, message }));
  else scheduleInflightCheck(Math.max(500, e.nextCheck - Date.now()));
}

// "刷新结果": ask for the receipt again and re-read the history (read-only reconciliation).
async function recheckDelivery(sid, cid, button) {
  await guarded(`recheck:${cid}`, async () => {
    let receipt = null;
    try { receipt = await api('GET', `/api/sessions/${sid}/delivery?client_id=${encodeURIComponent(cid)}`); } catch (x) { /* no receipt: the history check below still runs */ }
    if (receipt) noteDelivery(sid, receipt);
    const s = findSession(sid);
    if (s && s.view_mode === 'conversation') await refreshConversation(sid, { quiet: true });
    const still = [...(S.unsent.uncertain.get(sid) || [])].some((x) => x.clientId === cid);
    if (still) toast('结果仍未确认：接收记录和原生历史里都还没有它被收到的证据。');
  }, button);
}

function deliveryBlock(s) {
  // Same rule as the backend's delivery_unknown refusal (receipt-backed unknowns only).
  const u = unsentBlocking(S.unsent, s.session_id);
  return u ? '上一条消息是否送达还不确定：先“刷新结果”并核对历史，确认前不能发送新消息（可以继续编辑草稿）。' : null;
}

// Every toast says what actually happened to the text.
function applyUnsent(sid, r, why = '这条消息没有发出', { quiet = false } = {}) {
  if (!r || r.to === 'delivered') return;
  const root = convEl;
  const s = findSession(sid);
  const here = boxOf(sid).visible;
  const name = s ? `「${s.title}」` : '另一个会话';
  if (r.to === 'box') {
    root._ta.value = r.entry.text;
    S.drafts.set(sid, r.entry.text);
    autosize(root._ta);
    mergeAttachments(attachments(sid), r.entry.atts);
    renderAttachRow(sid);
    if (!quiet) toast(`${why}，已放回输入框。`);
  } else if (r.to === 'held') {
    renderUnsent(sid);
    toast(r.visible ? `${why}。输入框里有新的草稿，没有覆盖它；原消息保留在输入框上方。`
      : `${name}中有一条消息没有发出，已保留；回到那个会话后可以放回输入框。`);
  } else if (r.to === 'uncertain') {
    renderUnsent(sid);
    if (!r.adopted && !r.updated) {
      toast(here ? '这条消息是否送达还不确定，已单独保留；请核对历史，不要直接重发。'
        : `${name}中有一条消息是否送达还不确定，已单独保留。`);
    }
  } else if (r.to === 'resolved') {
    renderUnsent(sid);
    toast(`${here ? '' : name + '中'}那条结果待确认的消息已确认送达（CLI 已接收）。这不代表那一轮已经完成。`);
  } else if (r.to === 'unheld') {
    renderUnsent(sid);
    toast(`${here ? '' : name + '中'}一条标为“没有发出”的消息后来由 CLI 确认已送达，已从未发送列表中移除。`);
  } else if (r.to === 'cleared') {
    if (here) { root._ta.value = ''; autosize(root._ta); }
    S.drafts.delete(sid);
    const ids = new Set(r.entry.atts.map((a) => a.id).filter(Boolean));
    S.attach.set(sid, attachments(sid).filter((a) => !ids.has(a.id)));
    renderAttachRow(sid);
    toast('那条消息其实已经送达（CLI 已接收），已从输入框移除，避免重复发送。');
  } else if (r.to === 'edited') {
    toast('那条消息其实已经送达（CLI 已接收）。输入框里的文字已改动，没有自动清除；发送前请确认是否还需要。');
  }
  if (here) updateConvChrome(s, convFor(sid));
}

// A user item the history shows as not sent can be put back by hand (also after a reload).
function restoreFromItem(sid, it) {
  const root = convEl;
  if (!boxOf(sid).visible) return;
  const cid = itemClientId(it);
  // Confirmed since this bubble was drawn: nothing to put back.
  if (unsentConfirmed(S.unsent, sid, cid)) { queuePatch(sid, it.id); return; }
  unsentTake(S.unsent, sid, cid);
  const text = it.text || '';
  const atts = (it.attachments || []).filter((a) => a.id);
  root._ta.value = root._ta.value.trim() ? `${root._ta.value.replace(/\s+$/, '')}\n\n${text}` : text;
  S.drafts.set(sid, root._ta.value);
  mergeAttachments(attachments(sid), atts);
  S.unsent.handled.add(cid);
  S.unsent.placed.set(cid, { sid, clientId: cid, text, atts, at: Date.now() });
  autosize(root._ta);
  renderAttachRow(sid);
  renderUnsent(sid);
  updateConvChrome(findSession(sid), convFor(sid));
  queuePatch(sid, it.id);
  root._ta.focus();
}

function onEnded(msg) {
  scheduleChanges(msg.session_id, 300);
  S.details.delete(msg.session_id);
  const c = S.convs.get(msg.session_id);
  if (c) { c.live = false; c.turn = null; c.stale = true; }
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
    if (S.sel && S.sel.id === sessionId) renderOverlay();
  } catch (e) { fail(e); }
}

let fitFrame = 0;
let resizeTimer = null;
function scheduleFit() {
  cancelAnimationFrame(fitFrame);
  fitFrame = requestAnimationFrame(() => {
    const s = selectedSession();
    const t = s && S.terms.get(s.session_id);
    if (!t || !t.el.classList.contains('visible')) return;
    try { t.fit.fit(); } catch (e) { return; }
    const size = `${t.runId}:${t.term.cols}x${t.term.rows}`;
    if (s.attached && t.sent !== size) {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        t.sent = size;
        api('POST', `/api/sessions/${s.session_id}/resize`, { cols: t.term.cols, rows: t.term.rows }).catch(() => {});
      }, 60);
    }
  });
}

// Focus intent survives until the session is attached: a just-created or just-resumed session
// appears in the state stream slightly after the request returns.
function focusTerminal(sessionId) {
  S.pendingFocus = { id: sessionId, until: Date.now() + 5000 };
  setTimeout(tryPendingFocus, 0);
}
function tryPendingFocus() {
  const want = S.pendingFocus;
  if (!want) return;
  if (Date.now() > want.until || !S.sel || S.sel.id !== want.id) { S.pendingFocus = null; return; }
  const t = S.terms.get(want.id);
  const s = findSession(want.id);
  if (s && s.view_mode === 'conversation') { if (focusComposer()) S.pendingFocus = null; return; }
  if (t && s && s.attached && !layerOpen()) { t.term.focus(); S.pendingFocus = null; }
}

// ---------------------------------------------------------------- conversation view
// Built only from the harness's structured messages (stream-json / app-server) and its native
// history. Items arrive as upserts/deltas over SSE; the DOM is patched per item.

// History is paged (docs/EXISTING_SESSIONS_API.md): the newest page first, older pages on request,
// and a refresh that returns only changed/new items by stable ID. A backend without paging answers
// with the whole list (no `page`), which is then shown through the old display window.
const PAGE_SIZE = 80;

function convFor(sid) {
  let c = S.convs.get(sid);
  if (!c) {
    c = {
      items: new Map(), order: [], turn: null, live: false, runId: null, history: null, info: {}, loaded: false, loading: false, limit: 200, error: null,
      paged: false, page: null, partial: [], nextBefore: null, nextSince: null, hasMore: false,
      olderLoading: false, olderError: null, refreshing: false, refreshNote: null,
    };
    S.convs.set(sid, c);
  }
  return c;
}

async function loadConversation(sid, { refresh = false } = {}) {
  const c = convFor(sid);
  if (c.loading) { c.reloadAfter = true; return; }
  if (wasUnlinked(findSession(sid))) {
    // A removed association is not read at all; re-adding it brings the native history back.
    pagerReplace(c, { items: [] });
    Object.assign(c, { loaded: true, unlinked: true, error: null, live: false, turn: null, stale: false });
    if (S.sel && S.sel.id === sid) renderConversation(findSession(sid), { full: true });
    return;
  }
  c.unlinked = false;
  c.loading = true;
  c.error = null;
  if (S.sel && S.sel.id === sid) updateConvChrome(findSession(sid), c);
  try {
    const data = await api('GET', `/api/sessions/${sid}/conversation?limit=${PAGE_SIZE}${refresh ? '&refresh=1' : ''}`);
    pagerReplace(c, data);
    viewPage(sid, c, data.items || []);
    c.turn = data.turn;
    c.live = data.live;
    c.runId = data.run_id;
    c.info = data.info || {};
    c.loaded = true;
    c.stale = false;
    c.olderError = null;
    c.refreshNote = null;
  } catch (e) {
    // The last view stays; the failure is shown next to it.
    c.error = e.message;
    c.loaded = true;
  } finally { c.loading = false; }
  if (c.reloadAfter) { c.reloadAfter = false; loadConversation(sid); return; }
  if (S.sel && S.sel.id === sid) renderConversation(findSession(sid), { full: true });
  if (!c.error) reconcileDeliveries(sid, [...c.items.values()]);
  checkInflight();
}

// User-initiated (or after "outside has ended"): fetch what changed since the last page and patch
// it in by ID — no rebuild, no scroll jump, the composer and its draft untouched.
async function refreshConversation(sid, { quiet = false } = {}) {
  const c = convFor(sid);
  if (!c.loaded || c.error || !c.paged || !c.nextSince) { loadConversation(sid, { refresh: true }); return; }
  if (c.loading || c.refreshing) return;
  c.refreshing = true;
  c.refreshNote = null;
  updateHistoryHead(sid);
  let result = null;
  try {
    const data = await api('GET', `/api/sessions/${sid}/conversation?limit=${PAGE_SIZE}&since=${encodeURIComponent(c.nextSince)}`);
    if (data.live && c.runId && data.run_id !== c.runId) { c.refreshing = false; loadConversation(sid); return; }
    result = pagerMerge(c, data);
    viewPage(sid, c, data.items || []);
    if (result.reset) c.olderError = null;
    c.turn = data.turn;
    c.live = data.live;
    c.runId = data.run_id;
    if (data.info) c.info = data.info;
    // An automatic refresh (selecting the session) only speaks up when something changed.
    c.refreshNote = result.reset ? '已重新读取最近的部分（原生历史被改写，或读取位置已过期）'
      : (result.added.length || result.changed.length) ? `新增 ${result.added.length} 条，更新 ${result.changed.length} 条` : quiet ? null : '没有新内容';
  } catch (e) {
    // The loaded history stays; the failure is shown next to it.
    c.refreshNote = `刷新失败：${e.message}`;
  } finally { c.refreshing = false; }
  if (result) reconcileDeliveries(sid, result.reset ? [...c.items.values()] : [...result.changed, ...result.added].map((id) => c.items.get(id)));
  if (!S.sel || S.sel.id !== sid) return;
  const s = findSession(sid);
  if (result && result.reset) { renderConversation(s, { full: true }); return; }
  if (result) for (const id of [...result.changed, ...result.added]) queuePatch(sid, id);
  updateHistoryHead(sid);
}

async function loadOlder(sid) {
  const c = convFor(sid);
  if (!c.paged || !c.hasMore || c.olderLoading) return;
  c.olderLoading = true;
  c.olderError = null;
  updateHistoryHead(sid);
  let fresh = [];
  let page = null;
  try {
    const data = await api('GET', `/api/sessions/${sid}/conversation?limit=${PAGE_SIZE}&before=${encodeURIComponent(c.nextBefore)}`);
    fresh = pagerPrepend(c, data);
    page = viewPage(sid, c, data.items || []);
  } catch (e) {
    c.olderError = historyFailure(e);
  } finally { c.olderLoading = false; }
  // Like the first page and a refresh, an older page settles what is kept for its messages (the
  // 待确认 card, a put-back copy, the send block), whether or not this session is still in view.
  if (page) reconcileDeliveries(sid, page.ids.map((id) => c.items.get(id)));
  const root = convEl;
  const s = findSession(sid);
  if (!s || !root || root.dataset.sid !== sid || !root._head) return;
  // Loaded copies that are now shown as sent are redrawn in place.
  if (page) for (const id of page.changed) if (!fresh.includes(id)) queuePatch(sid, id);
  keepAnchor(root._scroll, () => {
    const frag = document.createDocumentFragment();
    for (const id of fresh) {
      const node = itemNode(s, c.items.get(id));
      if (node) { frag.append(node); root._nodes.set(id, node); }
    }
    root._head.after(frag);
    updateHistoryHead(sid);
  });
  updateEmpty(root, s, c);
}

function onConv(msg) {
  const c = S.convs.get(msg.session_id);
  if (!c || !c.loaded) return;
  if (msg.op === 'reset' || (c.runId && c.runId !== msg.run_id)) { c.runId = msg.run_id; loadConversation(msg.session_id); return; }
  c.runId = msg.run_id;
  c.live = true;
  if (msg.op === 'turn') {
    c.turn = msg.turn;
    if (S.sel && S.sel.id === msg.session_id) updateConvChrome(findSession(msg.session_id), c);
  } else if (msg.op === 'upsert') {
    noteDelivery(msg.session_id, msg.item);
    const prev = c.items.get(msg.item.id);
    c.items.set(msg.item.id, deliveryView(S.unsent, msg.session_id, prev ? { ...prev, ...msg.item } : msg.item));
    if (!prev) c.order.push(msg.item.id);
    queuePatch(msg.session_id, msg.item.id);
  } else if (msg.op === 'delta') {
    const it = c.items.get(msg.id);
    if (!it) return;
    it[msg.field] = (it[msg.field] || '') + msg.delta;
    queuePatch(msg.session_id, msg.id);
  }
}

const patchQueue = new Set();
let patchTimer = null;
function queuePatch(sid, id) {
  if (!S.sel || S.sel.id !== sid) return;
  patchQueue.add(id);
  if (!patchTimer) patchTimer = setTimeout(flushPatches, 40);
}
function flushPatches() {
  patchTimer = null;
  const s = selectedSession();
  const root = convEl;
  if (!s || !root || root.dataset.sid !== s.session_id || !root._inner) { patchQueue.clear(); return; }
  const c = convFor(s.session_id);
  const keep = stickState(root);
  for (const id of patchQueue) {
    const it = c.items.get(id);
    if (!it) continue;
    const node = itemNode(s, it);
    const old = root._nodes.get(id);
    if (old && old.parentNode) {
      if (node) old.replaceWith(node); else old.remove();
    } else if (node) root._inner.append(node);
    if (node) root._nodes.set(id, node); else root._nodes.delete(id);
  }
  patchQueue.clear();
  if (c.paged && root._head) fillHistoryHead(root._head, s, c); // e.g. "empty" → messages arrived
  updateEmpty(root, s, c);
  restickOrJump(root, keep);
  updateConvChrome(s, c);
}

function stickState(root) {
  const sc = root._scroll;
  return { atBottom: sc.scrollTop + sc.clientHeight >= sc.scrollHeight - 60 };
}
function restickOrJump(root, keep) {
  const sc = root._scroll;
  if (keep.atBottom) { sc.scrollTop = sc.scrollHeight; if (root._jump) root._jump.hidden = true; }
  else if (root._jump) root._jump.hidden = false;
}

let convEl = null;
function convRoot() {
  if (!convEl) {
    convEl = h('div', { class: 'conv', hidden: true });
    $('#stage').insertBefore(convEl, $('#overlay'));
    convEl.addEventListener('click', (e) => {
      const a = e.target.closest('a[data-href]');
      if (a) { e.preventDefault(); openLink(a.dataset.href); }
    });
    convEl.addEventListener('keydown', (e) => {
      const a = e.target.closest && e.target.closest('a[data-href]');
      if (a && e.key === 'Enter') { e.preventDefault(); openLink(a.dataset.href); }
    });
  }
  return convEl;
}

function openLink(href) {
  if (hasNative('open_url')) nativeCall('open_url', { url: href });
  else window.open(href, '_blank', 'noopener,noreferrer');
}

function renderConversation(s, { full = false } = {}) {
  const root = convRoot();
  if (!s) { root.hidden = true; return; }
  root.hidden = false;
  const c = convFor(s.session_id);
  if ((!c.loaded || c.stale || (c.unlinked && !wasUnlinked(s))) && !c.loading) loadConversation(s.session_id);
  if (root.dataset.sid !== s.session_id || full || !root._inner) buildConversation(root, s, c);
  else updateConvChrome(s, c);
}

function buildConversation(root, s, c) {
  const same = root.dataset.sid === s.session_id;
  const keepTop = same && root._scroll ? stickState(root) : { atBottom: true };
  const prevScroll = same && root._scroll ? root._scroll.scrollTop : null;
  // Rebuilding the list must not touch the input box: replacing it would drop focus, the caret
  // and an in-progress input-method composition.
  const keepComposer = same && root._composer && root._composer.parentNode === root;
  root.dataset.sid = s.session_id;
  if (!keepComposer) root.replaceChildren();
  const inner = h('div', { class: 'conv-inner' });
  const scroll = h('div', { class: 'conv-scroll' }, inner);
  const jump = h('button', { class: 'btn btn-small jump', type: 'button', hidden: true, onclick: () => { scroll.scrollTop = scroll.scrollHeight; jump.hidden = true; } }, '↓ 新消息');
  let lastTop = 0;
  scroll.addEventListener('scroll', () => {
    if (scroll.scrollTop + scroll.clientHeight >= scroll.scrollHeight - 60) jump.hidden = true;
    // Reading upwards near the top fetches the next older page (the button does the same).
    if (scroll.scrollTop < 120 && scroll.scrollTop < lastTop && c.paged && c.hasMore && !c.olderLoading && !c.olderError) loadOlder(s.session_id);
    lastTop = scroll.scrollTop;
  });
  const scrollWrap = h('div', { style: 'position:relative;flex:1;min-height:0;display:flex;flex-direction:column' }, scroll, jump);
  root._inner = inner;
  root._scroll = scroll;
  root._jump = jump;
  root._nodes = new Map();
  root._head = h('div', { class: 'conv-head' });
  inner.append(root._head);
  fillHistoryHead(root._head, s, c);
  const ids = c.order;
  const from = c.paged ? 0 : Math.max(0, ids.length - c.limit);
  if (from > 0) {
    root._head.append(h('button', { class: 'btn btn-small conv-more', type: 'button', onclick: () => { c.limit += 200; buildConversation(root, s, c); } }, `显示更早的 ${from} 条`));
  }
  for (const id of ids.slice(from)) {
    const node = itemNode(s, c.items.get(id));
    if (node) { inner.append(node); root._nodes.set(id, node); }
  }
  root._empty = h('div', { class: 'conv-empty', hidden: true });
  inner.append(root._empty);
  updateEmpty(root, s, c);
  if (keepComposer) {
    if (root._scrollWrap && root._scrollWrap.parentNode === root) root._scrollWrap.replaceWith(scrollWrap);
    else root.insertBefore(scrollWrap, root._composer);
  } else {
    root._composer = buildComposer(s, c);
    root.append(scrollWrap, root._composer);
  }
  root._scrollWrap = scrollWrap;
  if (prevScroll !== null && !keepTop.atBottom) scroll.scrollTop = prevScroll;
  else scroll.scrollTop = scroll.scrollHeight;
  updateConvChrome(s, c);
}

// The top of the list: where the history came from, whether it is complete, refresh, and the
// control for older pages. Updated in place so a refresh never rebuilds the list.
function fillHistoryHead(head, s, c) {
  // Rebuilt only when what it shows changes (it is refreshed on every streamed patch).
  const st = historyState(c);
  const key = JSON.stringify([c.paged, st, c.loading, c.refreshing, c.refreshNote, c.error, c.live, c.hasMore, c.olderLoading, c.olderError, !!c.order.length, c.history && c.history.source]);
  if (head._key === key) return;
  head._key = key;
  head.replaceChildren();
  if (!c.paged) { const line = sourceLine(s, c); if (line) head.append(line); return; }
  const banner = historyBanner(c, {
    label: HARNESS[s.harness].label,
    loading: c.loading,
    refreshing: c.refreshing,
    error: c.error ? `无法读取会话内容：${c.error}` : null,
    refreshNote: c.refreshNote,
    onRefresh: c.live ? null : () => refreshConversation(s.session_id),
    onRetry: () => loadConversation(s.session_id, { refresh: true }),
  });
  if (banner) head.append(banner);
  const older = olderControl(c, { loading: c.olderLoading, error: c.olderError, onLoad: () => loadOlder(s.session_id), onReload: () => loadConversation(s.session_id) });
  if (older) head.append(older);
}

function updateHistoryHead(sid) {
  const root = convEl;
  const s = findSession(sid);
  if (!s || !root || root.dataset.sid !== sid || !root._head) return;
  const c = convFor(sid);
  if (!c.paged) return;
  fillHistoryHead(root._head, s, c);
  updateEmpty(root, s, c);
}

function sourceLine(s, c) {
  if (c.loading && !c.order.length) return h('div', { class: 'conv-source' }, stGlyph({ tone: 'idle', glyph: 'spin' }), '正在读取原生历史…');
  if (c.error) return h('div', { class: 'conv-source warn' }, `无法读取会话内容：${c.error}`);
  const hs = c.history || {};
  const label = HARNESS[s.harness].label;
  const parts = [];
  if (hs.source === 'claude-transcript') parts.push(`历史来自 ${label} 的会话记录`);
  else if (hs.source === 'codex') parts.push('历史来自 Codex（app-server）');
  else if (hs.source === 'cache') parts.push('原生历史不可读，显示的是 RepoBridge 上次的记录');
  if (!parts.length && !hs.error) return null;
  const line = h('div', { class: `conv-source ${hs.error ? 'warn' : ''}` }, parts.join(' · ') || null, hs.error && hs.source !== 'cache' ? h('span', {}, hs.error) : null);
  if (!c.live) line.append(h('button', { class: 'btn-plain', type: 'button', title: '重新读取原生历史（例如在官方桌面客户端里继续之后）', onclick: () => loadConversation(s.session_id, { refresh: true }) }, icon('refresh'), '刷新'));
  return line;
}

function updateEmpty(root, s, c) {
  if (!root._empty) return;
  const visible = c.order.some((id) => { const it = c.items.get(id); return it && it.type !== 'turn_end'; });
  const hs = historyState(c);
  // A failed or partial read is never covered by the welcome text.
  root._empty.hidden = visible || c.loading || !!c.error || hs.state === 'unavailable' || (c.paged && hs.state === 'partial');
  if (root._empty.hidden) return;
  const label = HARNESS[s.harness].label;
  if (wasUnlinked(s)) {
    root._empty.replaceChildren(
      h('h2', {}, '已移除关联'),
      h('div', {}, `原生历史保留在 ${label} 中，RepoBridge 不再读取它。用“重新添加…”关联回来后，可以在这里查看和继续同一个会话。`));
    return;
  }
  if (s.native_link || (c.paged && hs.state === 'empty' && s.native_session_id)) {
    root._empty.replaceChildren(
      h('h2', {}, '原生历史里没有可显示的消息'),
      h('div', {}, `已从 ${label} 的原生记录读取，这个会话没有可以显示的用户或助手消息。${isLinked(s) && s.can_resume ? '继续时会用原生恢复接着这个会话，不会新建会话。' : ''}`));
    return;
  }
  root._empty.replaceChildren(
    h('h2', {}, s.active ? `${label} 已连接` : `与 ${label} 对话`),
    h('div', {}, `消息、工具调用和权限请求会以对话形式显示。这里使用 ${label} 自己的登录和设置；RepoBridge 不会替你发送消息或批准操作。`));
}

// ---------------------------------------------------------------- items

const TOOL_STATE = {
  running: { tone: 'ok', glyph: 'spin', label: '进行中' },
  waiting: { tone: 'warn', glyph: 'alert', label: '等待你确认' },
  ok: { tone: 'ok', glyph: 'check', label: '完成' },
  failed: { tone: 'bad', glyph: 'x', label: '失败' },
  declined: { tone: 'bad', glyph: 'x', label: '已拒绝' },
  interrupted: { tone: 'idle', glyph: 'ring', label: '已中断' },
  unknown: { tone: 'idle', glyph: 'ring', label: '结果未知' },
};

function itemNode(s, it) {
  if (!it) return null;
  if (it.type === 'user') {
    const outcome = deliveryOutcome(it);
    const meta = outcome === 'pending' ? (it.delivery && it.delivery.state === 'queued' ? '等待连接…' : '发送中…')
      : outcome === 'not_sent' ? '没有发出' : outcome === 'unknown' ? '发送结果待确认' : null;
    const cid = itemClientId(it);
    const putBack = outcome === 'not_sent' && s.session_id && !s.preview && !S.unsent.placed.has(cid) && !(S.unsent.held.get(s.session_id) || []).some((x) => x.clientId === cid)
      ? h('button', { class: 'btn-plain', type: 'button', title: '把这条没有发出的消息放回输入框（有草稿时接在后面）', onclick: () => restoreFromItem(s.session_id, it) }, '放回输入框') : null;
    const atts = (it.attachments || []).length ? h('div', { class: 'msg-atts' }, it.attachments.map((a) => h('span', { class: 'att-chip small', title: a.name }, icon(a.kind === 'image' ? 'image' : 'file'), h('span', { class: 'att-name' }, a.name)))) : null;
    return h('div', { class: `msg user selectable ${outcome === 'not_sent' ? 'failed' : outcome === 'unknown' ? 'uncertain' : ''}`, dataset: { id: it.id } }, atts, it.text || null,
      meta ? h('div', { class: 'meta', title: (it.delivery && it.delivery.message) || null }, meta, putBack ? ' · ' : null, putBack) : null);
  }
  if (it.type === 'assistant') {
    const md = renderMarkdown(it.text || '', { onCopy: (code) => copyText(code, '已复制代码') });
    if (it.streaming) (md.lastElementChild && md.lastElementChild.tagName === 'P' ? md.lastElementChild : md).classList.add('caret');
    return h('div', { class: 'msg assistant selectable', dataset: { id: it.id } }, md,
      it.text_truncated ? h('div', { class: 'note-line warn' }, '回复过长，只显示了开头部分') : null,
      it.streaming ? null : h('div', { class: 'msg-actions' }, h('button', { class: 'icon-btn small', type: 'button', title: '复制这条回复', 'aria-label': '复制这条回复', onclick: () => copyText(it.text || '', '已复制') }, icon('copy'))));
  }
  if (it.type === 'reasoning') {
    const d = h('details', { class: 'reasoning', dataset: { id: it.id } });
    if (S.openItems.has(it.id)) d.open = true;
    d.addEventListener('toggle', () => { if (d.open) S.openItems.add(it.id); else S.openItems.delete(it.id); });
    d.append(h('summary', {}, icon('chevron', 'chev'), h('span', {}, it.label || (it.streaming ? '正在思考…' : '思考过程'))), renderMarkdown(it.text || ''));
    return d;
  }
  if (it.type === 'tool') return toolNode(s, it);
  if (it.type === 'permission') return permissionNode(s, it);
  if (it.type === 'turn_end') {
    if (it.status === 'interrupted') return h('div', { class: 'turn-note' }, '已停止这一轮');
    if (it.status === 'failed') {
      const auth = /login|auth|api key|401|403|credential|登录/i.test(it.error || '');
      return h('div', { class: 'turn-fail', role: 'alert' }, icon('warning'), h('div', { class: 'txt selectable' },
        h('b', {}, '这一轮没有完成'), it.error ? `：${it.error}` : '',
        auth ? h('div', { class: 'hint', style: 'margin-top:4px' }, `看起来是登录问题。请在普通终端里用 ${HARNESS[s.harness].label} 自己的登录命令处理；RepoBridge 不读取也不保存登录信息。`) : null));
    }
    if (it.model) return h('div', { class: 'turn-model', title: '这一轮回复里，模型 API 报告的模型名' }, it.model);
    return null;
  }
  if (it.type === 'notice') return h('div', { class: `note-line ${it.level || ''}`, role: it.level === 'error' ? 'alert' : null }, it.text);
  return null;
}

function toolNode(s, it) {
  const open = S.openItems.has(it.id);
  const st = TOOL_STATE[it.status] || TOOL_STATE.unknown;
  const meta = [];
  if (it.status === 'waiting') meta.push('等待你确认');
  else if (it.status === 'declined') meta.push('已拒绝');
  else if (it.status === 'interrupted') meta.push('已中断');
  if (it.exit_code !== undefined && it.exit_code !== null && it.exit_code !== 0) meta.push(`退出码 ${it.exit_code}`);
  if (it.subagent_steps) meta.push(`子任务 ${it.subagent_steps} 步`);
  const box = h('div', { class: `tool ${open ? 'open' : ''}`, dataset: { id: it.id } });
  const toggle = () => { if (S.openItems.has(it.id)) S.openItems.delete(it.id); else S.openItems.add(it.id); if (s.repaint) s.repaint(it.id); else queuePatch(s.session_id, it.id); };
  box.append(h('div', { class: 'tool-row', role: 'button', tabindex: '0', 'aria-expanded': String(open), title: `${it.name}${it.title ? ` · ${it.title}` : ''} · ${st.label}`,
    onclick: toggle, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } } },
  icon('chevron', 'chev'), stGlyph(st), h('span', { class: 'name' }, it.name || '工具'), h('span', { class: 'title' }, relText(s, it.title)),
  meta.length ? h('span', { class: 'meta' }, meta.join(' · ')) : null));
  if (!open) return box;
  const body = h('div', { class: 'tool-body selectable' });
  const files = (it.files || []).filter((f) => f && f.path);
  if (files.length) {
    body.append(h('div', { class: 'tool-files' }, files.map((f) => h('button', { class: 'file-chip', type: 'button', title: `在“变更”中查看 ${f.path}`, onclick: () => showFileDiff(s, f.path) }, icon('changes'), relText(s, f.path)))));
    for (const f of files) if (f.diff) body.append(diffInline(f.diff));
  }
  if (it.input) body.append(h('div', { class: 'label' }, '输入'), h('pre', {}, relText(s, it.input)));
  if (it.output) {
    const pre = h('pre', {}, relText(s, it.output));
    body.append(h('div', { class: 'label' }, '输出'), pre);
    if (it.output_truncated) body.append(h('div', { class: 'hint' }, `输出过长，这里只显示开头部分${it.output_omitted ? `（省略约 ${Math.round(it.output_omitted / 1024)} KB）` : ''}；完整内容在原生会话中。`));
  } else if (it.status === 'running') body.append(h('div', { class: 'hint' }, '正在运行…'));
  if (it.error) body.append(h('div', { class: 'label' }, '错误'), h('pre', { class: 'err' }, it.error));
  box.append(body);
  return box;
}

function diffInline(text) {
  const box = h('div', { class: 'diff-inline' });
  for (const line of text.split('\n')) {
    let cls = '';
    if (/^(diff --git |index |\+\+\+ |--- )/.test(line)) continue;
    if (line.startsWith('+')) cls = 'add'; else if (line.startsWith('-')) cls = 'del'; else if (line.startsWith('@@')) cls = 'hunk';
    box.append(h('span', { class: `ln ${cls}` }, line || ' '));
  }
  return box;
}

function showFileDiff(s, path) {
  const rel = path.startsWith(`${s.workdir}/`) ? path.slice(s.workdir.length + 1) : path;
  S.diff = { sid: s.session_id, path: rel, text: '', truncated: false };
  setPref('inspector_open', true);
  setPref('inspector_tab', 'changes');
  render();
  loadDiff(s.session_id, rel).then(() => loadChanges(s.session_id));
}

const PERM_KIND = { command: '运行命令', file: '修改文件', permissions: '额外权限', question: '回答问题', plan: '确认计划', form: '填写信息' };

function permissionNode(s, it) {
  const label = HARNESS[s.harness].label;
  if (it.status !== 'pending') {
    const answered = it.kind === 'question' || it.kind === 'form';
    const text = { allowed: answered ? '已回答' : '已允许', denied: answered ? '没有回答' : '已拒绝', cancelled: '已取消（这一轮已结束或请求已撤回）', expired: '已失效（这一轮已结束）' }[it.status] || it.status;
    const ok = it.status === 'allowed';
    return h('div', { class: `perm-done ${ok ? 'allowed' : it.status === 'denied' ? 'denied' : ''}`, dataset: { id: it.id } },
      icon(ok ? 'check' : 'close'), h('span', {}, `${text}：${it.tool}${it.title && it.title !== it.tool ? ` · ${relText(s, it.title)}` : ''}`));
  }
  const what = PERM_KIND[it.kind] || `使用 ${it.tool}`;
  const who = it.kind === 'form' ? `${it.tool}（经 ${label}）` : label;
  const card = h('div', { class: 'perm-card', role: 'group', 'aria-label': `${who} 请求${what}`, dataset: { id: it.id } },
    h('div', { class: 'perm-head' }, icon('warning'), `${who} 请求${what}`));
  if (it.kind === 'form') card.append(h('div', { class: 'selectable' }, it.title));
  else if (it.title && it.kind !== 'question') card.append(h('div', { class: 'mono selectable', style: 'font:12.5px var(--mono);overflow-wrap:anywhere' }, relText(s, it.title)));
  if (it.kind === 'plan' && it.detail) card.append(h('div', { class: 'selectable', style: 'max-height:320px;overflow:auto' }, renderMarkdown(it.detail)));
  else if (it.diff) card.append(diffInline(relText(s, it.diff)));
  else if (it.detail && it.detail !== it.title && it.kind !== 'question') card.append(h('pre', { class: 'selectable' }, relText(s, it.detail)));
  if (it.reason) card.append(h('div', { class: 'why' }, `原因：${it.reason}`));
  if (it.grant_root) card.append(h('div', { class: 'why' }, `“本会话内都允许”会覆盖：${homeify(it.grant_root)}`));
  const answer = (decision, answers) => guarded(`perm:${it.id}`, () => api('POST', `/api/sessions/${s.session_id}/permission`, { request_id: it.request_id, decision, answers }));
  if (it.kind === 'question') { card.append(...questionCard(s, it, answer)); return card; }
  if (it.kind === 'form') { card.append(...formCard(s, it, answer)); return card; }
  const opts = it.options || [];
  const order = ['deny', 'allow_session', 'allow_always', 'allow'];
  const buttons = opts.slice().sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)).map((o) => h('button', {
    class: `btn btn-small ${o.id === 'allow' ? 'btn-primary' : ''}`, type: 'button', onclick: () => answer(o.id),
  }, o.label));
  card.append(h('div', { class: 'actions' }, buttons));
  return card;
}

// ---------------------------------------------------------------- composer

function autosize(ta) {
  ta.style.height = 'auto';
  ta.style.height = `${Math.min(ta.scrollHeight, Math.round(window.innerHeight * 0.38))}px`;
}

function composerBlock(s) {
  // Why the composer cannot be used right now, or null.
  if (S.state.environment.refusal) return '当前环境不能启动原生会话';
  if (wasUnlinked(s)) return RESUME_REASON_TEXT.unlinked;
  if (s.archived) return '会话已归档；取消归档后才能继续';
  if (isLinked(s) && !s.active && !s.can_resume) return RESUME_REASON_TEXT[s.native_link.resume_reason] || '这个原生会话当前不能恢复，只能查看历史';
  if (s.active && !s.attached) return '上次运行遗留的进程仍在；请先在工具栏结束它';
  if (!s.active && !harnessOk(s.harness)) return `找不到 ${HARNESS[s.harness].label}`;
  if (S.switching.has(s.session_id)) return '正在切换视图…';
  return null;
}

function updateConvChrome(s, c) {
  const root = convEl;
  if (!s || !root || root.dataset.sid !== s.session_id || !root._ta) return;
  const label = HARNESS[s.harness].label;
  const running = !!s.turn;
  const blocked = composerBlock(s);
  const pendingPerm = [...c.items.values()].some((x) => x.type === 'permission' && x.status === 'pending');
  root._ta.disabled = !!blocked;
  root._box.classList.toggle('disabled', !!blocked);
  root._ta.placeholder = blocked || (linkHold(s) ? `确认外部已结束后，发送消息会用原生恢复继续这个 ${label} 会话` : s.external ? `这个会话已在 ${s.external.app} 中打开` : !s.active
    ? (s.can_resume ? `发送消息，用原生恢复继续这个 ${label} 会话` : `发送第一条消息，启动 ${label}`)
    : `给 ${label} 发消息`);
  const atts = attachments(s.session_id);
  const uploading = atts.some((a) => a.uploading);
  const ready = atts.filter((a) => a.id && !a.error);
  root._send.replaceChildren(icon(running ? 'square' : 'send', running ? 'i-fill' : ''));
  root._send.classList.toggle('stop', running);
  root._send.title = running ? '停止这一轮（Esc）' : uploading ? '附件还在上传…' : '发送（↩）';
  root._send.setAttribute('aria-label', running ? '停止这一轮' : '发送');
  const waiting = deliveryBlock(s);
  root._send.disabled = running ? false : (!!blocked || !!waiting || uploading || (!root._ta.value.trim() && !ready.length));
  if (!running && waiting) root._send.title = waiting;
  root._hint.textContent = running ? 'Esc 停止这一轮' : '↩ 发送 · ⇧↩ 换行 · @ 引用文件';
  renderControls(s);
  const st = root._status;
  st.className = 'conv-status';
  st.replaceChildren();
  const pick = settingsStatus(s);
  if (S.switching.has(s.session_id)) st.append(stGlyph({ tone: 'idle', glyph: 'spin' }), '正在切换视图：结束原连接，再用原生恢复接续…');
  else if (pendingPerm) { st.classList.add('warn'); st.append(stGlyph({ tone: 'warn', glyph: 'alert' }), `${label} 在等你确认权限或回答问题`); }
  else if (waiting && !running) { st.classList.add('warn'); st.append(stGlyph({ tone: 'warn', glyph: 'alert' }), h('span', { class: 'grow' }, waiting)); }
  else if (pick && pick.tone === 'bad') {
    st.classList.add('bad');
    st.append(icon('warning'), h('span', { class: 'grow selectable' }, pick.text),
      h('button', { class: 'btn-plain', type: 'button', onclick: () => { S.dismissed.add(pick.dismiss); updateConvChrome(findSession(s.session_id), convFor(s.session_id)); } }, '知道了'));
  } else if (s.active && s.phase === 'starting') st.append(stGlyph({ tone: 'ok', glyph: 'spin' }), `正在连接 ${label}…`);
  else if (running) {
    const started = s.turn.started_at ? Date.parse(s.turn.started_at) : Date.now();
    const secs = Math.max(0, Math.round((Date.now() - started) / 1000));
    st.append(stGlyph({ tone: 'ok', glyph: 'spin' }), `${label} 正在工作…`, h('span', { class: 'hint' }, ` ${secs} 秒`));
    if (pick) st.append(h('span', { class: 'hint' }, ` · ${pick.text}`));
  } else if (pick) st.append(stGlyph({ tone: 'idle', glyph: 'ring' }), h('span', { class: 'hint' }, pick.text));
  else if (s.active && s.attached) st.append(stGlyph({ tone: 'ok', glyph: 'dot' }), h('span', { class: 'hint' }, `已连接 ${label}`));
  else if (!s.active && s.run) {
    st.append(h('span', { class: 'hint' }, s.can_resume ? '未连接。发送消息时会用原生恢复接续同一个会话。' : '未连接。'));
  }
}
setInterval(() => { const s = selectedSession(); if (s && s.turn && s.view_mode === 'conversation') updateConvChrome(s, convFor(s.session_id)); }, 1000);

async function sendFromComposer(sid, confirmExternal = false) {
  const root = convEl;
  const s = findSession(sid);
  if (!root || !root._ta || !s) return;
  const text = root._ta.value;
  const atts = attachments(sid);
  const ids = atts.filter((a) => a.id && !a.error).map((a) => a.id);
  if ((!text.trim() && !ids.length) || composerBlock(s) || atts.some((a) => a.uploading) || S.pending.has(`send:${sid}`)) return;
  const waiting = deliveryBlock(s);
  if (waiting) { toast(waiting, 'error'); return; } // the draft stays in the box
  const askExternal = (ext) => confirmPopover(root._send, externalPrompt(findSession(sid) || s, ext, () => sendFromComposer(sid, true)));
  if (s.external && !confirmExternal) { askExternal(s.external); return; }
  const clientId = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const sent = atts.filter((a) => ids.includes(a.id));
  unsentReleaseBox(S.unsent, sid);
  S.pending.add(`send:${sid}`);
  root._ta.value = '';
  S.drafts.delete(sid);
  autosize(root._ta);
  hidePop();
  updateConvChrome(s, convFor(sid));
  const track = () => {
    unsentTrack(S.unsent, { sid, clientId, text, atts: sent, at: Date.now() });
    S.attach.set(sid, attachments(sid).filter((a) => !ids.includes(a.id)));
    renderAttachRow(sid);
  };
  try {
    const res = await api('POST', `/api/sessions/${sid}/send`, { text, client_id: clientId, confirm_external: confirmExternal, attachments: ids });
    // Accepted locally; tracked by client_id until a receipt or the CLI settles it. 200 is not
    // native delivery: queued / sending stay open.
    track();
    const c = S.convs.get(sid);
    noteDelivery(sid, res && res.delivery ? { client_id: clientId, type: 'user', text, attachments: sent, delivery: res.delivery } : c && c.items.get(`user:${clientId}`));
    setTimeout(checkInflight, 400); // the run may have ended before this response arrived
  } catch (e) {
    const d = e.details || {};
    if (!e.code) {
      // No answer reached the page: the request may still have been accepted. Its receipt decides;
      // without one the message is kept as unknown, not put back as unsent.
      track();
      const entry = S.unsent.inflight.get(clientId);
      if (!entry) return; // its event already confirmed it
      Object.assign(entry, { at: 0, tries: 2, lostAnswer: true });
      queryReceipt(entry);
      toast(`${e.message}。正在核对这条消息是否已被接收…`, 'error');
      return;
    }
    // Refused before acceptance (the backend answered with an error): definitely not sent. The
    // attachments are still in the box; the text goes back, or next to a draft typed meanwhile.
    unsentTrack(S.unsent, { sid, clientId, text, atts: [], at: Date.now() });
    const box = boxOf(sid);
    box.attIds = box.attIds.filter((id) => !ids.includes(id)); // this message's own attachments
    const r = unsentFail(S.unsent, sid, clientId, box);
    applyUnsent(sid, r, '这条消息没有发出', { quiet: true });
    if (d.reason === 'delivery_unknown' && d.client_id) {
      // An earlier message's result is unknown: show that one (from its receipt) as the reason.
      try { noteDelivery(sid, await api('GET', `/api/sessions/${sid}/delivery?client_id=${encodeURIComponent(d.client_id)}`)); } catch (x) {
        if (d.delivery) noteDelivery(sid, { client_id: d.client_id, type: 'user', text: '', attachments: [], delivery: d.delivery });
      }
      toast(e.message, 'error');
    } else if (d.external && !confirmExternal) {
      if (r && r.to === 'held') {
        // Confirming would send the new draft instead; only record that outside use has ended.
        confirmPopover(root._send, externalPrompt(findSession(sid) || s, d.external, () => guarded(`return:${sid}`, async () => {
          await api('POST', `/api/sessions/${sid}/desktop/return`, {});
          toast('已记录外部已结束。原消息保留在输入框上方，放回后再发送。');
        })));
      } else askExternal(d.external);
    } else fail(e);
  } finally { S.pending.delete(`send:${sid}`); }
}

function interruptTurn(sid) {
  guarded(`interrupt:${sid}`, () => api('POST', `/api/sessions/${sid}/interrupt`, {}));
}

function focusComposer() {
  const root = convEl;
  if (root && !root.hidden && root._ta && !root._ta.disabled && !layerOpen()) { root._ta.focus(); return true; }
  return false;
}

// ---------------------------------------------------------------- view switching & desktop

function switchView(s, mode, anchor) {
  const sid = s.session_id;
  const label = HARNESS[s.harness].label;
  const target = mode === 'conversation' ? '对话' : '终端';
  const run = async (confirmUnknown) => {
    S.switching.add(sid);
    render();
    try {
      await api('POST', `/api/sessions/${sid}/view`, { view_mode: mode, confirm_unknown: confirmUnknown });
      S.convs.delete(sid);
      toast(`已切换到${target}视图${s.attached ? '，并接续了同一个原生会话' : ''}`);
    } catch (e) {
      if (e.details && e.details.idle === 'unknown') {
        S.switching.delete(sid);
        render();
        confirmPopover(anchor, { title: '无法确认是否空闲', text: `${e.message}。仍要切换吗？`, confirm: '仍然切换', danger: true, onConfirm: () => run(true) });
        return;
      }
      fail(e);
    } finally {
      S.switching.delete(sid);
      render();
      focusTerminal(sid);
    }
  };
  if (!s.attached) { run(false); return; }
  confirmPopover(anchor, {
    title: `切换到${target}视图？`,
    text: `会先在空闲时结束当前与 ${label} 的连接（原生会话已保存），再用 ${label} 的原生恢复接续同一个会话。不会发送任何消息，也不会换 harness。`,
    confirm: '切换',
    onConfirm: () => run(false),
  });
}

function openInDesktop(s, anchor) {
  const d = s.desktop || {};
  if (!d.available) { toast(d.reason || '无法在桌面客户端中打开', 'error'); return; }
  const label = HARNESS[s.harness].label;
  const go = async (confirmUnknown) => {
    let r;
    try {
      r = await api('POST', `/api/sessions/${s.session_id}/desktop/open`, { release: true, confirm_unknown: confirmUnknown });
    } catch (e) {
      if (e.details && e.details.idle === 'unknown') {
        confirmPopover(anchor, { title: '无法确认是否空闲', text: `${e.message}。仍要继续吗？`, confirm: '仍然继续', danger: true, onConfirm: () => go(true) });
        return;
      }
      fail(e);
      return;
    }
    if (r.status === 'acknowledged') toast(`${label} 已确认：正在 ${r.app} 中打开这个会话。请到 ${r.app} 中查看。`);
    else if (r.status === 'requested') toast(`已请 ${r.app} 打开这个对话。系统接受了请求；请在 ${r.app} 中确认看到的是正确的对话。`);
    else toast(`${r.app} 没有确认打开${r.message ? `：${r.message}` : ''}`, 'error');
  };
  confirmPopover(anchor, {
    title: `在 ${d.app} 中继续？`,
    text: (s.attached ? `RepoBridge 会先结束这里与 ${label} 的连接（原生会话已保存），然后` : '')
      + `在 ${d.app} 中打开同一个会话。之后请在 ${d.app} 中继续；回到这里时，需要确认那边的这一轮已经结束。`,
    confirm: `打开 ${d.app}`,
    onConfirm: () => go(false),
  });
}

async function desktopReturn(s) {
  await guarded(`return:${s.session_id}`, async () => {
    await api('POST', `/api/sessions/${s.session_id}/desktop/return`, {});
    toast('已回到 RepoBridge。继续时会接续同一个原生会话。');
    if (s.view_mode === 'conversation') refreshConversation(s.session_id);
  });
}

function viewToggle(s) {
  const busy = S.switching.has(s.session_id);
  return h('div', { class: 'seg-inline view-seg', role: 'radiogroup', 'aria-label': '视图' },
    [['conversation', '对话', 'chat', '对话视图：消息、工具调用和权限请求以卡片显示'], ['terminal', '终端', 'terminal', '终端视图：原生 CLI，与在终端中运行完全相同']].map(([v, l, ic, tip]) => h('button', {
      type: 'button', role: 'radio', 'aria-checked': String(s.view_mode === v), 'aria-pressed': String(s.view_mode === v), disabled: busy || !!s.archived,
      title: tip, onclick: (e) => { if (s.view_mode !== v) switchView(findSession(s.session_id), v, e.currentTarget); },
    }, icon(ic), h('span', { class: 'tb-label-2' }, l))));
}

// ---------------------------------------------------------------- selection & loading

function select(sel, { focus = true } = {}) {
  const prev = selectedSession();
  if (prev && S.terms.get(prev.session_id)) S.terms.get(prev.session_id).term.blur();
  S.sel = sel;
  S.diff = null;
  if (sel && sel.type === 'session') {
    setPref('selected_session', sel.id);
    const s = findSession(sel.id);
    if (s && S.prefs.collapsed_projects.includes(s.project_id)) {
      setPref('collapsed_projects', S.prefs.collapsed_projects.filter((x) => x !== s.project_id));
    }
    if (s) loadForSession(s);
  } else {
    setPref('selected_session', null);
  }
  if (window.innerWidth < 760) S.sidebarOverlayOpen = false;
  render();
  if (focus && sel && sel.type === 'session') focusTerminal(sel.id);
}

function loadForSession(s) {
  if (s.view_mode === 'conversation') {
    const c = convFor(s.session_id);
    if (!c.loaded || c.stale || c.error) loadConversation(s.session_id);
    else if (!c.live) refreshConversation(s.session_id, { quiet: true });
  }
  loadEvents(s.session_id);
  scheduleChanges(s.session_id, 0);
  if (S.prefs.inspector_open && S.prefs.inspector_tab === 'details') loadDetails(s.session_id);
}

async function loadEvents(sid) {
  try {
    const events = await api('GET', `/api/sessions/${sid}/activity`);
    S.events.set(sid, events);
    if (S.sel && S.sel.id === sid) renderInspector();
  } catch (e) { /* the notice area shows connection problems */ }
}

function onActivity(ev) {
  const list = S.events.get(ev.session_id);
  if (list && !list.some((x) => x.seq === ev.seq)) list.push(ev);
  if (S.sel && ev.session_id === S.sel.id) {
    if (S.prefs.inspector_open && S.prefs.inspector_tab === 'activity') scheduleActivityRender();
    scheduleChanges(ev.session_id, 1200);
  }
}

const changeTimers = new Map();
function scheduleChanges(sid, delay) {
  clearTimeout(changeTimers.get(sid));
  changeTimers.set(sid, setTimeout(() => loadChanges(sid), delay));
}
async function loadChanges(sid) {
  try {
    const c = await api('GET', `/api/sessions/${sid}/changes`);
    S.changes.set(sid, c);
    if (S.diff && S.diff.sid === sid) {
      if (!c.files.some((f) => f.path === S.diff.path)) S.diff = null;
      else loadDiff(sid, S.diff.path);
    }
    if (S.sel && S.sel.id === sid) { renderToolbar(); if (S.prefs.inspector_tab === 'changes') renderInspector(); }
  } catch (e) { /* not fatal: the chip just stays hidden */ }
}
setInterval(() => { const s = selectedSession(); if (s && s.active && !document.hidden) loadChanges(s.session_id); }, 8000);

async function loadDiff(sid, path) {
  try {
    const d = await api('GET', `/api/sessions/${sid}/diff?path=${encodeURIComponent(path)}`);
    // Native tools report absolute paths; the server answers with the project-relative one.
    S.diff = { sid, path: d.path || path, text: d.diff, truncated: d.truncated };
    if (S.sel && S.sel.id === sid) renderInspector();
  } catch (e) { fail(e); }
}

async function loadDetails(sid) {
  try {
    S.details.set(sid, await api('GET', `/api/sessions/${sid}`));
    if (S.sel && S.sel.id === sid && S.prefs.inspector_tab === 'details') renderInspector();
  } catch (e) { /* ignore */ }
}

// ---------------------------------------------------------------- actions

async function guarded(key, fn, button) {
  if (S.pending.has(key)) return undefined;
  S.pending.add(key);
  if (button) button.classList.add('busy');
  try { return await fn(); } catch (e) { fail(e); return undefined; } finally {
    S.pending.delete(key);
    if (button) button.classList.remove('busy');
  }
}

// The explicit confirmation before a second writer could appear: an official desktop client the
// user opened, or (for an added existing session) any outside client RepoBridge cannot observe.
function externalPrompt(s, ext, onConfirm) {
  const label = HARNESS[s.harness].label;
  if ((ext && ext.via === 'native-link') || linkHold(s)) {
    return {
      title: `继续这个 ${label} 会话？`,
      text: `这个会话来自 RepoBridge 之外，${holdText(s)}确认后会用 ${label} 的原生恢复继续同一个会话（原生 ID 不变，不会新建会话）。`,
      confirm: '外部已结束，继续',
      onConfirm,
    };
  }
  return {
    title: '在 RepoBridge 中继续？',
    text: `这个会话已在 ${ext.app} 中打开。RepoBridge 看不到那边是否还在执行；请先确认那边的这一轮已经结束，避免两边同时写入。`,
    confirm: '那边已结束，继续',
    onConfirm,
  };
}

async function startRun(s, kind, button, confirmExternal = false) {
  if (s.external && !confirmExternal) {
    confirmPopover(button || $('#toolbar'), externalPrompt(s, s.external, () => startRun(findSession(s.session_id), kind, button, true)));
    return;
  }
  await guarded(`start:${s.session_id}`, async () => {
    try {
      await api('POST', `/api/sessions/${s.session_id}/start`, { kind, confirm_external: confirmExternal });
    } catch (e) {
      if (e.details && e.details.external && !confirmExternal) {
        confirmPopover(button || $('#toolbar'), externalPrompt(findSession(s.session_id) || s, e.details.external, () => startRun(findSession(s.session_id), kind, button, true)));
        return;
      }
      throw e;
    }
  }, button);
  focusTerminal(s.session_id);
}

function stopSession(s, anchor) {
  if (s.view_mode === 'conversation' && s.transport === 'structured') {
    const label = HARNESS[s.harness].label;
    confirmPopover(anchor, {
      title: `断开 ${label}？`,
      text: s.turn ? `${label} 正在处理当前这一轮，断开会先停止这一轮。原生会话已保存，之后发送消息会自动恢复。`
        : `这会结束与 ${label} 的连接进程，并释放这个文件夹的写入权。原生会话已保存，之后发送消息会自动恢复。`,
      confirm: '断开',
      danger: !!s.turn,
      onConfirm: () => guarded(`stop:${s.session_id}`, () => api('POST', `/api/sessions/${s.session_id}/stop`, {})),
    });
    return;
  }
  confirmPopover(anchor, {
    title: `停止 ${HARNESS[s.harness].label}？`,
    text: s.phase === 'working'
      ? '它正在处理当前请求，停止会中断这一轮。原生会话已保存，之后可以恢复。'
      : '这会结束会话进程（相当于关闭终端）。原生会话已保存，之后可以恢复。',
    confirm: '停止',
    danger: true,
    onConfirm: () => guarded(`stop:${s.session_id}`, () => api('POST', `/api/sessions/${s.session_id}/stop`, {})),
  });
}

function archiveSession(s, anchor) {
  confirmPopover(anchor, {
    title: '归档这个会话？',
    text: '它会从列表中隐藏，可在侧边栏底部的设置里显示已归档会话后找回。原生会话历史和项目文件不会被删除。',
    confirm: '归档',
    onConfirm: () => guarded(`archive:${s.session_id}`, async () => {
      await api('POST', `/api/sessions/${s.session_id}/archive`, {});
      disposeTerm(s.session_id);
      if (S.sel && S.sel.id === s.session_id && !S.prefs.show_archived) select({ type: 'project', id: s.project_id }, { focus: false });
    }),
  });
}

function unarchiveSession(s) {
  guarded(`unarchive:${s.session_id}`, () => api('POST', `/api/sessions/${s.session_id}/unarchive`, {}));
}

function removeProject(p, anchor) {
  confirmPopover(anchor, {
    title: `从 RepoBridge 移除「${p.name}」？`,
    text: '只是不再在这里显示。文件夹、其中的文件和原生会话历史都不会被删除，之后可以重新添加。',
    confirm: '移除',
    danger: true,
    onConfirm: () => guarded(`rmproj:${p.project_id}`, async () => {
      await api('POST', `/api/projects/${p.project_id}/archive`, {});
      const sp = selectedProject();
      if (sp && sp.project_id === p.project_id) S.sel = null;
    }),
  });
}

function revealProject(p) { guarded(`reveal:${p.project_id}`, () => api('POST', `/api/projects/${p.project_id}/reveal`, {})); }

async function copyText(text, done = '已复制') {
  try { await navigator.clipboard.writeText(text); } catch (e) {
    const ta = h('textarea', { style: 'position:fixed;opacity:0' });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
  }
  toast(done);
}

function resumeCommand(s) { return `cd ${shellQuote(s.workdir)} && ${HARNESS[s.harness].resume(s.native_session_id)}`; }

function toggleInspector(tab) {
  const s = selectedSession();
  if (!s) return;
  if (S.prefs.inspector_open && (!tab || S.prefs.inspector_tab === tab)) setPref('inspector_open', false);
  else {
    setPref('inspector_open', true);
    if (tab) setPref('inspector_tab', tab);
    if (S.prefs.inspector_tab === 'details') loadDetails(s.session_id);
    if (S.prefs.inspector_tab === 'activity' && !S.events.has(s.session_id)) loadEvents(s.session_id);
    if (S.prefs.inspector_tab === 'changes') loadChanges(s.session_id);
  }
  render();
}

function toggleSidebar() {
  if (window.innerWidth < 760) S.sidebarOverlayOpen = !S.sidebarOverlayOpen;
  else setPref('sidebar_collapsed', !S.prefs.sidebar_collapsed);
  applyLayout();
}

function cycleSession(dir) {
  const list = visibleTree().flatMap((g) => g.sessions);
  if (!list.length) return;
  const i = list.findIndex((s) => S.sel && s.session_id === S.sel.id);
  const next = list[(i + dir + list.length) % list.length];
  select({ type: 'session', id: next.session_id });
}

// ---------------------------------------------------------------- render: layout

function render() {
  if (!S.state) return;
  applyLayout();
  renderSidebar();
  renderToolbar();
  renderNotice();
  renderStage();
  renderInspector();
  updateWindowTitle();
}

function applyLayout() {
  if (!S.prefs) return;
  const app = $('#app');
  const W = window.innerWidth;
  const narrow = W < 760;
  const sideVisible = narrow ? S.sidebarOverlayOpen : !S.prefs.sidebar_collapsed;
  const sideW = S.prefs.sidebar_width;
  const inspOpen = !!(S.prefs.inspector_open && selectedSession());
  const inspW = Math.min(S.prefs.inspector_width, Math.max(300, W - 360));
  app.style.setProperty('--sidebar-w', `${sideW}px`);
  app.classList.toggle('sidebar-overlay', narrow);
  app.classList.toggle('sidebar-hidden', !sideVisible);
  const inlineSide = !narrow && sideVisible ? sideW : 0;
  const inspOverlay = inspOpen && W - inlineSide - inspW < 520;
  // Width of the inspector's grid column: zero unless it is open and docked (inline var wins over CSS).
  app.style.setProperty('--inspector-w', `${inspOpen ? inspW : 0}px`);
  app.classList.toggle('inspector-overlay', inspOverlay);
  app.classList.toggle('inspector-hidden', !inspOpen);
  $('#scrim').hidden = !((narrow && sideVisible) || inspOverlay);
  const mainWidth = W - inlineSide - (inspOpen && !inspOverlay ? inspW : 0);
  // Labels collapse in two steps so the status and primary action keep their words longest.
  $('#toolbar').classList.toggle('compact', mainWidth < 860);
  $('#toolbar').classList.toggle('tight', mainWidth < 600);
  scheduleFit();
}

$('#scrim').addEventListener('click', () => {
  if ($('#app').classList.contains('sidebar-overlay') && S.sidebarOverlayOpen) S.sidebarOverlayOpen = false;
  else if ($('#app').classList.contains('inspector-overlay')) setPref('inspector_open', false);
  render();
});
window.addEventListener('resize', () => applyLayout());

function makeResizer(el, side) {
  el.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    el.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    const move = (ev) => {
      if (side === 'sidebar') S.prefs.sidebar_width = Math.round(Math.min(420, Math.max(200, ev.clientX)));
      else {
        const max = Math.min(900, window.innerWidth - (S.prefs.sidebar_collapsed ? 0 : S.prefs.sidebar_width) - 420);
        S.prefs.inspector_width = Math.round(Math.min(Math.max(300, max), Math.max(300, window.innerWidth - ev.clientX)));
      }
      applyLayout();
    };
    const up = () => {
      el.releasePointerCapture(e.pointerId);
      el.classList.remove('dragging');
      document.body.style.cursor = '';
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      if (side === 'sidebar') setPref('sidebar_width', S.prefs.sidebar_width);
      else setPref('inspector_width', S.prefs.inspector_width);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
  });
  el.addEventListener('dblclick', () => {
    if (side === 'sidebar') setPref('sidebar_width', 260); else setPref('inspector_width', 420);
    applyLayout();
  });
}

// ---------------------------------------------------------------- render: sidebar

function visibleTree() {
  const q = S.filter.trim().toLowerCase();
  return S.state.projects.map((p) => {
    const sessions = p.sessions.filter((s) => (S.prefs.show_archived || !s.archived)
      && (!q || s.title.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)
        || HARNESS[s.harness].label.toLowerCase().includes(q) || (s.native_session_id || '').toLowerCase().startsWith(q)));
    return { project: p, sessions };
  }).filter((g) => !q || g.sessions.length || g.project.name.toLowerCase().includes(q));
}

function renderSidebar() {
  const tree = $('#tree');
  const focusKey = document.activeElement && tree.contains(document.activeElement)
    ? (document.activeElement.closest('[data-key]') || {}).dataset?.key : null;
  const scroll = tree.scrollTop;
  tree.replaceChildren();
  if (!S.state.projects.length) {
    tree.append(h('div', { class: 'tree-empty' }, '还没有项目。添加一个本地文件夹后，就可以在其中打开 Claude Code 或 Codex 会话。'));
    return;
  }
  const groups = visibleTree();
  if (!groups.length) tree.append(h('div', { class: 'tree-empty' }, '没有匹配的会话。'));
  for (const { project: p, sessions } of groups) {
    const collapsed = S.prefs.collapsed_projects.includes(p.project_id) && !S.filter;
    const attn = p.sessions.filter((s) => s.attention).length;
    const projectSelected = S.sel && S.sel.type === 'project' && S.sel.id === p.project_id;
    const head = h('div', {
      class: `row project-row ${collapsed ? '' : 'open'} ${projectSelected ? 'selected' : ''}`,
      tabindex: '0', role: 'treeitem', 'aria-expanded': String(!collapsed), dataset: { key: `p:${p.project_id}` },
      title: homeify(p.root_path),
      onclick: (e) => { if (e.target.closest('.trail, .disclosure')) return; select({ type: 'project', id: p.project_id }, { focus: false }); },
      oncontextmenu: (e) => { e.preventDefault(); projectMenu(p, { x: e.clientX, y: e.clientY }); },
      onkeydown: treeKey,
    },
    h('button', {
      class: 'icon-btn small disclosure', type: 'button', tabindex: '-1', 'aria-label': collapsed ? '展开' : '折叠',
      onclick: (e) => { e.stopPropagation(); toggleCollapsed(p.project_id); },
    }, icon('chevron')),
    h('span', { class: 'name' }, p.name),
    h('span', { class: 'trail' },
      collapsed && attn ? h('span', { class: 'badge-attn rest-only', title: '有会话需要你确认' }, String(attn)) : null,
      h('button', { class: 'icon-btn small hover-only', type: 'button', title: `在 ${p.name} 中新建会话`, 'aria-label': '新建会话',
        onclick: (e) => { e.stopPropagation(); newSessionMenu(p, e.currentTarget); } }, icon('plus')),
      h('button', { class: 'icon-btn small hover-only', type: 'button', title: '项目操作', 'aria-label': '项目操作',
        onclick: (e) => { e.stopPropagation(); projectMenu(p, e.currentTarget); } }, icon('more'))));
    const group = h('div', { class: 'group', role: 'group' }, head);
    if (!collapsed) {
      if (!sessions.length) group.append(h('div', { class: 'row session-row', style: 'color:var(--text-3);font-size:12px' }, '还没有会话'));
      for (const s of sessions) group.append(sessionRow(s));
    }
    tree.append(group);
  }
  tree.scrollTop = scroll;
  if (focusKey) { const el = tree.querySelector(`[data-key="${CSS.escape(focusKey)}"]`); if (el) el.focus(); }
}

function sessionRow(s) {
  const st = statusOf(s);
  const selected = S.sel && S.sel.type === 'session' && S.sel.id === s.session_id;
  const from = s.handoff_from && findSession(s.handoff_from);
  const tip = `${s.title}\n${HARNESS[s.harness].label} · ${st.label}${from ? `\n交接自「${from.title}」` : ''}${s.native_link ? '\n添加的已有原生会话' : ''}`;
  const trail = h('span', { class: 'trail' }, h('span', { class: 'tag rest-only' }, HARNESS[s.harness].short));
  if (wasUnlinked(s)) {
    // Removed association: brought back with "add existing", not by unarchiving.
  } else if (s.archived) {
    trail.append(h('button', { class: 'icon-btn small hover-only', type: 'button', title: '取消归档', 'aria-label': '取消归档',
      onclick: (e) => { e.stopPropagation(); unarchiveSession(s); } }, icon('unarchive')));
  } else if (!s.active) {
    trail.append(h('button', { class: 'icon-btn small hover-only', type: 'button', title: '归档（不删除历史）', 'aria-label': '归档',
      onclick: (e) => { e.stopPropagation(); archiveSession(s, e.currentTarget); } }, icon('archive')));
  }
  return h('div', {
    class: `row session-row ${selected ? 'selected' : ''} ${s.archived ? 'archived' : ''}`,
    tabindex: '0', role: 'treeitem', 'aria-selected': String(!!selected), title: tip, dataset: { key: `s:${s.session_id}` },
    onclick: () => select({ type: 'session', id: s.session_id }),
    oncontextmenu: (e) => { e.preventDefault(); sessionMenu(s, { x: e.clientX, y: e.clientY }); },
    onkeydown: treeKey,
  },
  stGlyph(st),
  from ? h('span', { class: 'relation', title: `交接自「${from.title}」` }, '↳') : null,
  h('span', { class: 'name' }, s.title),
  s.native_link ? h('span', { class: 'link-mark', title: '添加的已有原生会话' }, icon('link')) : null,
  trail);
}

function treeKey(e) {
  if (e.target !== e.currentTarget) return;
  const rows = [...$('#tree').querySelectorAll('.row[tabindex="0"]')];
  const i = rows.indexOf(e.currentTarget);
  if (e.key === 'ArrowDown') { e.preventDefault(); if (rows[i + 1]) rows[i + 1].focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); if (rows[i - 1]) rows[i - 1].focus(); }
  else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.currentTarget.click(); }
  else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.currentTarget.classList.contains('project-row')) {
    const id = e.currentTarget.dataset.key.slice(2);
    const collapsed = S.prefs.collapsed_projects.includes(id);
    if ((e.key === 'ArrowLeft') !== collapsed) { e.preventDefault(); toggleCollapsed(id); }
  }
}

function toggleCollapsed(projectId) {
  const list = S.prefs.collapsed_projects;
  setPref('collapsed_projects', list.includes(projectId) ? list.filter((x) => x !== projectId) : [...list, projectId]);
  renderSidebar();
}

// ---------------------------------------------------------------- render: toolbar

function renderToolbar() {
  const bar = $('#toolbar');
  if (S.renaming) return;
  bar.replaceChildren();
  bar.append(h('button', { class: 'icon-btn', type: 'button', title: '显示/隐藏侧边栏（⌃⌘S）', 'aria-label': '显示或隐藏侧边栏', onclick: toggleSidebar }, icon('sidebar')));
  const s = selectedSession();
  const p = selectedProject();
  if (!s) {
    bar.append(h('div', { class: 'tb-title' },
      h('div', { class: 'tb-title-line' }, h('span', { class: 'tb-name', style: 'cursor:default' }, p ? p.name : 'RepoBridge')),
      h('div', { class: 'tb-sub' }, p ? `${shortPath(p.root_path, 64)}${p.branch ? ` · ${p.branch}` : ''}` : '项目与原生会话的工作台')));
    if (p) {
      bar.append(h('div', { class: 'tb-group' },
        h('button', { class: 'icon-btn', type: 'button', title: '项目操作', 'aria-label': '项目操作', onclick: (e) => projectMenu(p, e.currentTarget) }, icon('more'))));
    }
    return;
  }
  const st = statusOf(s);
  bar.append(h('div', { class: 'tb-title' },
    h('div', { class: 'tb-title-line' },
      h('span', { class: 'tb-name', title: '点击重命名', onclick: () => beginRename(s) }, s.title),
      h('button', { class: 'icon-btn small', type: 'button', title: '会话操作', 'aria-label': '会话操作', onclick: (e) => sessionMenu(s, e.currentTarget) }, icon('caret'))),
    h('div', { class: 'tb-sub' },
      h('span', { class: `harness ${s.harness}` }, HARNESS[s.harness].label),
      ` · ${p ? p.name : ''}${p && p.branch ? ` · ${p.branch}` : ''}`)));
  const tone = st.tone === 'warn' ? 'warn' : st.tone === 'bad' ? 'bad' : '';
  const right = h('div', { class: 'tb-group' }, h('span', { class: `status-label ${tone}`, title: st.label }, stGlyph(st), h('span', { class: 'tb-label' }, st.label)), h('span', { class: 'tb-sep' }), viewToggle(s), h('span', { class: 'tb-sep' }));
  const open = S.prefs.inspector_open;
  const tab = S.prefs.inspector_tab;
  const c = S.changes.get(s.session_id);
  if (c && c.git && c.files.length) {
    let add = 0;
    let del = 0;
    let known = false;
    for (const f of c.files) if (f.added !== undefined && f.added !== '-') { add += Number(f.added); del += Number(f.removed); known = true; }
    right.append(h('button', {
      class: `diff-chip ${open && tab === 'changes' ? 'active' : ''}`, type: 'button',
      title: `${c.files.length} 个文件有未提交的变更（⌘⇧D）`, onclick: () => toggleInspector('changes'),
    }, icon('changes'), known ? [h('span', { class: 'add' }, `+${add}`), h('span', { class: 'del' }, `−${del}`)] : null,
    h('span', { class: 'tb-label-2' }, `${c.files.length} 个文件`)));
  } else {
    right.append(h('button', { class: `icon-btn ${open && tab === 'changes' ? 'active' : ''}`, type: 'button', title: '变更（⌘⇧D）', 'aria-label': '变更', onclick: () => toggleInspector('changes') }, icon('changes')));
  }
  right.append(
    h('button', { class: `icon-btn ${open && tab === 'activity' ? 'active' : ''}`, type: 'button', title: '活动（⌘⇧A）', 'aria-label': '活动', onclick: () => toggleInspector('activity') }, icon('activity')),
    h('button', { class: `icon-btn ${open && tab === 'details' ? 'active' : ''}`, type: 'button', title: '详情（⌘⇧I）', 'aria-label': '详情', onclick: () => toggleInspector('details') }, icon('info')),
    h('span', { class: 'tb-sep' }));
  // Element.append would print a null; the handoff button is left out for a removed association.
  if (!wasUnlinked(s)) right.append(h('button', { class: 'btn', type: 'button', title: '交接：在同一项目中新建会话继续这项工作', onclick: () => openHandoff(s) }, icon('handoff'), h('span', { class: 'tb-label-2' }, '交接')));
  const primary = primaryAction(s);
  if (primary) right.append(primary);
  bar.append(right);
}

function primaryAction(s) {
  const label = HARNESS[s.harness].label;
  if (s.view_mode === 'conversation' && s.active && s.attached) {
    return h('button', { class: 'btn', type: 'button', disabled: s.stopping, title: `结束与 ${label} 的连接（原生会话会保存；之后发消息会自动恢复）`, onclick: (e) => stopSession(s, e.currentTarget) }, icon('stop', 'i-fill'), h('span', { class: 'tb-label' }, '断开'));
  }
  if (s.view_mode === 'conversation' && !s.active && !s.archived) return null; // the composer is the primary action
  if (s.active && s.attached) {
    return h('button', { class: 'btn', type: 'button', disabled: s.stopping, title: `停止 ${label} 进程（原生会话会保存）`, onclick: (e) => stopSession(s, e.currentTarget) }, icon('stop', 'i-fill'), h('span', { class: 'tb-label' }, '停止'));
  }
  if (s.active) {
    return h('button', { class: 'btn btn-danger', type: 'button', title: '结束上次运行遗留的进程', onclick: (e) => confirmPopover(e.currentTarget, {
      title: '结束遗留进程？', text: '这个进程由上次运行的 RepoBridge 启动，当前窗口无法接入它的终端。结束后可以原生恢复会话。', confirm: '结束进程', danger: true,
      onConfirm: () => guarded(`stop:${s.session_id}`, () => api('POST', `/api/sessions/${s.session_id}/stop`, {})),
    }) }, icon('stop', 'i-fill'), h('span', { class: 'tb-label' }, '结束进程'));
  }
  if (wasUnlinked(s)) return h('button', { class: 'btn', type: 'button', title: '用“添加已有会话”重新关联同一个原生会话', onclick: () => reAddSession(s) }, icon('link'), h('span', { class: 'tb-label' }, '重新添加…'));
  if (s.archived) return h('button', { class: 'btn', type: 'button', onclick: () => unarchiveSession(s) }, icon('unarchive'), h('span', { class: 'tb-label' }, '取消归档'));
  if (s.can_resume) return h('button', { class: 'btn btn-primary', type: 'button', title: `用 ${label} 原生恢复同一会话`, onclick: (e) => startRun(s, 'resume', e.currentTarget) }, icon('resume'), h('span', { class: 'tb-label' }, '恢复'));
  if (s.can_start_fresh) return h('button', { class: 'btn btn-primary', type: 'button', onclick: (e) => startRun(s, 'new', e.currentTarget) }, icon('play', 'i-fill'), h('span', { class: 'tb-label' }, s.status === 'new' ? '启动' : '重新启动'));
  return null;
}

function beginRename(s) {
  const bar = $('#toolbar');
  const name = bar.querySelector('.tb-name');
  if (!name) return;
  S.renaming = true;
  const input = h('input', { class: 'tb-name-input', maxlength: '120', 'aria-label': '会话标题' });
  input.value = s.title;
  name.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const title = input.value.trim();
    if (save && title && title !== s.title) {
      try { await api('POST', `/api/sessions/${s.session_id}/rename`, { title }); } catch (e) { fail(e); }
    }
    S.renaming = false;
    renderToolbar();
    focusTerminal(s.session_id);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

// ---------------------------------------------------------------- render: notices

function renderNotice() {
  const area = $('#notice');
  if (!S.state) return;
  area.replaceChildren();
  const add = (tone, iconName, msg, ...actions) => area.append(h('div', { class: `notice ${tone}`, role: tone === 'info' ? 'status' : 'alert' },
    icon(iconName), h('div', { class: 'msg' }, msg), ...actions));
  if (!S.connected) add('bad', 'warning', '与 RepoBridge 本地服务的连接已断开，正在重连…');
  if (S.state.environment.refusal) add('bad', 'warning', `当前环境不能启动原生会话：${S.state.environment.refusal}`);
  const s = selectedSession();
  const p = selectedProject();
  if (p && !p.exists) add('bad', 'warning', `找不到项目文件夹 ${homeify(p.root_path)}。它可能被移动或删除了。`);
  if (!s) return;
  const label = HARNESS[s.harness].label;
  if (linkHold(s) && !s.active) {
    add('info', 'external', [h('b', {}, '这个会话来自 RepoBridge 之外'), `：${holdText(s)}`],
      s.view_mode === 'conversation' ? h('button', { class: 'btn btn-small', type: 'button', title: '重新读取原生历史，查看在别处新增的内容', onclick: () => refreshConversation(s.session_id) }, '刷新历史') : null,
      h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => confirmOutsideEnded(s, e.currentTarget) }, '外部已结束…'));
  } else if (s.external && !s.active) {
    add('info', 'external', [h('b', {}, `已在 ${s.external.app} 中打开`), `（${clock(s.external.opened_at)}${s.external.via === 'cli /desktop' ? '，通过终端里的 /desktop' : ''}）。RepoBridge 看不到那边是否还在执行；在那边结束这一轮后，再回到这里继续。`],
      s.view_mode === 'conversation' ? h('button', { class: 'btn btn-small', type: 'button', title: '重新读取原生历史，查看在那边新增的内容', onclick: () => refreshConversation(s.session_id) }, '刷新历史') : null,
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => desktopReturn(s) }, '回到 RepoBridge 继续'));
  }
  if (wasUnlinked(s)) {
    add('info', 'link', [h('b', {}, '已移除关联'), `：原生历史保留在 ${label} 中。重新添加后会回到这个会话，继续前仍需确认外部已经结束。`],
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => reAddSession(s) }, '重新添加…'));
  } else if (isLinked(s) && s.native_link.resume_reason && !s.active) {
    const nl = s.native_link;
    const sameAsProject = p && !p.exists && p.root_path === s.workdir;
    const why = nl.resume_reason === 'directory_missing' ? `${sameAsProject ? '项目文件夹' : `工作目录 ${homeify(s.workdir)} `}不存在。历史仍可查看；恢复这个文件夹后才能继续。`
      : RESUME_REASON_TEXT[nl.resume_reason] || nl.resume_reason;
    add('warn', 'warning', [h('b', {}, '不能继续这个原生会话'), `：${why}`]);
  }
  if (s.attention && s.view_mode === 'conversation' && s.transport === 'structured') {
    // The permission card in the conversation is the place to answer.
  } else if (s.attention) {
    add('warn', 'warning', [h('b', {}, `${label} 需要你确认`), `：${s.attention.message || '权限请求'}。请在下方终端中回答。`],
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => focusTerminal(s.session_id) }, '转到终端'));
  } else if (s.active && !s.attached) {
    add('warn', 'warning', '这个会话由上次运行的 RepoBridge 启动，进程仍在，但当前窗口无法接入它的终端。');
  } else if (!s.active && s.run && s.run.status === 'failed') {
    const act = s.can_resume ? h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => startRun(s, 'resume', e.currentTarget) }, '恢复')
      : s.can_start_fresh ? h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => startRun(s, 'new', e.currentTarget) }, '重新启动') : null;
    const gone = /No conversation found|no rollout found|not found|不存在/i.test(s.run.failure || '');
    add('bad', 'warning', [h('b', {}, '会话失败'), `：${s.run.failure || '原因未知'}`,
      gone ? h('div', { class: 'hint', style: 'margin-top:2px' }, '原生历史似乎已不存在，无法恢复同一会话；可以用“交接”在同一项目中新建会话继续。') : null],
    gone ? h('button', { class: 'btn btn-small', type: 'button', onclick: () => openHandoff(s) }, '交接到新会话') : act,
      h('button', { class: 'btn btn-small', type: 'button', onclick: () => { setPref('inspector_open', true); setPref('inspector_tab', 'details'); loadDetails(s.session_id); render(); } }, '查看详情'));
  } else if (!s.active && s.run && s.run.status === 'interrupted') {
    add('warn', 'warning', [h('b', {}, '会话被中断'), '：RepoBridge 关闭时它仍在运行。原生会话已保存。'],
      s.can_resume ? h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => startRun(s, 'resume', e.currentTarget) }, '恢复') : null);
  }
  if (!s.active && !s.archived && !harnessOk(s.harness)) {
    const info = harnessInfo(s.harness);
    add('bad', 'warning', `找不到 ${label}${info && info.problem ? `：${info.problem}` : ''}`, h('button', { class: 'btn btn-small', type: 'button', onclick: openSettings }, '检查设置'));
  }
}

// ---------------------------------------------------------------- render: stage

function renderStage() {
  const s = selectedSession();
  const conv = !!s && s.view_mode === 'conversation';
  for (const [id, t] of S.terms) t.el.classList.toggle('visible', !!s && !conv && id === s.session_id);
  renderConversation(conv ? s : null);
  if (s && !conv) {
    const t = termFor(s.session_id);
    t.el.classList.add('visible');
    t.el.classList.toggle('readonly', !s.attached);
    t.term.options.disableStdin = !s.attached;
    if (!t.loaded && t.runId === null && s.run) loadHistory(s.session_id);
    scheduleFit();
  }
  renderOverlay();
}

function renderOverlay() {
  const ov = $('#overlay');
  ov.replaceChildren();
  ov.className = 'overlay';
  if (!S.state) return;
  const s = selectedSession();
  if (!s) {
    const p = selectedProject();
    ov.append(p ? projectCard(p) : welcomeCard());
    return;
  }
  if (s.view_mode === 'conversation') return;
  const t = S.terms.get(s.session_id);
  const label = HARNESS[s.harness].label;
  if (!s.active && s.status === 'new') { ov.append(startCard(s)); return; }
  if (s.active && s.phase === 'starting' && (!t || t.end === 0)) {
    ov.className = 'overlay floating';
    ov.append(h('div', { class: 'pill' }, stGlyph({ tone: 'ok', glyph: 'spin' }), `正在启动 ${label}…`));
    return;
  }
  if (!s.active && t && t.end > 0) {
    ov.className = 'overlay floating';
    ov.append(h('div', { class: 'pill' }, icon('terminal'), '上次运行的终端输出（只读）'));
  }
}

function welcomeCard() {
  return h('div', { class: 'card' },
    h('h1', {}, '欢迎使用 RepoBridge'),
    h('p', {}, '以项目为中心，使用你已有的 Claude Code 和 Codex。每个会话都是原生 CLI：对话、工具、权限、登录和计费都由它自己处理；你可以用图形“对话”或原生“终端”来使用它。'),
    h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: openAddProject }, icon('folder-plus'), '添加项目文件夹')),
    cliList());
}

function cliList() {
  return h('div', { class: 'cli-list' }, S.state.harnesses.map((x) => h('div', { class: 'cli-item' },
    stGlyph(x.available ? { tone: 'ok', glyph: 'dot', label: '可用' } : { tone: 'bad', glyph: 'x', label: '不可用' }),
    h('span', {}, x.label),
    h('span', { class: 'v', title: x.binary || x.problem || '' }, x.available ? (x.version || '已找到') : '未找到'))));
}

function projectCard(p) {
  const busy = busySessionIn(p);
  const recent = p.sessions.filter((s) => !s.archived).slice(-5).reverse();
  return h('div', { class: 'card' },
    h('h1', {}, p.name),
    h('p', {}, busy ? `「${busy.title}」正在这个项目中运行。同一文件夹同时只能有一个会话写入。` : '在这个项目中打开一个原生会话。换 harness 时，用“交接”新建会话继续，而不是在原会话里切换。'),
    h('div', { class: 'actions' },
      ['claude-code', 'codex'].map((k) => {
        const info = harnessInfo(k);
        return h('button', { class: `btn ${k === S.prefs.last_harness ? 'btn-primary' : ''}`, type: 'button', disabled: !info || !info.available,
          title: info && !info.available ? info.problem : null, onclick: () => openNewSession(p.project_id, k) }, icon('plus'), `新建 ${HARNESS[k].label} 会话`);
      }),
      h('button', { class: 'btn', type: 'button', title: '关联以前在 Claude Code 或 Codex 中创建的会话（不复制、不启动）', onclick: () => openAddExisting({ projectId: p.project_id }) }, icon('history'), '添加已有会话…')),
    h('div', { class: 'facts' },
      h('div', { class: 'fact' }, h('span', { class: 'k' }, '文件夹'), h('span', { class: 'v', title: p.root_path }, homeify(p.root_path))),
      h('div', { class: 'fact' }, h('span', { class: 'k' }, '分支'), h('span', { class: 'v' }, p.branch || '不是 Git 仓库或无法读取'))),
    recent.length ? h('div', { class: 'recent' }, h('div', { class: 'h' }, '最近的会话'),
      recent.map((s) => h('button', { class: 'list-btn', type: 'button', onclick: () => select({ type: 'session', id: s.session_id }) },
        stGlyph(statusOf(s)), h('span', { class: 'name' }, s.title), h('span', { class: 'meta' }, `${HARNESS[s.harness].short} · ${statusOf(s).label}`)))) : null);
}

function startCard(s) {
  const label = HARNESS[s.harness].label;
  const p = findProject(s.project_id);
  const busy = p && p.sessions.find((x) => x.active && x.session_id !== s.session_id);
  if (s.native_link) {
    const why = !s.can_resume ? (RESUME_REASON_TEXT[s.native_link.resume_reason] || '这个原生会话当前不能恢复') : null;
    return h('div', { class: 'card' },
      h('h1', {}, `继续这个 ${label} 会话`),
      h('p', {}, `这是添加到项目的已有原生会话。会在「${p ? p.name : ''}」中用 ${label} 的原生恢复（${HARNESS[s.harness].resume(s.native_session_id)}）打开同一个会话，不会新建会话，也不会替你发送消息。`),
      linkHold(s) ? h('div', { class: 'callout info' }, icon('external'), h('div', {}, `这个会话来自 RepoBridge 之外，${holdText(s)}`)) : null,
      why ? h('div', { class: 'callout warn' }, icon('warning'), h('div', {}, why)) : null,
      busy ? h('div', { class: 'callout warn' }, icon('warning'), h('div', {}, `「${busy.title}」正在这个项目中运行。先停止它，才能继续这个会话。`)) : null,
      h('div', { class: 'actions' },
        h('button', { class: 'btn btn-primary', type: 'button', disabled: !!busy || !!why || !harnessOk(s.harness) || !!wasUnlinked(s), onclick: (e) => startRun(s, 'resume', e.currentTarget) }, icon('resume'), '恢复'),
        busy ? h('button', { class: 'btn', type: 'button', onclick: () => select({ type: 'session', id: busy.session_id }) }, `切换到「${busy.title}」`) : null));
  }
  return h('div', { class: 'card' },
    h('h1', {}, `启动 ${label}`),
    h('p', {}, `将在「${p ? p.name : ''}」中打开原生 ${label} 交互会话。对话、工具和权限都在终端里由 ${label} 处理；RepoBridge 不读取登录信息，也不会替你发送消息。`),
    busy ? h('div', { class: 'callout warn' }, icon('warning'), h('div', {}, `「${busy.title}」正在这个项目中运行。先停止它，才能启动这个会话。`)) : null,
    h('div', { class: 'actions' },
      h('button', { class: 'btn btn-primary', type: 'button', disabled: !!busy || !harnessOk(s.harness), onclick: (e) => startRun(s, 'new', e.currentTarget) }, icon('play', 'i-fill'), `启动 ${label}`),
      busy ? h('button', { class: 'btn', type: 'button', onclick: () => select({ type: 'session', id: busy.session_id }) }, `切换到「${busy.title}」`) : null));
}

// ---------------------------------------------------------------- render: inspector

let activityTimer = null;
function scheduleActivityRender() { clearTimeout(activityTimer); activityTimer = setTimeout(renderInspector, 150); }

function renderInspector() {
  const s = selectedSession();
  for (const b of $('#inspector-tabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(!!S.prefs && b.dataset.tab === S.prefs.inspector_tab));
  if (!S.prefs || !S.prefs.inspector_open || !s) return;
  const body = $('#inspector-body');
  const prev = body.querySelector('.pane-scroll, .diff');
  const keep = prev ? { cls: prev.className, top: prev.scrollTop, atBottom: prev.scrollTop + prev.clientHeight >= prev.scrollHeight - 40 } : null;
  const same = body.dataset.tab === S.prefs.inspector_tab && body.dataset.sid === s.session_id;
  body.replaceChildren();
  body.dataset.tab = S.prefs.inspector_tab;
  body.dataset.sid = s.session_id;
  if (S.prefs.inspector_tab === 'changes') body.append(...changesPane(s));
  else if (S.prefs.inspector_tab === 'activity') body.append(...activityPane(s));
  else body.append(...detailsPane(s));
  const scroller = body.querySelector('.pane-scroll, .diff');
  if (!scroller) return;
  if (S.prefs.inspector_tab === 'activity') {
    if (!same || !keep || keep.atBottom) scroller.scrollTop = scroller.scrollHeight;
    else {
      scroller.scrollTop = keep.top;
      const jump = h('button', { class: 'btn btn-small jump', type: 'button', onclick: () => { scroller.scrollTop = scroller.scrollHeight; jump.remove(); } }, '↓ 新活动');
      body.append(jump);
      scroller.addEventListener('scroll', () => { if (scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 40) jump.remove(); });
    }
  } else if (same && keep && keep.cls === scroller.className) scroller.scrollTop = keep.top;
}

function changesPane(s) {
  const c = S.changes.get(s.session_id);
  const bar = h('div', { class: 'pane-bar' },
    h('span', { class: 'grow' }, c && c.git ? `${c.branch || '(detached)'} · ${c.files.length ? `${c.files.length} 个文件有未提交的变更` : '没有未提交的变更'}` : '工作区变更'),
    h('button', { class: 'icon-btn small', type: 'button', title: '刷新', 'aria-label': '刷新变更', onclick: () => loadChanges(s.session_id) }, icon('refresh')));
  if (!c) return [bar, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, '正在读取…'))];
  if (!c.git) return [bar, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, c.error || '这个文件夹不是 Git 仓库，无法显示变更。'))];
  if (!c.files.length) return [bar, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, '工作区是干净的。会话修改文件后，变更会出现在这里。'))];
  const files = h('div', { class: 'files', role: 'list' }, c.files.map((f) => {
    const code = { modified: 'M', added: 'A', deleted: 'D', renamed: 'R', copied: 'C', untracked: 'U', unmerged: '!', 'type changed': 'T' }[f.kind] || '?';
    const slash = f.path.lastIndexOf('/');
    const dir = slash >= 0 ? f.path.slice(0, slash + 1) : '';
    const base = slash >= 0 ? f.path.slice(slash + 1) : f.path;
    return h('div', { class: `file ${S.diff && S.diff.path === f.path ? 'selected' : ''}`, role: 'listitem', tabindex: '0', title: f.from ? `${f.from} → ${f.path}` : f.path,
      onclick: () => loadDiff(s.session_id, f.path), onkeydown: (e) => { if (e.key === 'Enter') loadDiff(s.session_id, f.path); } },
    h('span', { class: `code ${code}`, title: kindLabel(f.kind) }, code),
    h('span', { class: 'path' }, h('bdi', {}, h('span', { class: 'dir' }, dir), base)),
    f.added !== undefined ? h('span', { class: 'stat' }, `+${f.added} −${f.removed}`) : null);
  }));
  if (S.diff && S.diff.sid === s.session_id) {
    const diff = h('div', { class: 'diff selectable' });
    for (const line of S.diff.text.split('\n')) {
      let cls = '';
      if (/^(diff --git |index |\+\+\+ |--- )/.test(line)) continue; // the file is already selected above
      if (/^(new file|deleted file|similarity|rename |old mode|new mode)/.test(line)) cls = 'meta';
      else if (line.startsWith('+')) cls = 'add';
      else if (line.startsWith('-')) cls = 'del';
      else if (line.startsWith('@@')) cls = 'hunk';
      diff.append(h('span', { class: `ln ${cls}` }, line || ' '));
    }
    if (S.diff.truncated) diff.append(h('span', { class: 'ln meta' }, '… 差异过长，已截断'));
    return [bar, files, diff];
  }
  // Nothing picked yet: show the first file instead of an empty "pick a file" state.
  if (!S.diff || S.diff.sid !== s.session_id) setTimeout(() => { if (!S.diff || S.diff.sid !== s.session_id) loadDiff(s.session_id, c.files[0].path); }, 0);
  return [bar, files, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, '正在读取差异…'))];
}

function settingsLabel(payload) {
  return Object.entries(payload || {}).map(([k, v]) => `${FIELD_NAME[k] || k}→${v === null ? '默认' : v}`).join('，');
}

function kindLabel(kind) {
  return { modified: '已修改', added: '新增', deleted: '已删除', renamed: '重命名', copied: '复制', untracked: '未跟踪的新文件', unmerged: '有冲突', 'type changed': '类型变化' }[kind] || kind;
}

function activityPane(s) {
  const events = S.events.get(s.session_id);
  const note = s.view_mode === 'conversation'
    ? '对话视图的请求、工具调用、权限决定和每轮结束，来自原生结构化消息。'
    : s.harness === 'codex'
      ? 'Codex 只向 RepoBridge 报告每轮完成和审批请求；逐个工具的过程请看终端。'
      : 'Claude Code 的请求、工具调用、权限请求和停止，来自只记录的 hooks。';
  const head = h('div', { class: 'pane-bar' }, h('span', { class: 'grow', title: note }, note));
  if (!events) return [head, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, '正在读取…'))];
  const items = buildTimeline(events);
  if (!items.length) return [head, h('div', { class: 'pane-scroll' }, h('div', { class: 'empty' }, '还没有活动。在终端里开始对话后，这里会按轮次记录。'))];
  return [head, h('div', { class: 'pane-scroll selectable', style: 'padding:0' }, h('div', { class: 'timeline' }, items))];
}

function buildTimeline(events) {
  const out = [];
  let turn = null;
  const tools = new Map();
  const step = (cls, g, content) => h('div', { class: `step ${cls}` }, h('span', { class: 'glyph' }, g), h('span', { class: 'txt' }, content));
  const ensureTurn = (time) => {
    if (!turn) {
      turn = h('div', { class: 'turn' }, h('div', { class: 'turn-head' }, h('div', { class: 'turn-prompt', style: 'color:var(--text-3)' }, '（终端中的操作）'), h('span', { class: 'time' }, clock(time))));
      out.push(turn);
    }
    return turn;
  };
  const newTurn = (prompt, time) => {
    const p = h('div', { class: 'turn-prompt', title: '点击展开或收起' }, prompt);
    p.addEventListener('click', () => p.classList.toggle('expanded'));
    turn = h('div', { class: 'turn' }, h('div', { class: 'turn-head' }, p, h('span', { class: 'time' }, clock(time))));
    out.push(turn);
  };
  const sys = (text, time, bad = false) => { turn = null; out.push(h('div', { class: `sys ${bad ? 'bad' : ''}` }, h('span', { class: 'txt' }, text), h('span', { class: 'time' }, clock(time)))); };
  for (const ev of events) {
    const p = ev.payload || {};
    if (ev.kind === 'activity') {
      if (p.source === 'claude-hook' || p.source === 'structured') {
        const name = p.event;
        if (name === 'UserPromptSubmit') newTurn(p.prompt || '（空）', ev.created_at);
        else if (name === 'PreToolUse') {
          const el = step('', '›', [h('code', {}, p.tool_name || '工具'), p.summary ? ` ${p.summary}` : '']);
          ensureTurn(ev.created_at).append(el);
          if (p.tool_use_id) tools.set(p.tool_use_id, el);
        } else if (name === 'PostToolUse' || name === 'PostToolUseFailure') {
          const el = p.tool_use_id && tools.get(p.tool_use_id);
          if (el) {
            if (name === 'PostToolUse') el.querySelector('.txt').append(h('span', { class: 'ok', title: '完成' }, '✓'));
            else { el.classList.add('fail'); el.querySelector('.txt').append(p.declined ? ' — 已拒绝' : ` — 失败${p.error ? `：${p.error}` : ''}`); }
          } else if (name === 'PostToolUseFailure') ensureTurn(ev.created_at).append(step('fail', '×', `${p.tool_name || '工具'} 失败${p.error ? `：${p.error}` : ''}`));
        } else if (name === 'PermissionRequest' || (name === 'Notification' && p.notification_type === 'permission_prompt')) {
          ensureTurn(ev.created_at).append(step('perm', '!', `请求权限：${p.tool_name ? `${p.tool_name} ` : ''}${p.summary || p.message || ''}`));
        } else if (name === 'Notification') {
          if (p.message) ensureTurn(ev.created_at).append(step('', '·', p.message));
        } else if (name === 'Stop') {
          if (turn) turn.append(step('', '■', '本轮结束'));
        } else if (name === 'SessionStart') {
          sys(p.start_source === 'resume' ? '原生会话已恢复' : p.start_source === 'clear' ? '已开始新的原生对话（/clear）' : '原生会话已就绪', ev.created_at);
        } else if (name === 'SessionEnd') sys('原生会话已结束', ev.created_at);
        else if (name === 'PermissionDecision') ensureTurn(ev.created_at).append(step(p.decision === 'deny' ? 'fail' : '', p.decision === 'deny' ? '×' : '✓', p.decision === 'deny' ? '你拒绝了这个请求' : '你允许了这个请求'));
      } else if (p.source === 'codex-notify') {
        newTurn(p.prompt || '（终端中的输入）', ev.created_at);
        if (p.message) turn.append(step('', '■', `本轮完成：${p.message}`));
        turn = null;
      } else if (p.source === 'terminal') {
        const perm = /permission|approv|权限|批准/i.test(p.message || '');
        ensureTurn(ev.created_at).append(step(perm ? 'perm' : '', perm ? '!' : '·', p.message || '终端通知'));
      }
    } else {
      const label = {
        session_created: null,
        run_started: `${p.kind === 'resume' ? '已用原生方式恢复' : '已启动'}${p.transport === 'structured' ? '（对话连接）' : '（终端）'}${p.handoff_prompt ? '，并发送交接说明' : ''}`,
        released: `已结束连接（${p.reason === 'view' ? '切换视图' : '在官方桌面客户端中继续'}）`,
        view_changed: `视图切换为${p.to === 'conversation' ? '对话' : '终端'}`,
        settings_chosen: `选择了${settingsLabel(p)}`,
        desktop_open: p.via === '/desktop' ? '通过终端里的 /desktop 移到了 Claude Desktop' : `已请求在 ${p.app || '桌面客户端'} 中打开（${{ acknowledged: '已确认', requested: '系统已接受请求', not_acknowledged: '没有确认', failed: '失败' }[p.status] || p.status}）`,
        desktop_returned: '已回到 RepoBridge 继续',
        turn_interrupt_requested: '已请求停止这一轮',
        run_ended: `会话${{ exited: '已退出', stopped: '已停止', failed: '失败', interrupted: '被中断' }[p.status] || p.status}${p.exit_code !== null && p.exit_code !== undefined && p.status !== 'stopped' ? `（退出码 ${p.exit_code}）` : ''}${p.failure ? `：${p.failure}` : ''}`,
        stop_requested: '已请求停止',
        writer_refused: '启动被拒绝：这个文件夹已有运行中的会话',
        native_session_observed: '已识别原生会话',
        native_session_changed: '原生会话已切换（例如 /clear 或 /resume）',
        handoff_out: `已交接到新的 ${HARNESS[p.target] ? HARNESS[p.target].label : ''} 会话`,
        handoff_in: '由交接创建',
        run_interrupted: 'RepoBridge 关闭时会话被中断',
        exit_unconfirmed: '无法确认进程已全部退出',
        orphan_stopped: '已结束上次运行遗留的进程',
        run_failed: `启动失败：${p.failure || ''}`,
      }[ev.kind];
      if (label) sys(label, ev.created_at, ['run_failed', 'writer_refused', 'exit_unconfirmed'].includes(ev.kind) || (ev.kind === 'run_ended' && p.status === 'failed'));
    }
  }
  return out;
}

function detailsPane(s) {
  const p = findProject(s.project_id);
  const d = S.details.get(s.session_id);
  if (!d) loadDetails(s.session_id);
  const label = HARNESS[s.harness].label;
  const from = s.handoff_from && findSession(s.handoff_from);
  const outs = p ? p.handoffs.filter((x) => x.from_session_id === s.session_id) : [];
  const recovery = s.active ? (s.attached ? '正在运行。' : '记录为运行中，但不在当前窗口的终端里。')
    : wasUnlinked(s) ? RESUME_REASON_TEXT.unlinked
      : s.native_link && !s.can_resume ? (RESUME_REASON_TEXT[s.native_link.resume_reason] || '这个原生会话当前不能恢复。')
        : s.can_resume ? `可以恢复：会用 ${label} 的原生恢复回到同一会话${linkHold(s) ? '（先确认外部已经结束）' : ''}。`
      : s.can_start_fresh ? (s.status === 'new' ? '还没有启动。' : '还没有原生对话，可以重新启动。')
        : s.native_session_id ? '原生会话存在，但当前无法恢复。' : `还没有识别到原生会话（${label} 在第一轮结束后才报告）。`;
  const sections = [
    h('div', { class: 'sect' }, h('h3', {}, '会话'), h('div', { class: 'kv' },
      h('div', { class: 'k' }, 'Harness'), h('div', { class: 'v' }, label),
      h('div', { class: 'k' }, '项目'), h('div', { class: 'v' }, p ? p.name : '—'),
      h('div', { class: 'k' }, '文件夹'), h('div', { class: 'v selectable' }, homeify(s.workdir)),
      h('div', { class: 'k' }, '分支'), h('div', { class: 'v' }, (p && p.branch) || '—'),
      h('div', { class: 'k' }, '视图'), h('div', { class: 'v' }, s.view_mode === 'conversation' ? '对话' : '终端'),
      h('div', { class: 'k' }, '连接方式'), h('div', { class: 'v' }, transportLabel(s)),
      h('div', { class: 'k' }, '创建于'), h('div', { class: 'v' }, clock(s.created_at)))),
    h('div', { class: 'sect' }, h('h3', {}, '恢复'), h('div', { style: 'font-size:12.5px' }, recovery),
      s.native_session_id && s.can_resume ? [
        h('div', { class: 'code-line selectable' }, h('span', { title: HARNESS[s.harness].resume(s.native_session_id) }, HARNESS[s.harness].resume(s.native_session_id)),
          h('button', { class: 'icon-btn small', type: 'button', title: '复制命令', 'aria-label': '复制恢复命令', onclick: () => copyText(resumeCommand(s), '已复制恢复命令') }, icon('copy'))),
        h('div', { class: 'hint', style: 'margin-top:6px' }, '也可以在普通终端里，于项目文件夹中运行这条原生命令。')] : null),
  ];
  const link = linkSection(s);
  if (link) sections.push(link);
  sections.push(settingsSection(s));
  sections.push(desktopSection(s));
  if (from || outs.length) {
    sections.push(h('div', { class: 'sect' }, h('h3', {}, '交接'),
      from ? h('button', { class: 'list-btn', type: 'button', onclick: () => select({ type: 'session', id: from.session_id }) }, icon('handoff'), h('span', { class: 'name' }, `来自「${from.title}」`), h('span', { class: 'meta' }, HARNESS[from.harness].short)) : null,
      outs.map((x) => {
        const to = findSession(x.to_session_id);
        return h('button', { class: 'list-btn', type: 'button', onclick: () => select({ type: 'session', id: x.to_session_id }) }, icon('handoff'), h('span', { class: 'name' }, `交接到「${to ? to.title : x.to_session_id}」`), h('span', { class: 'meta' }, clock(x.created_at)));
      }),
      h('div', { class: 'hint', style: 'margin-top:6px' }, '交接会新建原生会话，新会话不继承原会话的原生上下文。')));
  }
  const runs = d ? d.runs.slice().reverse() : [];
  sections.push(h('div', { class: 'sect' }, h('h3', {}, '运行记录'),
    !d ? h('div', { class: 'hint' }, '正在读取…') : !runs.length ? h('div', { class: 'hint' }, '还没有运行。') :
      h('div', { class: 'runs' }, runs.map((r) => h('div', { class: 'run' },
        h('span', { class: 'n' }, `#${r.seq}`),
        h('span', { class: 'what' }, `${r.kind === 'resume' ? '恢复' : '启动'} · ${r.transport === 'structured' ? '对话' : '终端'} · ${['running', 'starting'].includes(r.status) ? '运行中' : statusOf({ ...s, active: false, archived: false, external: null, status: r.status }).label}${r.exit_code !== null && r.status === 'failed' ? `（退出码 ${r.exit_code}）` : ''}`,
          r.failure ? h('span', { class: 'why' }, r.failure) : null),
        h('span', { class: 'time' }, clock(r.started_at))))),
    d && runs[0] && runs[0].output_tail && runs[0].status === 'failed' ? [h('div', { class: 'hint', style: 'margin-top:10px' }, '最后的输出'), h('pre', { class: 'tail selectable' }, runs[0].output_tail)] : null));
  sections.push(h('div', { class: 'sect' }, h('details', { class: 'tech' }, h('summary', {}, icon('chevron'), '技术详情'),
    h('div', { class: 'kv selectable', style: 'margin-top:8px' },
      h('div', { class: 'k' }, '会话 ID'), h('div', { class: 'v mono' }, s.session_id),
      h('div', { class: 'k' }, '原生会话 ID'), h('div', { class: 'v mono' }, s.native_session_id || '未知'),
      h('div', { class: 'k' }, 'ID 来源'), h('div', { class: 'v' }, { pending: '等待 CLI 报告', preassigned: '启动时指定，等待确认', confirmed: '启动时指定，CLI 已确认', observed: 'CLI 报告', linked: '添加已有会话时关联' }[s.native_binding] || s.native_binding),
      h('div', { class: 'k' }, '观察到的轮次'), h('div', { class: 'v' }, String(s.turns_observed), s.native_link ? h('span', { class: 'hint' }, ' · 只统计在 RepoBridge 中看到的轮次') : null),
      runs[0] ? [
        h('div', { class: 'k' }, '最近的命令'), h('div', { class: 'v mono' }, (runs[0].argv || []).map((a) => (a.length > 120 ? `${a.slice(0, 117)}…` : a)).join(' ')),
        h('div', { class: 'k' }, '未传递变量'), h('div', { class: 'v' }, runs[0].stripped_env && runs[0].stripped_env.length ? runs[0].stripped_env.join(', ') : '无'),
        h('div', { class: 'k' }, '运行 ID'), h('div', { class: 'v mono' }, runs[0].run_id)] : null,
      d && d.structured_info ? Object.entries(d.structured_info).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => [
        h('div', { class: 'k' }, { model: '模型', permissionMode: '权限模式', apiKeySource: '认证来源', approval_policy: '审批策略', sandbox: '沙箱', thread_source: '线程来源', cli_version: 'CLI 版本', version: 'CLI 版本', session_id: '原生会话', cwd: '目录' }[k] || k),
        h('div', { class: 'v mono' }, typeof v === 'string' ? v : JSON.stringify(v))]) : null))));
  return [h('div', { class: 'pane-scroll' }, sections)];
}

function settingsSection(s) {
  const st = settingsOf(s);
  const rows = [['model', modelNow(s).label], ['effort', effortNow(s).label], ['mode', modeNow(s).label]];
  const stateText = (name) => fieldStateText(s, name);
  return h('div', { class: 'sect' }, h('h3', {}, '模型与权限'), h('div', { class: 'kv' },
    rows.map(([name, value]) => [h('div', { class: 'k' }, FIELD_NAME[name]), h('div', { class: 'v', title: fieldTitle(s, name, value) }, value, h('span', { class: 'hint' }, ` · ${stateText(name)}`))]),
    st.turn_model ? [h('div', { class: 'k' }, '上一轮'), h('div', { class: 'v mono' }, st.turn_model)] : null,
    st.actual.reviewer ? [h('div', { class: 'k' }, '审批人'), h('div', { class: 'v' }, (REVIEWER[st.actual.reviewer] || st.actual.reviewer).trim(), h('span', { class: 'hint' }, ' · Codex 设置'))] : null),
  h('div', { class: 'hint', style: 'margin-top:6px' }, s.view_mode === 'terminal'
    ? '终端视图里，单独选过的设置会作为启动参数传给 CLI；之后在终端里用 /model 等命令改动的，以终端显示为准。'
    : '在对话输入框下方选择。只有 CLI 回报后才显示为“已确认生效”。'));
}

function transportLabel(s) {
  const t = s.transport || (s.view_mode === 'conversation' ? 'structured' : 'pty');
  if (t === 'pty') return `原生终端（${HARNESS[s.harness].label} 交互界面）`;
  return s.harness === 'codex' ? 'Codex app-server（官方 JSON-RPC）' : 'Claude Code 流式协议（stream-json）';
}

function desktopSection(s) {
  const d = s.desktop || {};
  const label = HARNESS[s.harness].label;
  const rows = [
    h('div', { class: 'k' }, '客户端'), h('div', { class: 'v' }, d.app_found ? `${d.app}${d.app_version ? `（${d.app_version}）` : ''}` : `${d.app}（未找到）`),
    h('div', { class: 'k' }, '状态'), h('div', { class: 'v' }, linkHold(s) ? '外部使用未确认结束' : s.external ? `已在 ${s.external.app} 中打开（${clock(s.external.opened_at)}）` : d.available ? '可以打开' : (d.reason || '不可用')),
  ];
  const ref = d.command || d.link;
  return h('div', { class: 'sect' }, h('h3', {}, '官方桌面客户端'), h('div', { class: 'kv' }, rows),
    h('div', { style: 'display:flex;gap:8px;margin-top:10px;flex-wrap:wrap' },
      linkHold(s) ? h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => confirmOutsideEnded(s, e.currentTarget) }, '外部已结束…')
        : s.external ? h('button', { class: 'btn btn-small', type: 'button', onclick: () => desktopReturn(s) }, '回到 RepoBridge 继续')
        : h('button', { class: 'btn btn-small', type: 'button', disabled: !d.available, title: d.reason || null, onclick: (e) => openInDesktop(s, e.currentTarget) }, icon('external'), `在 ${d.app} 中打开`)),
    ref ? h('div', { class: 'code-line selectable', style: 'margin-top:8px' }, h('span', { title: ref }, ref),
      h('button', { class: 'icon-btn small', type: 'button', title: '复制', 'aria-label': '复制', onclick: () => copyText(d.command ? `cd ${shellQuote(s.workdir)} && ${d.command}` : d.link, '已复制') }, icon('copy'))) : null,
    h('div', { class: 'hint', style: 'margin-top:6px' }, s.harness === 'codex'
      ? '使用 Codex 官方的“已有对话”链接打开。系统接受请求不代表已经看到正确的对话，请在 Codex 中确认。'
      : `由 ${label} 自己执行 claude --desktop --resume，并确认打开同一个会话；Claude Desktop 继续的是同一个会话，回到这里后可用原生恢复接着做。`));
}

function shellQuote(s) { return /^[\w@%+=:,./-]+$/.test(s) ? s : `'${s.replace(/'/g, `'\\''`)}'`; }

// ---------------------------------------------------------------- menus, popovers, dialogs

const layers = [];
function layerOpen() { return layers.length > 0; }
function pushLayer(el, onClose) {
  const entry = { el, onClose, prevFocus: document.activeElement };
  layers.push(entry);
  $('#layer').append(el);
  return () => closeLayer(entry);
}
function closeLayer(entry) {
  const i = layers.indexOf(entry);
  if (i < 0) return;
  layers.splice(i, 1);
  entry.el.remove();
  if (entry.onClose) entry.onClose();
  if (entry.prevFocus && document.body.contains(entry.prevFocus) && entry.prevFocus !== document.body) entry.prevFocus.focus();
  else { const s = selectedSession(); if (s) focusTerminal(s.session_id); }
}
function closeTop() { if (layers.length) closeLayer(layers[layers.length - 1]); }
document.addEventListener('mousedown', (e) => {
  const top = layers[layers.length - 1];
  if (top && (top.el.classList.contains('menu') || top.el.classList.contains('popover')) && !top.el.contains(e.target)) closeLayer(top);
}, true);

function place(el, anchor) {
  const isEl = anchor instanceof Element;
  const r = isEl ? anchor.getBoundingClientRect() : null;
  let x = isEl ? r.left : anchor.x;
  let y = isEl ? r.bottom + 4 : anchor.y;
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  // Measured right away (the element is already in the layer): no frame at the wrong place,
  // and no dependence on animation frames, which a covered window may not deliver.
  const w = el.offsetWidth;
  const hgt = el.offsetHeight;
  if (isEl && r.left + w > window.innerWidth - 8) x = r.right - w;
  if (y + hgt > window.innerHeight - 8) y = isEl ? r.top - hgt - 4 : y - hgt;
  el.style.left = `${Math.max(8, Math.min(x, window.innerWidth - w - 8))}px`;
  el.style.top = `${Math.max(8, Math.min(y, window.innerHeight - hgt - 8))}px`;
}

function menu(anchor, items) {
  const el = h('div', { class: 'menu', role: 'menu' });
  let close = () => {};
  const clean = items.filter(Boolean).filter((x, i, arr) => !(x === '-' && (i === 0 || arr[i - 1] === '-' || i === arr.length - 1)));
  for (const it of clean) {
    if (it === '-') { el.append(h('div', { class: 'menu-sep' })); continue; }
    if (it.head) { el.append(h('div', { class: 'menu-head' }, it.head)); continue; }
    el.append(h('button', {
      class: `menu-item ${it.danger ? 'danger' : ''}`, role: 'menuitem', type: 'button', disabled: it.disabled,
      title: it.title || null, onclick: () => { close(); it.action(); },
    }, it.icon ? icon(it.icon) : h('span', { style: 'width:16px' }), h('span', { class: 'grow' }, it.label), it.note ? h('span', { class: 'note' }, it.note) : null));
  }
  el.addEventListener('keydown', (e) => {
    const btns = [...el.querySelectorAll('.menu-item:not(:disabled)')];
    const i = btns.indexOf(document.activeElement);
    if (e.key === 'ArrowDown') { e.preventDefault(); (btns[i + 1] || btns[0]).focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); (btns[i - 1] || btns[btns.length - 1]).focus(); }
  });
  close = pushLayer(el);
  place(el, anchor);
  const first = el.querySelector('.menu-item:not(:disabled)');
  if (first) first.focus();
}

function confirmPopover(anchor, { title, text, confirm, danger, onConfirm }) {
  let close = () => {};
  const ok = h('button', { class: `btn ${danger ? 'btn-danger' : 'btn-primary'}`, type: 'button', onclick: () => { close(); onConfirm(); } }, confirm);
  const el = h('div', { class: 'popover', role: 'alertdialog', 'aria-label': title },
    h('h4', {}, title), h('p', {}, text),
    h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: () => close() }, '取消'), ok));
  close = pushLayer(el);
  place(el, anchor instanceof Element ? anchor : $('#toolbar'));
  ok.focus();
}

const FOCUSABLE = 'input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled):not([hidden]), [tabindex="0"]';

function dialog(content, { wide = false, cls = '', onClose } = {}) {
  const box = h('div', { class: `dialog ${wide ? 'wide' : ''} ${cls}`, role: 'dialog', 'aria-modal': 'true', tabindex: '-1' }, content);
  const wrap = h('div', { class: 'dialog-wrap' }, box);
  let close = () => {};
  wrap.addEventListener('mousedown', (e) => { if (e.target === wrap) close(); });
  // Keep keyboard focus inside the dialog: nothing typed here may reach the terminal behind it.
  wrap.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const items = [...box.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
    if (!items.length) { e.preventDefault(); box.focus(); return; }
    const i = items.indexOf(document.activeElement);
    const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i === items.length - 1 ? 0 : i + 1);
    e.preventDefault();
    items[next].focus();
  });
  close = pushLayer(wrap, onClose);
  const s = selectedSession();
  if (s && S.terms.get(s.session_id)) S.terms.get(s.session_id).term.blur();
  box.focus();
  setTimeout(() => { if (box.contains(document.activeElement) && document.activeElement !== box) return; const f = box.querySelector('input, textarea, select') || box.querySelector('.btn-primary') || box.querySelector(FOCUSABLE); if (f) f.focus(); }, 0);
  return close;
}

function sessionMenu(s, anchor) {
  const label = HARNESS[s.harness].label;
  const p = findProject(s.project_id);
  const anchorEl = anchor instanceof Element ? anchor : $('#toolbar');
  menu(anchor, [
    { icon: 'pencil', label: '重命名…', action: () => { select({ type: 'session', id: s.session_id }, { focus: false }); setTimeout(() => beginRename(findSession(s.session_id)), 50); } },
    wasUnlinked(s) ? null : { icon: 'handoff', label: '交接到新会话…', action: () => openHandoff(s) },
    { icon: s.view_mode === 'conversation' ? 'terminal' : 'chat', label: s.view_mode === 'conversation' ? '切换到终端视图' : '切换到对话视图', disabled: s.archived || (s.active && !s.attached), action: () => switchView(s, s.view_mode === 'conversation' ? 'terminal' : 'conversation', anchorEl) },
    s.external && !linkHold(s) ? { icon: 'resume', label: '回到 RepoBridge 继续', action: () => desktopReturn(s) }
      : { icon: 'external', label: `在 ${(s.desktop && s.desktop.app) || '桌面客户端'} 中打开…`, disabled: !(s.desktop && s.desktop.available), note: s.desktop && !s.desktop.available ? '不可用' : null, title: s.desktop && s.desktop.reason, action: () => openInDesktop(s, anchorEl) },
    '-',
    s.native_session_id && s.can_resume ? { icon: 'copy', label: '复制原生恢复命令', action: () => copyText(resumeCommand(s), '已复制恢复命令') } : null,
    p ? { icon: 'folder', label: '在 Finder 中显示项目', action: () => revealProject(p) } : null,
    { icon: 'info', label: '会话详情', action: () => { select({ type: 'session', id: s.session_id }, { focus: false }); setPref('inspector_open', true); setPref('inspector_tab', 'details'); loadDetails(s.session_id); render(); } },
    '-',
    linkHold(s) && !s.active ? { icon: 'check', label: '外部已结束…', action: () => confirmOutsideEnded(s, anchorEl) } : null,
    s.active && s.attached ? { icon: 'stop', label: s.transport === 'structured' ? `断开 ${label}` : `停止 ${label}`, action: () => stopSession(s, anchorEl) } : null,
    isLinked(s) ? { icon: 'link', label: '移除关联…', disabled: s.active, note: s.active ? '先断开' : null, title: '只从 RepoBridge 移除；原生历史保留', action: () => unlinkSession(s, anchorEl) } : null,
    wasUnlinked(s) ? { icon: 'link', label: '重新添加…', action: () => reAddSession(s) }
      : s.archived ? { icon: 'unarchive', label: '取消归档', action: () => unarchiveSession(s) }
        : { icon: 'archive', label: '归档…', disabled: s.active, note: s.active ? '先停止' : null, action: () => archiveSession(s, anchorEl) },
  ]);
}

function projectMenu(p, anchor) {
  const anchorEl = anchor instanceof Element ? anchor : $('#tree');
  menu(anchor, [
    { icon: 'plus', label: '新建 Claude Code 会话', disabled: !harnessOk('claude-code'), action: () => openNewSession(p.project_id, 'claude-code') },
    { icon: 'plus', label: '新建 Codex 会话', disabled: !harnessOk('codex'), action: () => openNewSession(p.project_id, 'codex') },
    { icon: 'history', label: '添加已有会话…', action: () => openAddExisting({ projectId: p.project_id }) },
    '-',
    { icon: 'folder', label: '在 Finder 中显示', action: () => revealProject(p) },
    { icon: 'copy', label: '复制路径', action: () => copyText(p.root_path, '已复制路径') },
    '-',
    { icon: 'close', label: '从 RepoBridge 移除…', danger: true, action: () => removeProject(p, anchorEl) },
  ]);
}

function newSessionMenu(p, anchor) {
  menu(anchor, [
    { head: p.name },
    ...['claude-code', 'codex'].map((k) => ({ icon: 'plus', label: `新建 ${HARNESS[k].label} 会话`, disabled: !harnessOk(k), note: harnessOk(k) ? null : '未找到', action: () => openNewSession(p.project_id, k) })),
    '-',
    { icon: 'history', label: '添加已有会话…', title: '关联以前在 Claude Code 或 Codex 中创建的会话', action: () => openAddExisting({ projectId: p.project_id }) },
  ]);
}

function openNewSession(projectId, harness) {
  const projects = S.state.projects;
  if (!projects.length) { openAddProject(); return; }
  let pid = projectId || (selectedProject() || projects[0]).project_id;
  let kind = harness || S.prefs.last_harness;
  if (!harnessOk(kind) && harnessOk(kind === 'codex' ? 'claude-code' : 'codex')) kind = kind === 'codex' ? 'claude-code' : 'codex';
  const projectSelect = h('select', { class: 'select' }, projects.map((p) => h('option', { value: p.project_id }, p.name)));
  projectSelect.value = pid;
  const title = h('input', { class: 'input', placeholder: '可选，例如“修复登录跳转”', maxlength: '120' });
  const choice = h('div', { class: 'choice', role: 'radiogroup' });
  let view = S.prefs.default_view || 'terminal';
  const viewChoice = h('div', { class: 'choice', role: 'radiogroup' });
  const busyBox = h('div');
  const create = h('button', { class: 'btn btn-primary', type: 'button' }, '创建并启动');
  const alt = h('button', { class: 'btn', type: 'button' });
  let close = () => {};
  const draw = () => {
    choice.replaceChildren(...['claude-code', 'codex'].map((k) => {
      const info = harnessInfo(k);
      return h('button', { type: 'button', role: 'radio', 'aria-pressed': String(k === kind), 'aria-checked': String(k === kind), disabled: !info || !info.available, onclick: () => { kind = k; draw(); } },
        h('span', { class: 't' }, h('span', { class: `dot ${k}` }), HARNESS[k].label),
        h('span', { class: 'd' }, info && info.available ? (info.version || '已找到') : '未找到'));
    }));
    viewChoice.replaceChildren(...[['conversation', '对话', '消息、工具调用和权限请求以卡片显示'], ['terminal', '终端', '原生终端界面，与在终端中运行一致']].map(([v, l, d]) => h('button', {
      type: 'button', role: 'radio', 'aria-pressed': String(v === view), 'aria-checked': String(v === view), onclick: () => { view = v; draw(); },
    }, h('span', { class: 't' }, icon(v === 'conversation' ? 'chat' : 'terminal'), l), h('span', { class: 'd' }, d))));
    const busy = busySessionIn(findProject(pid));
    busyBox.replaceChildren();
    if (busy) {
      busyBox.append(h('div', { class: 'callout warn' }, icon('warning'), h('div', {}, `「${busy.title}」正在这个项目中运行。同一文件夹同时只能有一个会话写入，新会话会先创建，等你停止它之后再启动。`)));
      create.textContent = '创建（稍后启动）';
      alt.hidden = false;
      alt.textContent = '切换到运行中的会话';
      alt.onclick = () => { close(); select({ type: 'session', id: busy.session_id }); };
    } else {
      create.textContent = '创建并启动';
      alt.hidden = true;
    }
    create.disabled = !harnessOk(kind);
  };
  projectSelect.addEventListener('change', () => { pid = projectSelect.value; draw(); });
  create.addEventListener('click', () => guarded('new-session', async () => {
    const start = !busySessionIn(findProject(pid));
    const s = await api('POST', '/api/sessions', { project_id: pid, harness: kind, title: title.value.trim() || null, start, view_mode: view });
    setPref('last_harness', kind);
    setPref('default_view', view);
    close();
    select({ type: 'session', id: s.session_id });
  }, create));
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) create.click(); });
  close = dialog([
    h('h2', {}, '新建会话'),
    h('p', { class: 'sub' }, '每个会话固定使用一种 harness，在项目文件夹中运行它的原生 CLI。界面可以随时在“对话”和“终端”之间切换。'),
    h('div', { class: 'field' }, h('label', {}, '项目'), projectSelect),
    h('div', { class: 'field' }, h('div', { class: 'label' }, 'Harness'), choice),
    h('div', { class: 'field' }, h('div', { class: 'label' }, '界面'), viewChoice),
    h('div', { class: 'field' }, h('label', {}, '标题'), title),
    busyBox,
    h('div', { class: 'actions' }, h('span', { class: 'left' }, alt), h('button', { class: 'btn', type: 'button', onclick: () => close() }, '取消'), create),
  ]);
  draw();
  setTimeout(() => title.focus(), 30);
}

function openAddProject() {
  const path = h('input', { class: 'input', placeholder: '/Users/you/code/my-project', spellcheck: 'false', autocomplete: 'off' });
  const name = h('input', { class: 'input', placeholder: '默认使用文件夹名' });
  const err = h('div', { class: 'err', hidden: true });
  const add = h('button', { class: 'btn btn-primary', type: 'button' }, '添加');
  let close = () => {};
  const pick = hasNative('pick_folder') ? h('button', { class: 'btn', type: 'button', onclick: (e) => guarded('pick-folder', async () => {
    const p = await api('POST', '/api/native/pick-folder', {});
    if (p) { path.value = p; err.hidden = true; }
  }, e.currentTarget) }, '选择…') : null;
  const submit = () => guarded('add-project', async () => {
    err.hidden = true;
    try {
      const p = await api('POST', '/api/projects', { path: path.value, name: name.value.trim() || null });
      close();
      toast(p.created ? `已添加「${p.name}」` : `「${p.name}」已在列表中`);
      select({ type: 'project', id: p.project_id }, { focus: false });
    } catch (e) { err.textContent = e.message; err.hidden = false; path.focus(); }
  }, add);
  add.addEventListener('click', submit);
  path.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.isComposing) submit(); });
  close = dialog([
    h('h2', {}, '添加项目'),
    h('p', { class: 'sub' }, '选择一个本地文件夹；Git 仓库请选择仓库的顶层文件夹。RepoBridge 不会修改其中的文件。'),
    h('div', { class: 'field' }, h('label', {}, '文件夹'), h('div', { class: 'row-input' }, path, pick)),
    err,
    h('div', { class: 'field' }, h('label', {}, '名称（可选）'), name),
    h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: () => close() }, '取消'), add),
  ]);
  setTimeout(() => path.focus(), 30);
}

function openHandoff(source) {
  let target = source.harness === 'claude-code' ? 'codex' : 'claude-code';
  const progress = h('textarea', { class: 'textarea', rows: '3', placeholder: '例如：登录接口已完成；test_auth.py 还有 2 个失败；下一步修复令牌过期判断。', style: 'font-family:var(--font);font-size:13px' });
  const note = h('textarea', { class: 'textarea', rows: '12', spellcheck: 'false', 'aria-label': '交接说明' });
  const send = h('input', { type: 'checkbox' });
  send.checked = true;
  const choice = h('div', { class: 'choice' });
  const warnBox = h('div');
  const create = h('button', { class: 'btn btn-primary', type: 'button' }, '创建新会话');
  let close = () => {};
  const noteWrap = h('div', { hidden: true }, note);
  const noteToggle = h('button', { class: 'disclose', type: 'button' }, icon('chevron'), '查看和编辑交接说明');
  noteToggle.addEventListener('click', () => { noteWrap.hidden = !noteWrap.hidden; noteToggle.classList.toggle('open', !noteWrap.hidden); });
  const draw = () => {
    choice.replaceChildren(...['claude-code', 'codex'].map((k) => {
      const info = harnessInfo(k);
      return h('button', { type: 'button', role: 'radio', 'aria-pressed': String(k === target), 'aria-checked': String(k === target), disabled: !info || !info.available, onclick: () => { target = k; draw(); draft(); } },
        h('span', { class: 't' }, h('span', { class: `dot ${k}` }), HARNESS[k].label),
        h('span', { class: 'd' }, k === source.harness ? '同一 harness，全新的上下文' : '换一个 harness 继续'));
    }));
    const live = findSession(source.session_id);
    warnBox.replaceChildren();
    if (live && live.active) {
      warnBox.append(h('div', { class: 'callout warn' }, icon('warning'), h('div', {}, `「${live.title}」正在运行。同一文件夹同时只能有一个会话写入，继续时会先停止它（原生会话会保存）。`)));
      create.textContent = '停止原会话并创建';
    } else create.textContent = '创建新会话';
    create.disabled = !harnessOk(target);
  };
  let draftSeq = 0;
  const draft = async () => {
    const seq = ++draftSeq;
    try {
      const d = await api('POST', `/api/sessions/${source.session_id}/handoff/draft`, { target, progress: progress.value });
      if (seq === draftSeq) note.value = d.note;
    } catch (e) { fail(e); }
  };
  let progressTimer = null;
  progress.addEventListener('input', () => { clearTimeout(progressTimer); progressTimer = setTimeout(draft, 500); });
  create.addEventListener('click', () => guarded('handoff', async () => {
    const live = findSession(source.session_id);
    if (live && live.active) {
      await api('POST', `/api/sessions/${source.session_id}/stop`, {});
      const t0 = Date.now();
      while (Date.now() - t0 < 15000) {
        await new Promise((r) => setTimeout(r, 300));
        const now = findSession(source.session_id);
        if (now && !now.active) break;
      }
      if (findSession(source.session_id).active) throw new ApiError({ message: '原会话还没有停止，请稍后再试' });
      if (noteWrap.hidden) await draft();
    }
    const r = await api('POST', `/api/sessions/${source.session_id}/handoff`, { target, note: note.value, send_as_prompt: send.checked });
    close();
    select({ type: 'session', id: r.session.session_id });
    toast(`已在同一项目中创建 ${HARNESS[target].label} 会话`);
  }, create));
  close = dialog([
    h('h2', {}, '交接到新会话'),
    h('p', { class: 'sub' }, `从「${source.title}」继续这项工作。会在同一项目中新建一个会话；它读不到原会话的原生上下文，会先阅读代码和这份交接说明。原会话保留，之后仍可恢复查看。`),
    warnBox,
    h('div', { class: 'field' }, h('div', { class: 'label' }, '新会话使用'), choice),
    h('div', { class: 'field' }, h('label', {}, '进度与下一步（写进交接说明）'), progress),
    h('div', { class: 'field' }, noteToggle, noteWrap),
    h('label', { class: 'check' }, send, h('span', {}, '启动后把交接说明作为第一条消息发给新会话（会产生一次模型调用）。不勾选则只启动，你可以自己粘贴。')),
    h('div', { class: 'actions' }, h('button', { class: 'btn', type: 'button', onclick: () => close() }, '取消'), create),
  ], { wide: true });
  const ticker = setInterval(() => { if (!document.body.contains(create)) clearInterval(ticker); else draw(); }, 1000);
  draw();
  draft();
  setTimeout(() => progress.focus(), 30);
}

function openSettings() {
  const body = h('div');
  let close = () => {};
  const draw = () => {
    const seg = (key, options) => h('div', { class: 'seg-inline', role: 'radiogroup' }, options.map(([v, l]) => h('button', {
      type: 'button', 'aria-pressed': String(S.prefs[key] === v), onclick: () => { setPref(key, v); applyTheme(); render(); draw(); },
    }, l)));
    body.replaceChildren(
      h('div', { class: 'settings-row' }, h('span', {}, '外观'), seg('appearance', [['system', '跟随系统'], ['light', '浅色'], ['dark', '深色']])),
      h('div', { class: 'settings-row' }, h('span', {}, '终端配色'), seg('terminal_theme', [['auto', '跟随外观'], ['dark', '始终深色']])),
      h('div', { class: 'settings-row' }, h('span', {}, '终端字号'), seg('terminal_font_size', [[12, '12'], [13, '13'], [14, '14'], [15, '15'], [16, '16']])),
      h('div', { class: 'settings-row' }, h('span', {}, '显示已归档的会话'), seg('show_archived', [[false, '隐藏'], [true, '显示']])),
      h('div', { class: 'settings-row', style: 'align-items:flex-start' }, h('span', {}, '命令行工具'),
        h('div', { style: 'flex:1;max-width:340px' }, cliList(),
          h('div', { style: 'margin-top:8px;display:flex;gap:8px;align-items:center' },
            h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => guarded('refresh-cli', async () => { await api('POST', '/api/harnesses/refresh', {}); setTimeout(draw, 300); }, e.currentTarget) }, '重新检测'),
            h('span', { class: 'hint' }, '只运行 --version，不启动会话。')))),
      h('div', { class: 'settings-row' }, h('span', {}, '键盘快捷键'), h('button', { class: 'btn btn-small', type: 'button', onclick: () => { close(); openShortcuts(); } }, icon('keyboard'), '查看')),
      h('p', { class: 'hint', style: 'margin:12px 0 0' }, 'RepoBridge 不读取或保存任何登录令牌。启动会话时不会传递可能把订阅切换为 API 计费的环境变量。'));
  };
  draw();
  close = dialog([h('h2', {}, '设置'), h('div', { style: 'margin-top:10px' }, body),
    h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => close() }, '完成'))]);
}

function openShortcuts() {
  let close = () => {};
  close = dialog([h('h2', {}, '键盘快捷键'),
    h('div', { class: 'shortcuts', style: 'margin-top:12px' }, KEY_LABELS.flatMap(([a, k]) => [h('span', {}, a), h('span', { class: 'k' }, h('kbd', {}, k))])),
    h('p', { class: 'hint', style: 'margin:14px 0 0' }, '终端获得焦点时，其他按键（包括 Esc 和 ⌃C）都直接交给原生 CLI。'),
    h('div', { class: 'actions' }, h('button', { class: 'btn btn-primary', type: 'button', onclick: () => close() }, '好'))]);
}

// ---------------------------------------------------------------- toasts & errors

function toast(message, kind = 'info', actions = []) {
  const el = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status' },
    kind === 'error' ? icon('warning') : icon('check'),
    h('div', { class: 'msg' }, message),
    actions.map(([label, fn]) => h('button', { class: 'btn btn-small', type: 'button', onclick: () => { el.remove(); fn(); } }, label)));
  $('#toasts').append(el);
  setTimeout(() => el.remove(), actions.length ? 9000 : kind === 'error' ? 7000 : 2600);
}

function fail(err) {
  const actions = [];
  if (err && err.details && err.details.busy_session_id) actions.push(['切换到该会话', () => select({ type: 'session', id: err.details.busy_session_id })]);
  toast((err && err.message) || String(err), 'error', actions);
}

// ---------------------------------------------------------------- keyboard

window.addEventListener('keydown', (e) => {
  if (e.isComposing || e.keyCode === 229) return;
  if (layerOpen()) {
    const top = layers[layers.length - 1].el;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeTop(); }
    else if (!top.contains(e.target)) { e.preventDefault(); e.stopPropagation(); }
    return;
  }
  if (!S.state || S.renaming) return;
  const k = e.key.toLowerCase();
  const cmd = e.metaKey && !e.ctrlKey && !e.altKey;
  let handled = true;
  if (cmd && !e.shiftKey && k === 'n') openNewSession();
  else if (cmd && !e.shiftKey && k === ',') openSettings();
  else if (cmd && (k === '/' || e.key === '?')) openShortcuts();
  else if (cmd && e.shiftKey && k === 'd') toggleInspector('changes');
  else if (cmd && e.shiftKey && k === 'a') toggleInspector('activity');
  else if (cmd && e.shiftKey && k === 'i') toggleInspector('details');
  else if (cmd && !e.shiftKey && e.key === '\\') { if (S.prefs.inspector_open) { setPref('inspector_open', false); render(); } }
  else if (e.metaKey && e.ctrlKey && k === 's') toggleSidebar();
  else if (e.ctrlKey && !e.metaKey && e.key === 'Tab') cycleSession(e.shiftKey ? -1 : 1);
  else handled = false;
  if (handled) { e.preventDefault(); e.stopPropagation(); }
}, true);

// ---------------------------------------------------------------- development hooks
// Only active when the App runs with --dev-snapshot-dir (state.dev): lets a tester open a dialog in
// the native window (which has no automation driver) before capturing its pixels.
function runDevHash() {
  if (!S.state || !S.state.dev || !location.hash.startsWith('#dev=')) return;
  const [action, arg, arg2] = location.hash.slice(5).split(':').map((x) => decodeURIComponent(x));
  history.replaceState(null, '', '/');
  const s = selectedSession();
  queueMicrotask(() => {
    if (action === 'settings') openSettings();
    else if (action === 'new') openNewSession();
    else if (action === 'add') openAddProject();
    else if (action === 'keys') openShortcuts();
    else if (action === 'handoff' && s) openHandoff(s);
    else if (action === 'stop' && s) stopSession(s, $('#toolbar .tb-group .btn:last-child'));
    else if (action === 'menu' && s) sessionMenu(s, $('#toolbar .tb-title .icon-btn'));
    else if (action === 'view' && s) switchView(s, s.view_mode === 'conversation' ? 'terminal' : 'conversation', $('#toolbar .view-seg button[aria-checked="false"]'));
    else if (action === 'desktop' && s) openInDesktop(s, $('#toolbar .tb-title .icon-btn'));
    else if (['model', 'effort', 'mode'].includes(action) && s) { S.devOpen = action; render(); }
    else if (action === 'attach' && s && convEl && convEl._attachBtn) attachMenu(s, convEl._attachBtn);
    else if (action === 'existing') openAddExisting({ harness: arg || undefined, pick: arg2 ? Number(arg2) : undefined });
    else if (action === 'unsent' && s && convEl && convEl._ta) {
      // Snapshot of the kept-message state: a synthetic message whose connection "failed" while a
      // new draft was in the box.
      convEl._ta.value = '等待连接时写的新草稿';
      S.drafts.set(s.session_id, convEl._ta.value);
      unsentTrack(S.unsent, { sid: s.session_id, clientId: 'devunsent', text: '把导出的金额统一保留两位小数，并补一个 0.1 + 0.2 的测试', atts: [], at: 0 });
      applyUnsent(s.session_id, unsentFail(S.unsent, s.session_id, 'devunsent', boxOf(s.session_id)), '连接失败，这条消息没有发出');
    }
    else if (action === 'filter') { $('#filter').value = arg || ''; S.filter = arg || ''; renderSidebar(); }
    else if (action === 'diff' && s) {
      const pick = (tries) => {
        const c = S.changes.get(s.session_id);
        const f = c && c.files[Number(arg) || 0];
        if (f) loadDiff(s.session_id, f.path); else if (tries > 0) setTimeout(() => pick(tries - 1), 250);
      };
      pick(20);
    }
  });
}

// ---------------------------------------------------------------- boot

for (const b of document.querySelectorAll('#inspector-tabs button')) {
  b.addEventListener('click', () => {
    setPref('inspector_tab', b.dataset.tab);
    const s = selectedSession();
    if (s && b.dataset.tab === 'details') loadDetails(s.session_id);
    if (s && b.dataset.tab === 'changes') loadChanges(s.session_id);
    render();
  });
}
$('#close-inspector').addEventListener('click', () => { setPref('inspector_open', false); render(); });
$('#new-session').addEventListener('click', () => openNewSession());
$('#add-project').addEventListener('click', openAddProject);
$('#open-settings').addEventListener('click', openSettings);
$('#filter').addEventListener('input', (e) => { S.filter = e.target.value; renderSidebar(); });
$('#filter').addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.target.value = ''; S.filter = ''; renderSidebar(); } });
makeResizer($('#sidebar-resizer'), 'sidebar');
makeResizer($('#inspector-resizer'), 'inspector');
new ResizeObserver(() => scheduleFit()).observe($('#stage'));
connect();
