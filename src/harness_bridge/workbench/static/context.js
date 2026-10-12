'use strict';
/* Native context and commands in the conversation view.

   Context usage and compaction come only from the harness, through the App (backend contract
   docs/NATIVE_CONTEXT_API.md): GET /api/sessions/{id}/context (snapshot with capabilities),
   conversation.context and SSE conv events with op "context". An unknown value stays unknown, a
   stale one is labelled stale, a started compaction is never shown as finished, and an action is
   offered only when the App says it can admit it (capabilities.*.available). Nothing here polls a
   CLI, retries an action or touches the input box's draft or attachments.

   Every source carries the snapshot's session, run and order {run_seq, closed, revision} (contract
   "PM review contract revision"): within one session the larger (run_seq, closed, revision) wins,
   a closed run outranks every live snapshot of that run, and usage and compaction are taken
   together from the winning snapshot. Equal or older snapshots are ignored, whatever arrives last.
   A failed read is a read status, not a snapshot: the last accepted values stay, marked as failed
   and stale, and a late failure never marks a newer read or event as failed.

   "/" works as in each harness. POST /send is ordinary text only. Codex receives text as written,
   so a leading space keeps "/…" literal; its TUI commands that map to actions here (/model,
   /permissions, /compact, /status, /mention) run those actions, the others are refused. Claude
   Code reads a leading "/" itself, also after spaces or line breaks: such text is refused (the
   draft and attachments stay), and only commands from its own catalog go through the command
   action, identity-changing ones refused.

   Loaded after composer.js and before app.js; the helpers at the top hold no DOM state (tested
   in Node). */

// ---------------------------------------------------------------- pure helpers

const IDENTITY_COMMANDS = ['clear', 'reset', 'new', 'resume', 'fork'];
// Codex TUI commands that have the same action here (codex-rs/tui/src/slash_command.rs wording).
const CODEX_ACTIONS = {
  model: '选择模型和思考强度',
  permissions: '选择 Codex 可以做什么',
  compact: '压缩对话，避免超出上下文上限',
  status: '查看上下文用量与当前设置',
  mention: '引用一个文件',
};
const COMPACT_TEXT = {
  idle: null,
  requested: '已请求压缩',
  running: '正在压缩上下文',
  completed: '上下文已压缩',
  failed: '上下文压缩失败',
  unknown: '压缩结果未知',
};
const CTX_REASON = {
  not_observed: '还没有收到原生用量',
  native_usage_missing: '原生报告里没有用量',
  compaction_in_progress: '正在压缩，之前的用量不再准确',
  compaction_changed_context: '上下文已因压缩改变，等待新的用量',
  disconnected: '未连接，显示的是上次连接时的数据',
};
const CTX_ERROR = {
  native_completion_not_observed: '本轮结束时没有收到原生的完成信号',
  native_connection_lost: '连接在压缩过程中断开',
  native_outcome_unknown: '原生请求是否被接受没有得到确认',
  native_capability_unsupported: '当前原生版本不支持压缩',
};

function parseSlash(text) {
  // A command typed as such: "/" first, no leading space.
  const m = /^\/([A-Za-z][\w:.-]*)(?:\s+([\s\S]*))?$/.exec(String(text || '').replace(/\s+$/, ''));
  return m ? { name: m[1], args: (m[2] || '').trim() } : null;
}

// What sending this text does in this harness: 'text' (an ordinary message), 'compact', 'action'
// (a RepoBridge control that the harness itself offers as that command), 'command' (a validated
// Claude Code command) or 'refuse' (with the reason; the draft stays).
// Claude Code treats text whose first non-blank character is "/" as a command; the App refuses
// to send it as text (reason native_text_ambiguous) and so does this page, before any request.
const CLAUDE_SLASH_TEXT = 'Claude Code 会把以 / 开头的文字（前面有空格或换行也一样）当作命令处理，所以它不能作为普通文字发送。请改写开头，或从命令菜单选择命令。草稿和附件都还在。';

