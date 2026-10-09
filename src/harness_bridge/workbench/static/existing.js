'use strict';
/* Existing native sessions: find a Claude Code / Codex session created outside RepoBridge in one
   project, preview it, link it (the same native session, never a copy), and page its history.
   Only the backend routes are used (/api/history, /api/sessions/link, the session routes): the page
   never reads vendor files. Nothing here starts a session or sends a message, and nothing polls:
   every request follows a user action or a state change the user caused. */

// ---------------------------------------------------------------- wording (machine codes → text)

const LINK_SOURCE_TEXT = { cli: '命令行', desktop: '官方桌面客户端', cloud: '云端', other: '其他客户端', unknown: '来源未记录' };
const LINK_SOURCE_TIP = {
  cli: '原生记录表明它由命令行创建',
  desktop: '原生记录表明它由官方桌面客户端创建',
  cloud: '云端会话，不能在本机恢复',
  other: '由其他客户端（例如编辑器扩展）创建',
  unknown: '原生记录没有说明它由哪个客户端创建；RepoBridge 不按标题猜测来源',
};
const RESUME_REASON_TEXT = {
  unsupported_source: '这个来源不支持在本机恢复，只能查看历史',
  directory_missing: '工作目录不存在；恢复这个文件夹后才能继续',
  environment_changed: '原生存储位置与添加时不同，不能恢复',
  unlinked: '已从 RepoBridge 移除关联；重新添加后才能继续',
};
const REASON_TEXT = {
  local_only: '只搜索了本机这个项目的记录，云端和其他项目的会话不在其中',
  native_index_only: '只列出 Codex 自己索引中的会话',
  scan_limit: '记录太多，只检查了其中一部分',
  symlink_skipped: '跳过了以符号链接存放的记录目录',
  directory_unreadable: '有记录目录无法读取',
  invalid_native_metadata: '有记录的原生信息无效或与项目不符，已跳过',
  malformed_native_record: '有无法解析的原生记录，已跳过',
  native_file_limit: '会话记录文件超过读取上限，只读取了前面的部分',
  native_page_limit: 'Codex 历史超过读取上限，只读取了最近的部分',
  history_snapshot_limit: '历史超过 RepoBridge 的保留上限，只保留了最近的部分',
};
const reasonText = (r) => REASON_TEXT[r] || r;

const isLinked = (s) => !!(s && s.native_link && s.native_link.linked);
const wasUnlinked = (s) => !!(s && s.native_link && !s.native_link.linked);
const linkHold = (s) => !!(s && s.external && s.external.via === 'native-link');

// What a failed request means for the history UI; decided by code/details, never by message text.
// PREFLIGHT_FAILED covers any failed precondition or native read, so it is a read failure: "not
// supported" needs an explicit capability reason from the contract, and the contract
// (docs/EXISTING_SESSIONS_API.md at ad585c5) does not define one yet. Sources that cannot be
// resumed are told apart by the candidate's own resume_reason instead.
function historyFailure(e) {
  const code = e && e.code;
  const d = (e && e.details) || {};
  if (code === 'STATE_CONFLICT' && d.reason === 'cursor_expired') return { kind: 'expired', text: '读取位置已过期（超过 10 分钟、应用重启过或缓存已满）' };
  if (code === 'PREFLIGHT_FAILED') return { kind: 'error', preflight: true, text: (e && e.message) || '读取前的检查没有通过' };
  if (code === 'NOT_FOUND') return { kind: 'gone', text: (e && e.message) || '找不到' };
  return { kind: 'error', text: (e && e.message) || String(e) };
}

// ---------------------------------------------------------------- history paging (pure)
// A model is any object with items (Map id → item) and order (ids, oldest first). Pages follow
// docs/EXISTING_SESSIONS_API.md: the first page is the newest, `before` pages are older, `since`
// returns changed or new items by stable ID (or reset=true: replace everything). A response
// without `page` is the legacy unpaged shape: the whole list, nothing older to fetch.

function pagerReplace(m, data) {
  m.items = new Map();
  m.order = [];
  for (const it of data.items || []) { if (!m.items.has(it.id)) m.order.push(it.id); m.items.set(it.id, it); }
  const p = data.page || null;
  m.paged = !!p;
  m.page = p;
  m.history = data.history || null;
  m.partial = data.partial_reasons || [];
  m.nextBefore = p ? p.next_before || null : null;
  m.hasMore = !!(p && p.has_more && p.next_before);
  m.nextSince = p ? p.next_since || null : null;
}

// Older page: put in front; an ID already loaded keeps its (newer) version.
function pagerPrepend(m, data) {
  const fresh = [];
  for (const it of data.items || []) {
    if (m.items.has(it.id)) continue;
    m.items.set(it.id, it);
    fresh.push(it.id);
  }
  m.order = fresh.concat(m.order);
  const p = data.page || {};
  m.nextBefore = p.next_before || null;
  m.hasMore = !!(p.has_more && p.next_before);
  return fresh;
}