function slashRoute(harness, text, commands) {
  const parsed = parseSlash(text);
  if (harness === 'codex') {
    if (!parsed) return { kind: 'text' };
    const { name, args } = parsed;
    // Codex receives the text as written: a leading space really does make it ordinary text.
    const escape = '（如果这是普通文字，在开头加一个空格再发送，Codex 会按原文接收。）';
    if (name === 'compact') return args ? { kind: 'refuse', reason: `/compact 不接受额外内容，只请 Codex 压缩当前对话。${escape}` } : { kind: 'compact' };
    if (CODEX_ACTIONS[name]) return args ? { kind: 'refuse', reason: `/${name} 在对话视图中不接受参数。${escape}` } : { kind: 'action', name };
    return { kind: 'refuse', reason: `/${name} 属于 Codex 终端界面，对话视图没有接入，不会作为提示词发给 Codex。需要时切换到终端视图。${escape}` };
  }
  if (!parsed) return /^\s*\//.test(String(text || '')) ? { kind: 'refuse', reason: CLAUDE_SLASH_TEXT, code: 'native_text_ambiguous' } : { kind: 'text' };
  const { name, args } = parsed;
  if (IDENTITY_COMMANDS.includes(name)) {
    return { kind: 'refuse', reason: `/${name} 会改变会话身份（清空、新建、恢复或分叉），同一会话中没有接入。需要时切换到终端视图。` };
  }
  const list = commands || [];
  if (!list.some((c) => c.name === name)) {
    return { kind: 'refuse', reason: list.length ? `Claude Code 的命令目录里没有 /${name}。以 / 开头的文字会被 Claude Code 当作命令，不能作为普通文字发送；请改写开头。` : `还没有取得 Claude Code 的命令目录，连接后再使用 /${name}。` };
  }
  if (name === 'compact') return args ? { kind: 'refuse', reason: '专用压缩操作暂不接受额外指令，请只输入 /compact。' } : { kind: 'compact' };
  return { kind: 'command', name, args };
}

// Order of a context snapshot: [run_seq, closed, revision], or null when it has none (an older App).
function ctxOrderKey(snap) {
  const o = snap && snap.order;
  if (!o || !Number.isInteger(o.run_seq) || !Number.isInteger(o.revision) || typeof o.closed !== 'boolean') return null;
  return [o.run_seq, o.closed ? 1 : 0, o.revision];
}

// Whether `snap` replaces the accepted `prev` of session `sid`: 'accept', 'equal', 'older',
// 'other-session', 'conflict' (same run_seq, different run), 'unordered' (no order while the held
// one has one: never by arrival) or 'compat' (neither has an order: an older App, by arrival).
function contextVerdict(prev, snap, sid) {
  if (!snap || typeof snap !== 'object') return 'invalid';
  if (snap.session_id != null && snap.session_id !== sid) return 'other-session';
  const next = ctxOrderKey(snap);
  const held = prev ? ctxOrderKey(prev) : null;
  if (!next) return held ? 'unordered' : 'compat';
  if (!held) return 'accept';
  if (next[0] === held[0] && snap.run_id && prev.run_id && snap.run_id !== prev.run_id) return 'conflict';
  for (let i = 0; i < 3; i += 1) if (next[i] !== held[i]) return next[i] > held[i] ? 'accept' : 'older';
  return 'equal';
}

function orderSig(ctx) {
  const k = ctxOrderKey(ctx);
  return k ? k.join(':') : '';
}

function fmtTokens(n) {
  if (n === null || n === undefined) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, '')}M`;
  if (n >= 1e4) return `${Math.round(n / 1e3)}k`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1).replace(/\.0$/, '')}k`;
  return String(n);
}

// What the indicator shows. Estimates may exceed their window: the percentage is not clamped.
function contextView(ctx) {
  const usage = (ctx && ctx.usage) || {};
  const comp = (ctx && ctx.compaction) || { status: 'idle' };
  const status = comp.status || 'idle';
  const busy = status === 'requested' || status === 'running';
  const used = Number.isInteger(usage.used_tokens) && usage.used_tokens >= 0 ? usage.used_tokens : null;
  const cap = Number.isInteger(usage.capacity_tokens) && usage.capacity_tokens > 0 ? usage.capacity_tokens : null;
  const pct = used !== null && cap !== null ? Math.round((used / cap) * 100) : null;
  const readFailed = !!(ctx && ctx.readError);
  const stale = (!!usage.stale || readFailed) && used !== null;
  let tone = '';
  if (busy) tone = 'compacting';
  else if (status === 'failed') tone = 'bad';
  else if (status === 'unknown' || readFailed) tone = 'warn';
  else if (pct !== null && pct >= 90 && !stale) tone = 'warn';
  let text;
  if (busy) text = '压缩中';
  else if (pct !== null) text = `${stale ? '≈' : ''}${pct === 0 && used > 0 ? '<1' : pct}%`;
  else if (used !== null) text = `${stale ? '≈' : ''}${fmtTokens(used)}`;
  else if (status === 'failed') text = '压缩失败';
  else if (status === 'unknown') text = '压缩结果未知';
  else if (readFailed) text = '读取失败';
  else text = '—';
  return { used, cap, pct, stale, readFailed, known: used !== null, busy, status, tone, text, usage, comp };
}

// ---------------------------------------------------------------- context state (page)

function ctxStore() {
  if (!S.ctx) S.ctx = new Map();
  if (!S.ctxTimers) S.ctxTimers = new Map();
  return S.ctx;
}

function contextOf(sid) { return ctxStore().get(sid) || null; }

function repaintContext(sid) {
  const s = findSession(sid);
  if (s && S.sel && S.sel.id === sid && s.view_mode === 'conversation') updateConvChrome(s, convFor(sid));
  if (S.ctxPanel && S.ctxPanel.sid === sid) S.ctxPanel.paint();
}

// Take a context snapshot (GET, an action's result, conversation.context or an SSE event) if it is
// newer than the one held; returns whether it was taken. An action's request_receipt is not state.
function putContext(sid, snap) {
  const store = ctxStore();
  const prev = store.get(sid) || null;
  const verdict = contextVerdict(prev, snap, sid);
  if (verdict === 'equal' && snap.capabilities) {
    // The same state read again: only its capabilities (computed at read time) are newer.
    store.set(sid, { ...prev, capabilities: snap.capabilities, live: 'live' in snap ? !!snap.live : prev.live });
    repaintContext(sid);
    return false;
  }
  if (verdict !== 'accept' && verdict !== 'compat') return false;
  const closed = !!(snap.order && snap.order.closed);
  const sameRun = !!prev && prev.run_id === snap.run_id;
  store.set(sid, {
    session_id: sid,
    run_id: snap.run_id ?? null,
    order: snap.order || null,
    usage: snap.usage || null,
    compaction: snap.compaction || null,
    harness: snap.harness ?? (prev && prev.harness),
    native_session_id: snap.native_session_id ?? (prev && prev.native_session_id),
    live: closed ? false : 'live' in snap ? !!snap.live : sameRun && !!prev.live,
    // An event carries no capabilities; the held ones stay a hint until the next read.
    capabilities: snap.capabilities || (prev && prev.capabilities) || null,
    compat: verdict === 'compat',
    missing: false,
    readError: null,
  });
  // A new or closed run changes what can be done: read the capabilities again.
  if (!snap.capabilities && (!sameRun || closed)) scheduleContextFetch(sid);
  repaintContext(sid);
  return true;
}