// Refresh: replace changed items in place, append new ones in the order given.
function pagerMerge(m, data) {
  const p = data.page || {};
  if (p.reset) { pagerReplace(m, data); return { reset: true, added: [], changed: [] }; }
  const added = [];
  const changed = [];
  for (const it of data.items || []) {
    if (m.items.has(it.id)) changed.push(it.id);
    else { m.order.push(it.id); added.push(it.id); }
    m.items.set(it.id, it);
  }
  if (data.history) m.history = data.history;
  if (data.partial_reasons) m.partial = data.partial_reasons;
  m.page = { ...p, next_before: m.nextBefore, has_more: m.hasMore };
  if (p.next_since) m.nextSince = p.next_since;
  return { reset: false, added, changed };
}

// What the loaded history amounts to, for the state line: loading / empty / partial / unavailable /
// ready, plus why.
function historyState(m) {
  if (!m.paged) return { state: (m.history && m.history.error) ? 'unavailable' : 'legacy', reasons: [] };
  const p = m.page || {};
  const reasons = (p.completeness && p.completeness.reasons) || m.partial || [];
  return { state: p.state || 'ready', reasons, error: m.history && m.history.error };
}

// ---------------------------------------------------------------- shared pieces of UI

function sourceChip(source) {
  return h('span', { class: `ex-chip src-${source}`, title: LINK_SOURCE_TIP[source] || null }, LINK_SOURCE_TEXT[source] || source);
}

// The line above a history: where it came from and whether it is complete. `onRefresh` adds the
// refresh action (user initiated; nothing polls).
function historyBanner(m, { label, loading, refreshing, error, refreshNote, onRefresh, onRetry, retryLabel = '重试' }) {
  const st = historyState(m);
  const box = h('div', { class: 'hist-banner' });
  const line = h('div', { class: 'hist-line' });
  if (loading && !m.order.length) line.append(stGlyph({ tone: 'idle', glyph: 'spin' }), h('span', {}, '正在读取原生历史…'));
  else {
    const src = m.history && m.history.source;
    const from = src === 'claude-transcript' ? `${label} 的会话记录` : src === 'codex' ? 'Codex 原生历史' : src === 'live-structured' ? `当前与 ${label} 的连接` : src === 'cache' ? 'RepoBridge 上次的记录' : null;
    if (from) line.append(h('span', {}, `历史来自 ${from}`));
    if (st.state === 'partial') line.append(h('span', { class: 'hist-tag warn' }, '部分可见'));
    else if (st.state === 'empty') line.append(h('span', { class: 'hist-tag' }, '原生历史为空'));
    else if (st.state === 'unavailable') line.append(h('span', { class: 'hist-tag bad' }, '读取失败'));
  }
  if (refreshing) line.append(stGlyph({ tone: 'idle', glyph: 'spin' }), h('span', {}, '正在刷新…'));
  else if (refreshNote) line.append(h('span', { class: 'hist-note' }, refreshNote));
  if (onRefresh && !loading) line.append(h('button', { class: 'btn-plain', type: 'button', title: '重新读取原生历史，查看在别处新增或更新的内容', onclick: onRefresh }, icon('refresh'), '刷新'));
  if (line.childNodes.length) box.append(line);
  const problems = [];
  if (error) problems.push(h('div', { class: 'hist-problem bad', role: 'alert' }, icon('warning'), h('span', { class: 'selectable' }, error), onRetry ? h('button', { class: 'btn-plain', type: 'button', onclick: onRetry }, retryLabel) : null));
  if (st.state === 'unavailable' && st.error) problems.push(h('div', { class: 'hist-problem bad', role: 'alert' }, icon('warning'), h('span', { class: 'selectable' }, `无法读取原生历史：${st.error}`)));
  if (st.state === 'partial' && st.reasons.length) {
    problems.push(h('div', { class: 'hist-problem warn' }, icon('warning'), h('span', {}, `只显示了能读到的部分：${st.reasons.map(reasonText).join('；')}`)));
  }
  box.append(...problems);
  return box.childNodes.length ? box : null;
}