// A read failure is a status of the held values, not a snapshot. Each read is bound to the
// session's latest read generation and to the snapshot held when it started.
async function fetchContext(sid) {
  ctxStore();
  if (!S.ctxReads) S.ctxReads = new Map();
  const gen = (S.ctxReads.get(sid) || 0) + 1;
  S.ctxReads.set(sid, gen);
  const before = orderSig(contextOf(sid));
  try {
    const snap = await api('GET', `/api/sessions/${sid}/context`);
    putContext(sid, snap);
    const now = contextOf(sid);
    if (now && now.readError && S.ctxReads.get(sid) === gen) { now.readError = null; repaintContext(sid); }
  } catch (e) {
    const now = contextOf(sid);
    if (S.ctxReads.get(sid) !== gen || orderSig(now) !== before) return now; // something newer came
    if (e.code === 'NOT_FOUND' && !(now && now.order)) {
      ctxStore().set(sid, { ...(now || {}), missing: true }); // an App without the context interface
    } else {
      ctxStore().set(sid, { ...(now || {}), readError: { message: e.message || String(e), at: Date.now() } });
    }
    repaintContext(sid);
  }
  return contextOf(sid);
}

function scheduleContextFetch(sid, ms = 250) {
  ctxStore();
  clearTimeout(S.ctxTimers.get(sid));
  S.ctxTimers.set(sid, setTimeout(() => { S.ctxTimers.delete(sid); fetchContext(sid); }, ms));
}

function newActionId() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

// Why compaction cannot start now, from what this window knows; the App decides in the end.
function compactBlockedReason(s, ctx) {
  const v = contextView(ctx);
  const cap = ((ctx && ctx.capabilities) || {}).compact || {};
  const label = HARNESS[s.harness].label;
  if (ctx && ctx.missing) return '当前 RepoBridge 后端没有提供上下文接口。';
  if (cap.native_support === 'unsupported') return `当前 ${label} 版本不支持压缩。`;
  if (v.busy) return '正在压缩。';
  if (v.status === 'unknown') return '上次压缩结果未知：先在原生历史中核对。RepoBridge 不会自动重试。';
  if (!s.active || !(ctx && ctx.live)) return `先连接会话：发送一条消息后，会在同一个原生连接上压缩，不会新建会话。`;
  if (s.turn) return '这一轮结束后可以压缩。';
  const c = convFor(s.session_id);
  if ([...c.items.values()].some((x) => x.type === 'permission' && x.status === 'pending')) return '先处理待确认的权限请求或问题。';
  if (unsentBlocking(S.unsent, s.session_id)) return '先核对送达结果未知的消息。';
  const st = settingsOf(s);
  if (Object.values(st.fields).some((r) => r && (r.state === 'selected' || r.state === 'applying'))) return '有尚未生效的设置；压缩不会代替普通消息应用设置。';
  return `${label} 的连接尚未就绪。`;
}

// ---------------------------------------------------------------- actions

async function startCompact(sid, anchor, { fromComposer = false } = {}) {
  const s = findSession(sid);
  if (!s) return;
  const ctx = await fetchContext(sid);
  const cap = ((ctx && ctx.capabilities) || {}).compact;
  // From the input box the reason sits above the kept "/compact"; elsewhere it is a toast.
  const refuse = (m) => (fromComposer ? composerNotice(sid, m) : toast(m, 'error'));
  if (ctx && ctx.readError) { refuse(`读取上下文失败，现在无法确认能否压缩：${ctx.readError.message}`); return; }
  if (!cap || !cap.implemented) { refuse(compactBlockedReason(s, ctx || { missing: true })); return; }
  if (!cap.available) { refuse(compactBlockedReason(s, ctx)); return; }
  const label = HARNESS[s.harness].label;
  // A new action ID per click, with the run the window shows; never reused automatically.
  const body = { request_id: newActionId(), run_id: ctx.run_id };
  await guarded(`compact:${sid}`, async () => {
    let res;
    try {
      res = await api('POST', `/api/sessions/${sid}/compact`, body);
    } catch (e) {
      if (e.details && e.details.context) putContext(sid, e.details.context);
      throw e;
    }
    putContext(sid, res); // the current state; a reused request's own receipt is not shown as it
    if (fromComposer) clearComposerIf(sid, '/compact');
    toast(res && res.reused ? '这个压缩请求已经提交过；显示的是当前状态。' : `已请 ${label} 压缩上下文。是否完成以 ${label} 的报告为准。`);
  }, anchor instanceof Element ? anchor : null);
}

async function refreshContextUsage(sid, anchor) {
  await guarded(`ctxrefresh:${sid}`, async () => {
    putContext(sid, await api('POST', `/api/sessions/${sid}/context-refresh`, {}));
  }, anchor instanceof Element ? anchor : null);
}

// Remove a command typed in the input box once its action has started (the rest of the draft stays).
function clearComposerIf(sid, text) {
  const root = convEl;
  if (!root || root.dataset.sid !== sid || !root._ta) return;
  if (root._ta.value.trim() !== text) return;
  root._ta.value = '';
  S.drafts.delete(sid);
  autosize(root._ta);
  updateConvChrome(findSession(sid), convFor(sid));
}

function runSlashAction(s, name) {
  const root = convEl;
  const anchor = (sel) => (root && root._right ? root._right.querySelector(sel) : null) || (root && root._ta);
  if (name === 'model') openModelPicker(s, anchor('.cpill.model'));
  else if (name === 'permissions') openModePicker(s, (root && root._left.querySelector('.cpill.mode')) || root._ta);
  else if (name === 'status') openContextPanel(s, anchor('.ctx-ind'));
  else if (name === 'mention') insertAtCaret(s.session_id, '@');
  else if (name === 'compact') startCompact(s.session_id, anchor('.ctx-ind'));
}

// ---------------------------------------------------------------- indicator & panel

function ringSvg(pct, busy) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('class', `ctx-ring ${busy ? 'spin' : ''}`.trim());
  svg.setAttribute('viewBox', '0 0 16 16');
  svg.setAttribute('aria-hidden', 'true');
  const track = document.createElementNS(ns, 'circle');
  Object.entries({ cx: 8, cy: 8, r: 6, class: 'track' }).forEach(([k, v]) => track.setAttribute(k, v));
  const bar = document.createElementNS(ns, 'circle');
  const len = 2 * Math.PI * 6;
  const frac = busy ? 0.3 : pct === null ? 0 : Math.max(0, Math.min(1, pct / 100));
  Object.entries({ cx: 8, cy: 8, r: 6, class: 'bar', 'stroke-dasharray': `${(frac * len).toFixed(2)} ${len.toFixed(2)}`, transform: 'rotate(-90 8 8)' }).forEach(([k, v]) => bar.setAttribute(k, v));
  svg.append(track, bar);
  return svg;
}

function usageLines(s, ctx) {
  const v = contextView(ctx);
  const u = v.usage;
  const label = HARNESS[s.harness].label;
  const lines = [];
  if (ctx && ctx.missing) return ['当前 RepoBridge 后端没有提供上下文接口。'];
  if (!v.known) lines.push(`暂无用量数据：${CTX_REASON[u.reason] || u.reason || '还没有收到原生用量'}`);
  else {
    lines.push(`约 ${v.used.toLocaleString()}${v.cap ? ` / ${v.cap.toLocaleString()}` : ''} tokens${v.pct !== null ? `（${v.pct}%）` : ''}`);
    if (u.capacity_kind === 'model_context_window') lines.push('窗口：模型上下文窗口（modelContextWindow）');
    else if (u.capacity_kind === 'native_compaction_window') lines.push(`窗口：${label} 压缩策略窗口（不是模型上限）`);
    lines.push(u.basis === 'native_last_context_estimate' ? '依据：最近一次请求的上下文估计（不是累计用量）' : `依据：${label} 的上下文估计`);
  }
  if (u.source) lines.push(`来源：${u.source}${u.observed_at ? ` · ${clock(u.observed_at)} 收到` : ''}`);
  if (v.stale && u.stale) lines.push(`旧数据：${CTX_REASON[u.reason] || u.reason || '可能已变化'}`);
  if (ctx && ctx.compat) lines.push('后端没有提供顺序信息（较旧版本）：按到达顺序显示。');
  return lines;
}