// Top-of-list control for older pages.
function olderControl(m, { loading, error, onLoad, onReload }) {
  if (!m.paged) return null;
  if (loading) return h('div', { class: 'hist-older' }, stGlyph({ tone: 'idle', glyph: 'spin' }), '正在读取更早的消息…');
  if (error) {
    return h('div', { class: 'hist-older warn', role: 'alert' }, icon('warning'), h('span', {}, error.text),
      error.kind === 'expired' && onReload ? h('button', { class: 'btn btn-small', type: 'button', onclick: onReload }, '从最近的消息重新载入')
        : h('button', { class: 'btn btn-small', type: 'button', onclick: onLoad }, '重试'));
  }
  if (m.hasMore) return h('button', { class: 'btn btn-small hist-older-btn', type: 'button', onclick: onLoad }, '加载更早的消息');
  if (!m.order.length) return null;
  // Only the snapshot/page limits cut off older content; other partial reasons do not.
  const cut = (historyState(m).reasons || []).some((r) => r === 'history_snapshot_limit' || r === 'native_page_limit');
  if (cut) return h('div', { class: 'hist-older' }, '更早的内容超出读取上限，没有显示');
  return h('div', { class: 'hist-older' }, '已到可读取历史的开头');
}

// Keep what the reader is looking at in place while nodes are inserted above it.
function keepAnchor(scroller, fn) {
  const fromBottom = scroller.scrollHeight - scroller.scrollTop;
  fn();
  scroller.scrollTop = scroller.scrollHeight - fromBottom;
}

// ---------------------------------------------------------------- linked sessions

function holdText(s) {
  const label = HARNESS[s.harness].label;
  return `可能仍在 ${label} 或官方桌面客户端中使用。RepoBridge 看不到外部是否还在执行；请先确认那边已经结束，避免两个写入者同时写同一个原生会话。`;
}

// Explicit user statement that outside use has ended (clears the hold; does not start anything).
function confirmOutsideEnded(s, anchor) {
  const label = HARNESS[s.harness].label;
  confirmPopover(anchor, {
    title: '外部已经结束？',
    text: `这个会话来自 RepoBridge 之外，${holdText(s)}确认后，RepoBridge 才会在你发送消息或恢复时用 ${label} 的原生恢复继续同一个会话（原生 ID 不变）。这一步不会启动会话。`,
    confirm: '已结束',
    onConfirm: () => guarded(`return:${s.session_id}`, async () => {
      await api('POST', `/api/sessions/${s.session_id}/desktop/return`, {});
      toast('已记录：外部已结束。继续时会接续同一个原生会话。');
      if (s.view_mode === 'conversation') refreshConversation(s.session_id);
    }),
  });
}

function unlinkSession(s, anchor) {
  const label = HARNESS[s.harness].label;
  confirmPopover(anchor, {
    title: '移除这个关联？',
    text: `只从 RepoBridge 中移除。${label} 中的原生历史不会删除；之后可以用“添加已有会话”重新添加，会回到同一个本地会话。`,
    confirm: '移除关联',
    danger: true,
    onConfirm: async () => {
      if (S.pending.has(`unlink:${s.session_id}`)) return;
      S.pending.add(`unlink:${s.session_id}`);
      try {
        const r = await api('POST', `/api/sessions/${s.session_id}/unlink`, {});
        toast(r.native_history_preserved ? '已移除关联。原生历史保留在原处。' : '已移除关联。');
        disposeTerm(s.session_id);
        if (S.sel && S.sel.id === s.session_id && !S.prefs.show_archived) select({ type: 'project', id: s.project_id }, { focus: false });
      } catch (e) {
        const now = findSession(s.session_id) || s;
        const d = e.details || {};
        // A refusal is shown as such; RepoBridge never lifts the protection by itself.
        if (d.external || (d.busy_session_id === s.session_id && now.external)) {
          toast('它可能仍在外部使用，所以没有移除。确认外部已经结束（“外部已结束…”）后再移除；RepoBridge 不会自动解除这个保护。', 'error');
        } else if (d.busy_session_id === s.session_id) {
          toast('这个会话正在 RepoBridge 中运行，先断开或停止它，再移除关联。', 'error');
        } else fail(e);
      } finally { S.pending.delete(`unlink:${s.session_id}`); }
    },
  });
}