// A failed read, shown with the values it leaves in place.
function readFailureLine(ctx) {
  const r = ctx && ctx.readError;
  if (!r) return null;
  const kept = ctx.order || ctx.usage ? '显示的是最近一次成功读取的数据，可能已过时。' : '还没有成功读取过。';
  return `读取上下文失败（${clock(r.at)}）：${r.message}。${kept}`;
}

function compactLine(s, ctx) {
  const comp = (ctx && ctx.compaction) || {};
  const status = comp.status || 'idle';
  if (status === 'idle') return null;
  const trigger = comp.trigger === 'user' ? '你发起' : comp.trigger === 'native' ? `${HARNESS[s.harness].label} 自动` : '来源未知';
  const when = comp.updated_at ? clock(comp.updated_at) : '';
  const err = comp.error ? `：${CTX_ERROR[comp.error] || comp.error}` : '';
  return { status, text: `${COMPACT_TEXT[status] || status}${err}`, meta: [trigger, when].filter(Boolean).join(' · ') };
}

function renderContextIndicator(s) {
  const ctx = contextOf(s.session_id);
  const v = contextView(ctx);
  const label = HARNESS[s.harness].label;
  const outcome = (v.status === 'failed' ? '，上次压缩失败' : v.status === 'unknown' ? '，上次压缩结果未知' : '')
    + (v.readFailed ? '，读取失败' : '');
  const aria = ctx && ctx.missing ? '上下文：后端未提供'
    : v.busy ? `上下文：${COMPACT_TEXT[v.status]}`
    : v.known ? `上下文：已用约 ${v.pct !== null ? `${v.text.replace('≈', '')}` : fmtTokens(v.used)}${v.stale ? '（旧数据）' : ''}${outcome}`
    : `上下文：暂无用量数据${outcome}`;
  const title = [`上下文 · ${label}`, ...usageLines(s, ctx), (compactLine(s, ctx) || {}).text, readFailureLine(ctx)].filter(Boolean).join('\n');
  return h('button', {
    class: `ctx-ind ${v.tone} ${v.known ? '' : 'unknown'} ${v.stale ? 'stale' : ''} ${v.readFailed ? 'read-failed' : ''} ${v.text === '—' ? 'empty' : ''}`.replace(/\s+/g, ' ').trim(), type: 'button',
    title, 'aria-label': aria, 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
    onclick: (e) => openContextPanel(findSession(s.session_id) || s, e.currentTarget),
  }, ringSvg(v.pct, v.busy), h('span', { class: 'ctx-word' }, '上下文'), h('span', { class: 'ctx-text' }, v.text));
}

function openContextPanel(s, anchor) {
  const sid = s.session_id;
  const el = h('div', { class: 'popover ctx-panel', role: 'dialog', 'aria-label': `上下文 · ${HARNESS[s.harness].label}` });
  const opener = anchor instanceof Element ? anchor : null;
  const paint = () => {
    const now = findSession(sid) || s;
    const ctx = contextOf(sid);
    const v = contextView(ctx);
    const caps = (ctx && ctx.capabilities) || {};
    const compact = caps.compact || {};
    const refresh = caps.context_refresh || {};
    const label = HARNESS[now.harness].label;
    const line = compactLine(now, ctx);
    // While it runs the compaction line above already says so.
    const reason = compact.implemented && !compact.available && !v.busy ? compactBlockedReason(now, ctx) : null;
    const compactBtn = compact.implemented
      ? h('button', { class: 'btn btn-small', type: 'button', disabled: !compact.available || v.busy || v.readFailed, onclick: (e) => startCompact(sid, e.currentTarget) }, v.busy ? '正在压缩…' : '立即压缩')
      : null;
    const refreshBtn = refresh.implemented
      ? h('button', { class: 'btn btn-small', type: 'button', disabled: !refresh.available, title: refresh.available ? null : `${label} 空闲且已连接时才能读取`, onclick: (e) => refreshContextUsage(sid, e.currentTarget) }, '刷新用量')
      : null;
    el.replaceChildren(...[
      h('div', { class: 'ctx-head' }, ringSvg(v.pct, v.busy), h('div', { class: 'grow' },
        h('div', { class: 'ctx-big' }, v.known ? `${v.pct !== null ? `${v.stale ? '≈' : ''}${v.pct}%` : fmtTokens(v.used)}` : '暂无数据'),
        h('div', { class: 'hint' }, `上下文估计 · ${label}`))),
      h('div', { class: 'ctx-lines' }, usageLines(now, ctx).map((t) => h('div', {}, t))),
      h('div', { class: 'ctx-sep' }),
      h('div', { class: 'ctx-sub' }, '压缩'),
      line ? h('div', { class: `ctx-comp ${line.status}`, role: 'status' }, line.status === 'running' || line.status === 'requested' ? stGlyph({ tone: 'idle', glyph: 'spin' }) : null, h('span', {}, line.text), line.meta ? h('span', { class: 'hint' }, ` · ${line.meta}`) : null)
        : h('div', { class: 'hint' }, '这个会话还没有压缩记录。'),
      compact.implemented
        ? h('div', { class: 'hint' }, `立即压缩会在同一会话中执行 ${compact.native_method || ''}，可能使用模型；不会发送输入框里的内容。自动压缩由 ${label} 自己决定。`)
        : h('div', { class: 'hint' }, ctx && ctx.missing ? '当前后端没有提供压缩操作。' : '正在读取上下文能力…'),
      reason ? h('div', { class: 'ctx-reason' }, reason) : null,
      readFailureLine(ctx) ? h('div', { class: 'ctx-reason', role: 'alert' }, readFailureLine(ctx)) : null,
      compactBtn || refreshBtn || v.readFailed ? h('div', { class: 'actions' },
        // Reading again is a read, not a retried action.
        v.readFailed ? h('button', { class: 'btn btn-small', type: 'button', onclick: () => fetchContext(sid) }, '重新读取') : null,
        refreshBtn, compactBtn) : null,
    ].filter(Boolean)); // replaceChildren would print a null as text
  };
  if (S.ctxPanel) S.ctxPanel.close();
  if (opener) opener.setAttribute('aria-expanded', 'true');
  const close = pushLayer(el, () => { if (opener) opener.setAttribute('aria-expanded', 'false'); if (S.ctxPanel && S.ctxPanel.el === el) S.ctxPanel = null; }, { returnFocus: opener });
  S.ctxPanel = { sid, el, paint, close };
  paint();
  place(el, anchor);
  const first = el.querySelector('button:not(:disabled)');
  (first || el).focus();
  fetchContext(sid); // fresh capabilities; paint() runs again when they arrive
}

// ---------------------------------------------------------------- "/" menu

function claudeCommands(s) {
  return ((catalogOf(s).commands) || []).filter((c) => c && c.name);
}