function linkSection(s) {
  const nl = s.native_link;
  if (!nl) return null;
  const label = HARNESS[s.harness].label;
  const resumeText = nl.resume_reason ? RESUME_REASON_TEXT[nl.resume_reason] || nl.resume_reason : (nl.resumable ? `可以用 ${label} 的原生恢复继续` : '不能在本机恢复');
  return h('div', { class: 'sect' }, h('h3', {}, '已有会话关联'), h('div', { class: 'kv' },
    h('div', { class: 'k' }, '状态'), h('div', { class: 'v' }, nl.linked ? '已关联同一个原生会话' : '已移除关联（原生历史保留）'),
    h('div', { class: 'k' }, '来源'), h('div', { class: 'v', title: LINK_SOURCE_TIP[nl.source] || null }, LINK_SOURCE_TEXT[nl.source] || nl.source),
    h('div', { class: 'k' }, '原生存储'), h('div', { class: 'v' }, (nl.environment && nl.environment.label) || '—'),
    h('div', { class: 'k' }, '工作目录'), h('div', { class: 'v' }, nl.directory_state === 'missing' ? '不存在' : '存在'),
    h('div', { class: 'k' }, '继续'), h('div', { class: 'v' }, resumeText),
    nl.linked ? [h('div', { class: 'k' }, '外部使用'), h('div', { class: 'v' }, linkHold(s) ? '未确认已结束' : s.external ? `已在 ${s.external.app} 中打开` : '已确认结束或未在外部打开')] : null),
  h('div', { style: 'display:flex;gap:8px;margin-top:10px;flex-wrap:wrap' },
    nl.linked && linkHold(s) && !s.active ? h('button', { class: 'btn btn-small', type: 'button', onclick: (e) => confirmOutsideEnded(s, e.currentTarget) }, '外部已结束…') : null,
    nl.linked ? h('button', { class: 'btn btn-small', type: 'button', disabled: s.active, title: s.active ? '先断开或停止' : null, onclick: (e) => unlinkSession(s, e.currentTarget) }, icon('link'), '移除关联…')
      : h('button', { class: 'btn btn-small', type: 'button', onclick: () => reAddSession(s) }, icon('link'), '重新添加…')),
  h('div', { class: 'hint', style: 'margin-top:6px' }, '历史始终从原生记录读取；RepoBridge 只保存这个关联。“观察到的轮次”只统计在 RepoBridge 中看到的轮次，不代表原生历史长度。'));
}

// ---------------------------------------------------------------- add-existing dialog

function openAddExisting({ projectId, harness, query, pick, prefer } = {}) {
  const projects = S.state.projects;
  if (!projects.length) { openAddProject(); return; }
  const st = {
    pid: projectId || (selectedProject() || projects[0]).project_id,
    harness: harness || S.prefs.last_harness || 'claude-code',
    q: query || '',
    view: 'conversation',
    rows: [], next: null, completeness: null, listLoading: false, listError: null, moreLoading: false, moreError: null, listNote: null,
    sel: null, previews: new Map(), alive: true, seq: 0,
  };
  S.existing = st;
  const projectSelect = h('select', { class: 'select', 'aria-label': '项目' }, projects.map((p) => h('option', { value: p.project_id }, p.name)));
  projectSelect.value = st.pid;
  const seg = h('div', { class: 'seg-inline', role: 'radiogroup', 'aria-label': 'Harness' });
  const search = h('input', { class: 'input ex-search', type: 'search', placeholder: '搜索标题或原生会话 ID', 'aria-label': '搜索', spellcheck: 'false', autocomplete: 'off' });
  search.value = st.q;
  const reload = h('button', { class: 'icon-btn', type: 'button', title: '重新读取列表', 'aria-label': '重新读取列表' }, icon('refresh'));
  const list = h('div', { class: 'ex-list', role: 'listbox', 'aria-label': '原生会话' });
  const preview = h('div', { class: 'ex-preview', 'aria-live': 'polite' });
  const foot = h('div', { class: 'ex-foot hint' });
  const viewSeg = h('div', { class: 'seg-inline', role: 'radiogroup', 'aria-label': '打开方式' });
  const viewLabel = h('span', { class: 'ex-view-label hint' }, '打开为');
  const primary = h('button', { class: 'btn btn-primary', type: 'button', disabled: true }, '添加到项目');
  let close = () => {};

  const drawSeg = () => {
    // Claude matches title or native ID; Codex's own list searches titles only.
    search.placeholder = st.harness === 'codex' ? '搜索标题' : '搜索标题或原生会话 ID';
    seg.replaceChildren(...['claude-code', 'codex'].map((k) => h('button', {
      type: 'button', role: 'radio', 'aria-pressed': String(st.harness === k), 'aria-checked': String(st.harness === k),
      onclick: () => { if (st.harness !== k) { st.harness = k; drawSeg(); discover(); } },
    }, h('span', { class: `dot ${k}` }), ` ${HARNESS[k].label}`)));
    viewSeg.replaceChildren(...[['conversation', '对话'], ['terminal', '终端']].map(([v, l]) => h('button', {
      type: 'button', role: 'radio', 'aria-pressed': String(st.view === v), 'aria-checked': String(st.view === v), onclick: () => { st.view = v; drawSeg(); },
    }, l)));
  };

  const current = () => st.rows.find((r) => r.candidate_id === st.sel) || null;

  // ---- list
  const discover = async ({ more = false, note = null } = {}) => {
    const seq = ++st.seq;
    if (more) { st.moreLoading = true; st.moreError = null; } else {
      st.listLoading = true; st.listError = null; st.moreError = null; st.listNote = note;
    }
    drawList();
    const qs = new URLSearchParams({ project_id: st.pid, harness: st.harness, limit: '30' });
    if (st.q) qs.set('q', st.q);
    if (more && st.next) qs.set('cursor', st.next);
    try {
      const page = await api('GET', `/api/history?${qs}`);
      if (!st.alive || seq !== st.seq) return;
      if (more) {
        const known = new Set(st.rows.map((r) => r.candidate_id));
        st.rows = st.rows.concat(page.items.filter((r) => !known.has(r.candidate_id)));
      } else {
        st.rows = page.items;
        if (pick !== undefined && st.rows[pick]) { st.sel = st.rows[pick].candidate_id; pick = undefined; }
        const hit = prefer && st.rows.find((r) => r.native_session_id === prefer);
        if (hit) { st.sel = hit.candidate_id; prefer = undefined; }
        if (!st.rows.some((r) => r.candidate_id === st.sel)) st.sel = st.rows.length ? st.rows[0].candidate_id : null;
      }
      st.next = page.next_cursor || null;
      st.completeness = page.completeness || null;
    } catch (e) {
      if (!st.alive || seq !== st.seq) return;
      const f = historyFailure(e);
      if (more && f.kind === 'expired') {
        // The contract: restart from the first page. Say so instead of silently reshuffling.
        st.moreLoading = false;
        discover({ note: '列表的读取位置已过期，已从第一页重新读取。' });
        return;
      }
      if (more) st.moreError = f; else { st.listError = f; st.rows = []; st.next = null; st.completeness = null; st.sel = null; }
    } finally {
      if (st.alive && seq === st.seq) { st.listLoading = false; st.moreLoading = false; drawList(); drawPreview({ anchor: 'top' }); }
    }
    if (st.alive && seq === st.seq && st.sel && needsPreview(st.sel)) loadPreview(st.sel);
  };

  const rowNode = (r) => {
    const selected = r.candidate_id === st.sel;
    const badges = [];
    if (r.already_linked) badges.push(h('span', { class: 'ex-badge ok' }, r.already_linked.archived ? '已添加（已归档）' : '已添加'));
    if (r.directory_state === 'missing') badges.push(h('span', { class: 'ex-badge warn' }, '目录不存在'));
    else if (!r.resumable) badges.push(h('span', { class: 'ex-badge' }, '只能查看'));
    if (r.occupancy && r.occupancy.state === 'repobridge') badges.push(h('span', { class: 'ex-badge ok' }, '正在 RepoBridge 中运行'));
    else if (r.occupancy && r.occupancy.state === 'external') badges.push(h('span', { class: 'ex-badge warn' }, '外部未确认结束'));
    return h('div', {
      class: `ex-row ${selected ? 'selected' : ''}`, role: 'option', tabindex: selected ? '0' : '-1', 'aria-selected': String(selected),
      dataset: { cid: r.candidate_id },
      onclick: () => choose(r.candidate_id),
      ondblclick: () => { choose(r.candidate_id); act(); },
      onkeydown: rowKey,
    },
    h('div', { class: 'ex-row-top' }, h('span', { class: 'ex-title' }, r.title || r.native_session_id), h('span', { class: 'ex-time' }, clock(r.updated_at))),
    h('div', { class: 'ex-row-meta' }, sourceChip(r.source), h('span', { class: 'ex-path', title: r.workdir }, r.project_match === 'root' ? '项目根目录' : shortPath(r.workdir, 40)), badges));
  };

  const drawList = () => {
    const keepFocus = list.contains(document.activeElement);
    const scroll = list.scrollTop;
    list.replaceChildren();
    const label = HARNESS[st.harness].label;
    if (st.listNote) list.append(h('div', { class: 'ex-note' }, st.listNote));
    if (st.listLoading && !st.rows.length) {
      list.append(h('div', { class: 'ex-state' }, stGlyph({ tone: 'idle', glyph: 'spin' }), `正在读取这个项目的 ${label} 原生记录…`));
    } else if (st.listError) {
      const f = st.listError;
      list.append(h('div', { class: 'ex-state bad', role: 'alert' },
        h('b', {}, '读取失败'),
        h('div', { class: 'selectable' }, f.text),
        h('div', { class: 'hint' }, f.preflight ? `这不是“没有会话”：读取前的检查没有通过，也没有退回到更大范围的搜索。可以检查 ${label} 和项目文件夹后重试。` : '这不是“没有会话”：读取本身没有成功。'),
        h('button', { class: 'btn btn-small', type: 'button', onclick: () => discover() }, '重试')));
    } else if (!st.rows.length) {
      list.append(h('div', { class: 'ex-state' }, h('b', {}, st.q ? '没有匹配的会话' : `没有找到 ${label} 会话`),
        h('div', {}, st.q ? `在这个项目的本机记录中，没有${st.harness === 'codex' ? '标题' : '标题或原生 ID '}含“${st.q}”的会话。` : `这个项目的文件夹在本机没有可读取的 ${label} 会话记录。`)));
    } else {
      for (const r of st.rows) list.append(rowNode(r));
      if (st.moreLoading) list.append(h('div', { class: 'ex-more' }, stGlyph({ tone: 'idle', glyph: 'spin' }), '正在读取更多…'));
      else if (st.moreError) list.append(h('div', { class: 'ex-more warn' }, st.moreError.text, h('button', { class: 'btn-plain', type: 'button', onclick: () => discover({ more: true }) }, '重试')));
      else if (st.next) list.append(h('button', { class: 'btn btn-small ex-more-btn', type: 'button', onclick: () => discover({ more: true }) }, '加载更多'));
    }
    list.scrollTop = scroll;
    if (keepFocus) { const el = list.querySelector('.ex-row.selected'); if (el) el.focus(); }
    const c = st.completeness;
    foot.replaceChildren();
    if (c && !st.listError) {
      foot.append(c.state === 'complete' ? '已读取这个项目在本机的全部原生记录。' : `列表不是全部：${c.reasons.map(reasonText).join('；')}。`);
    }
  };

  function rowKey(e) {
    const i = st.rows.findIndex((r) => r.candidate_id === st.sel);
    if (e.key === 'ArrowDown' && st.rows[i + 1]) { e.preventDefault(); choose(st.rows[i + 1].candidate_id, true); }
    else if (e.key === 'ArrowUp' && i > 0) { e.preventDefault(); choose(st.rows[i - 1].candidate_id, true); }
    else if (e.key === 'Enter') { e.preventDefault(); act(); }
  }

  const choose = (cid, focus = false) => {
    if (st.sel === cid) return;
    st.sel = cid;
    drawList();
    if (focus) { const el = list.querySelector('.ex-row.selected'); if (el) { el.focus(); el.scrollIntoView({ block: 'nearest' }); } }
    if (needsPreview(cid)) loadPreview(cid); else drawPreview();
  };
  // Drawing creates an empty model, so "not fetched yet" is decided by its flags, not by presence.
  const needsPreview = (cid) => { const m = st.previews.get(cid); return !m || (!m.loaded && !m.loading && !m.error); };

  // ---- preview
  const pv = (cid) => {
    let m = st.previews.get(cid);
    if (!m) { m = { items: new Map(), order: [], loaded: false, loading: false, error: null, older: null, olderLoading: false, refreshing: false, note: null }; st.previews.set(cid, m); }
    return m;
  };

  const loadPreview = async (cid, { since = false } = {}) => {
    const m = pv(cid);
    if (m.loading || m.refreshing) return;
    const qs = new URLSearchParams({ limit: '40' });
    if (since && m.nextSince) { qs.set('since', m.nextSince); m.refreshing = true; } else m.loading = true;
    m.error = null;
    m.note = null;
    const anchor = since ? 'follow' : undefined;
    if (st.sel === cid) drawPreview({ anchor });
    try {
      const data = await api('GET', `/api/history/${cid}?${qs}`);
      if (!st.alive) return;
      if (since && m.nextSince) {
        const r = pagerMerge(m, data);
        if (r.reset) m.older = null;
        m.note = r.reset ? '已重新读取最近的部分（原生历史被改写，或读取位置已过期）' : (r.added.length || r.changed.length) ? `新增 ${r.added.length} 条，更新 ${r.changed.length} 条` : '没有新内容';
      } else pagerReplace(m, data);
      m.loaded = true;
    } catch (e) {
      if (!st.alive) return;
      const f = historyFailure(e);
      m.error = f;
      if (f.kind === 'gone' || f.kind === 'expired') m.error = { ...f, text: '这一项已过期（应用重启过或项目范围变了），请重新读取列表。', relist: true };
    } finally { m.loading = false; m.refreshing = false; }
    if (st.alive && st.sel === cid) drawPreview({ anchor });
  };

  const loadPreviewOlder = async (cid) => {
    const m = pv(cid);
    if (!m.hasMore || m.olderLoading) return;
    m.olderLoading = true;
    m.older = null;
    if (st.sel === cid) drawPreview({ anchor: 'bottom' });
    try {
      const data = await api('GET', `/api/history/${cid}?${new URLSearchParams({ limit: '40', before: m.nextBefore })}`);
      if (!st.alive) return;
      pagerPrepend(m, data);
    } catch (e) {
      if (!st.alive) return;
      m.older = historyFailure(e);
    } finally { m.olderLoading = false; }
    // Older messages go above what the reader is looking at; it stays where it was.
    if (st.alive && st.sel === cid) drawPreview({ anchor: 'bottom' });
  };

  // anchor: undefined = newest at the bottom (first show); 'top' = keep the scroll offset (an item
  // expanded or refreshed in place); 'bottom' = keep the distance from the end (content added above).
  const drawPreview = ({ anchor } = {}) => {
    const r = current();
    const old = preview.querySelector('.ex-hist');
    const oldTop = old ? old.scrollTop : 0;
    const oldFromEnd = old ? old.scrollHeight - old.scrollTop : 0;
    const wasAtEnd = !old || old.scrollTop + old.clientHeight >= old.scrollHeight - 40;
    preview.replaceChildren();
    updatePrimary();
    if (!r) {
      preview.append(h('div', { class: 'ex-state' }, st.listLoading ? '' : '选择左侧的一个会话来预览它的历史。'));
      return;
    }
    const label = HARNESS[r.harness].label;
    const m = pv(r.candidate_id);
    const occ = r.occupancy || { state: 'unknown' };
    const occText = occ.state === 'repobridge' ? '正在 RepoBridge 中运行' : occ.state === 'external' ? '外部使用未确认结束' : '外部使用情况未知（不等于空闲）';
    const resumeText = r.resume_reason ? (RESUME_REASON_TEXT[r.resume_reason] || r.resume_reason)
      : r.already_linked ? '已添加；打开那个会话后在那里继续' : r.resumable ? `可以用 ${label} 的原生恢复继续（需先确认外部已结束）` : '不能在本机恢复';
    preview.append(h('div', { class: 'ex-head' },
      h('div', { class: 'ex-head-title' }, h('span', { class: `dot ${r.harness}` }), h('span', { class: 'selectable' }, r.title || r.native_session_id)),
      h('div', { class: 'kv ex-kv' },
        h('div', { class: 'k' }, '原生 ID'), h('div', { class: 'v mono selectable' }, r.native_session_id,
          h('button', { class: 'icon-btn small', type: 'button', title: '复制原生会话 ID', 'aria-label': '复制原生会话 ID', onclick: () => copyText(r.native_session_id, '已复制原生会话 ID') }, icon('copy'))),
        h('div', { class: 'k' }, '工作目录'), h('div', { class: 'v selectable', title: r.workdir }, homeify(r.workdir), r.directory_state === 'missing' ? h('span', { class: 'ex-badge warn' }, '不存在') : null),
        h('div', { class: 'k' }, '来源'), h('div', { class: 'v' }, sourceChip(r.source), h('span', { class: 'hint' }, ` · ${(r.environment && r.environment.label) || '本机'}`)),
        h('div', { class: 'k' }, '更新'), h('div', { class: 'v' }, clock(r.updated_at)),
        h('div', { class: 'k' }, '外部使用'), h('div', { class: 'v' }, occText),
        h('div', { class: 'k' }, '继续'), h('div', { class: 'v' }, resumeText))));
    const scroller = h('div', { class: 'ex-hist' });
    const inner = h('div', { class: 'ex-hist-inner' });
    scroller.append(inner);
    const relist = m.error && m.error.relist;
    const banner = historyBanner(m, {
      label,
      loading: m.loading,
      refreshing: m.refreshing,
      error: m.error ? m.error.text : null,
      refreshNote: m.note,
      onRefresh: m.loaded ? () => loadPreview(r.candidate_id, { since: true }) : null,
      onRetry: relist ? () => { st.previews.clear(); discover(); } : () => loadPreview(r.candidate_id),
      retryLabel: relist ? '重新读取列表' : '重试',
    });
    if (banner) inner.append(banner);
    if (m.loaded) {
      const older = olderControl(m, { loading: m.olderLoading, error: m.older, onLoad: () => loadPreviewOlder(r.candidate_id), onReload: () => { st.previews.delete(r.candidate_id); loadPreview(r.candidate_id); } });
      if (older) inner.append(older);
      const fake = { session_id: null, harness: r.harness, workdir: r.workdir, preview: true, repaint: () => drawPreview({ anchor: 'top' }) };
      let shown = 0;
      for (const id of m.order) {
        const it = m.items.get(id);
        const node = it ? itemNode(fake, it.type === 'permission' && it.status === 'pending' ? { ...it, status: 'expired' } : it) : null;
        if (node) { inner.append(node); shown++; }
      }
      const hs = historyState(m);
      if (!shown && hs.state === 'empty') inner.append(h('div', { class: 'ex-state' }, h('b', {}, '原生历史里没有可显示的消息'), h('div', {}, '读取成功，但这个会话没有用户或助手消息可以显示。')));
      else if (!shown && hs.state !== 'unavailable' && !m.error) inner.append(h('div', { class: 'ex-state' }, '这一页没有可显示的消息。'));
    }
    preview.append(scroller);
    if (anchor === 'top') scroller.scrollTop = oldTop;
    else if (anchor === 'bottom') scroller.scrollTop = scroller.scrollHeight - oldFromEnd;
    else if (anchor === 'follow' && !wasAtEnd) scroller.scrollTop = oldTop;
    else scroller.scrollTop = scroller.scrollHeight;
    scroller.addEventListener('scroll', () => {
      if (scroller.scrollTop < 80 && m.hasMore && !m.olderLoading && !m.older && scroller._lastTop > scroller.scrollTop) loadPreviewOlder(r.candidate_id);
      scroller._lastTop = scroller.scrollTop;
    });
    scroller._lastTop = scroller.scrollTop;
  };

  const updatePrimary = () => {
    const r = current();
    primary.disabled = !r || S.pending.has('link-existing');
    viewSeg.hidden = viewLabel.hidden = !r || !!r.already_linked;
    if (r && r.already_linked) {
      primary.textContent = '打开已添加的会话';
      primary.title = '这个原生会话已经添加过；打开那个会话，不会创建副本';
    } else {
      primary.textContent = '添加到项目';
      primary.title = r ? '关联同一个原生会话；不会启动会话，也不会发送消息' : '';
    }
  };

  // ---- link
  const act = () => {
    const r = current();
    if (!r || primary.disabled) return;
    if (r.already_linked) { close(); selectWhenReady(r.already_linked.session_id); return; }
    guarded('link-existing', async () => {
      let res;
      try {
        res = await api('POST', '/api/sessions/link', { candidate_id: r.candidate_id, view_mode: st.view });
      } catch (e) {
        const f = historyFailure(e);
        if (f.kind === 'gone' || f.kind === 'expired') {
          st.previews.clear();
          discover({ note: '这个列表已过期（应用重启过或项目范围变了），已重新读取；请再选一次。' });
          return;
        }
        throw e;
      }
      // The local session ID is result.session.session.session_id (contract), never a guess.
      const session = res.session && res.session.session;
      const sid = session && session.session_id;
      if (!sid) throw new ApiError({ message: '后端没有返回关联的会话' });
      close();
      setPref('last_harness', r.harness);
      selectWhenReady(sid);
      const title = session.title || r.title;
      if (res.created) toast(`已添加「${title}」。没有启动会话，也没有发送消息。`);
      else if (res.relinked) toast(`已重新添加「${title}」，回到同一个本地会话。继续前需要确认外部已经结束。`);
      else toast(`「${title}」已经添加过，已打开它（没有创建副本）。`);
    }, primary);
  };
  primary.addEventListener('click', act);

  // ---- inputs (no polling: only these handlers and the dialog opening fetch)
  let searchTimer = null;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { st.q = search.value.trim(); discover(); }, 300);
  });
  search.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); const el = list.querySelector('.ex-row.selected') || list.querySelector('.ex-row'); if (el) el.focus(); }
    if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); clearTimeout(searchTimer); st.q = search.value.trim(); discover(); }
  });
  projectSelect.addEventListener('change', () => { st.pid = projectSelect.value; st.previews.clear(); st.sel = null; discover(); });
  reload.addEventListener('click', () => { st.previews.clear(); discover(); });

  close = dialog([
    h('h2', {}, '添加已有会话'),
    h('p', { class: 'sub' }, '从这个项目在本机的原生记录中，选择一个以前在 Claude Code 或 Codex 里创建的会话。添加只是关联同一个原生会话：不会复制历史、不会新建或启动会话，也不会发送消息。'),
    h('div', { class: 'ex-bar' }, projectSelect, seg, h('div', { class: 'ex-search-wrap' }, icon('search'), search), reload),
    h('div', { class: 'ex-body' }, list, preview),
    h('div', { class: 'actions' }, h('div', { class: 'left ex-left' }, foot), viewLabel, viewSeg,
      h('button', { class: 'btn', type: 'button', onclick: () => close() }, '取消'), primary),
  ], { wide: true, cls: 'ex-dialog', onClose: () => { st.alive = false; clearTimeout(searchTimer); if (S.existing === st) S.existing = null; } });
  drawSeg();
  drawList();
  drawPreview();
  discover();
  setTimeout(() => search.focus(), 30);
  return st;
}

// Re-add a removed association: the dialog opens on the same native session. Claude's list
// searches titles and native IDs; Codex's own list searches titles only, so it is preselected.
function reAddSession(s) {
  openAddExisting({ projectId: s.project_id, harness: s.harness, query: s.harness === 'claude-code' ? s.native_session_id : undefined, prefer: s.native_session_id });
}

// The state stream may deliver a just-linked session slightly after the request returns.
function selectWhenReady(sid) {
  if (findSession(sid)) { select({ type: 'session', id: sid }); return; }
  S.pendingSelect = { id: sid, until: Date.now() + 5000 };
}