function openCommandMenu(s, anchor) {
  const sid = s.session_id;
  const label = HARNESS[s.harness].label;
  const panel = menuPanel(anchor, { title: `${label} 命令与上下文`, cls: 'cmd-menu' });
  const draw = () => {
    const now = findSession(sid) || s;
    const ctx = contextOf(sid);
    const caps = (ctx && ctx.capabilities) || {};
    const compact = caps.compact || {};
    const refresh = caps.context_refresh || {};
    const v = contextView(ctx);
    const compactReason = v.readFailed ? '读取上下文失败，现在无法确认能否压缩'
      : !compact.implemented ? (ctx && ctx.missing ? '当前后端没有提供压缩操作' : '正在读取上下文能力…') : !compact.available ? compactBlockedReason(now, ctx) : null;
    const items = [
      { head: '上下文' },
      { key: 'ctx', kind: 'action', icon: 'gauge', label: '查看上下文用量与压缩…', note: now.harness === 'codex' ? '/status' : null, action: () => openContextPanel(now, renderedIndicator() || anchor) },
      { key: 'compact', kind: 'action', icon: 'refresh', label: v.busy ? '正在压缩…' : '压缩上下文', note: '/compact', disabled: !!compactReason || v.busy, reason: compactReason, desc: compactReason ? null : `在同一会话中执行 ${compact.native_method || ''}，可能使用模型`, action: () => startCompact(sid, anchor) },
    ];
    if (refresh.implemented) items.push({ key: 'refresh', kind: 'action', icon: 'refresh', label: '刷新上下文用量', desc: refresh.available ? `${refresh.native_method}，不调用模型` : `${label} 空闲且已连接时才能读取`, disabled: !refresh.available, action: () => refreshContextUsage(sid, anchor) });
    items.push('-', { head: '设置' },
      { key: 'model', kind: 'action', icon: 'spark', label: '模型与思考强度…', note: now.harness === 'codex' ? '/model' : null, action: () => runSlashAction(now, 'model') },
      { key: 'mode', kind: 'action', icon: 'shield', label: now.harness === 'codex' ? '权限…' : '权限模式…', note: now.harness === 'codex' ? '/permissions' : null, action: () => runSlashAction(now, 'permissions') },
      '-', { head: '附件与引用' },
      { key: 'att', kind: 'action', icon: 'image', label: '添加图片或文件…', desc: '也可以粘贴或拖入', action: () => pickFiles(sid) },
      { key: 'at', kind: 'action', icon: 'search', label: '引用项目文件', note: '@', action: () => insertAtCaret(sid, '@') });
    if (now.harness === 'claude-code') {
      const cmds = claudeCommands(now).filter((c) => c.name !== 'compact');
      items.push('-', { head: `Claude Code 命令（${cmds.length}）` });
      if (!cmds.length) items.push({ text: '还没有取得 Claude Code 的命令目录；连接后显示。' });
      for (const c of cmds) {
        const blocked = IDENTITY_COMMANDS.includes(c.name);
        items.push({
          key: `c:${c.name}`, kind: 'action', label: `/${c.name}`, mono: true, note: c.hint || null,
          desc: blocked ? null : c.description, disabled: blocked,
          reason: blocked ? '会改变会话身份，同一会话中没有接入' : null,
          action: () => insertAtCaret(sid, `/${c.name} `, true),
        });
      }
      items.push({ text: '选择命令会把它放进输入框；按 ↩ 后由 Claude Code 执行。命令可能使用模型。' });
    } else {
      items.push('-', { text: 'Codex 的其他 / 命令（如 /review、/diff）属于它的终端界面，对话视图没有接入；需要时切换到终端视图。' });
    }
    panel.set(items);
  };
  panel.onPaint(draw);
  draw();
  fetchContext(sid).then(() => { if (panel.el.isConnected) draw(); });
}

function renderedIndicator() {
  const root = convEl;
  return root && root._right ? root._right.querySelector('.ctx-ind') : null;
}

// Entries for the "/" list typed in the input box: the same actions and (Claude) the catalog.
function slashEntries(s, q) {
  const query = (q || '').toLowerCase();
  const match = (name) => name.toLowerCase().includes(query);
  if (s.harness === 'codex') {
    return Object.entries(CODEX_ACTIONS).filter(([name]) => match(name))
      .map(([name, desc]) => ({ label: `/${name}`, desc, action: name }));
  }
  const out = [];
  if (match('compact')) out.push({ label: '/compact', desc: '压缩上下文（同一会话，可能使用模型）', action: 'compact' });
  for (const c of claudeCommands(s)) {
    if (c.name === 'compact' || !match(c.name)) continue;
    if (IDENTITY_COMMANDS.includes(c.name)) out.push({ label: `/${c.name}`, desc: '会改变会话身份，同一会话中没有接入', disabled: true });
    else out.push({ label: `/${c.name}`, desc: c.description, note: c.hint, value: `/${c.name} ` });
  }
  return out;
}
