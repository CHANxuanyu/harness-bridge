'use strict';
/* Minimal Markdown → DOM for assistant messages. Builds nodes with textContent only (never from
   HTML strings), so model output cannot inject markup or script. Covers what coding assistants
   write: paragraphs, headings, lists (nested), block quotes, fenced code, tables, rules, inline
   code, emphasis, strikethrough and links (http/https/mailto only). */

(function () {
  const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([^\s`]*)?.*$/;
  const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
  const QUOTE = /^ {0,3}>\s?(.*)$/;
  const ITEM = /^( *)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

  function el(tag, cls) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    return node;
  }

  function safeHref(url) {
    const u = url.trim();
    return /^(https?:\/\/|mailto:)/i.test(u) ? u : null;
  }

  // ---------------------------------------------------------------- inline

  const INLINE = [
    { re: /(`+)([\s\S]*?[^`])\1(?!`)/, make: (m) => { const c = el('code'); c.textContent = m[2].replace(/^ (.*) $/, '$1'); return c; } },
    { re: /\[([^\]\n]+)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/, make: (m) => link(m[1], m[2]) },
    { re: /<((?:https?:\/\/|mailto:)[^\s<>]+)>/, make: (m) => link(m[1], m[1]) },
    { re: /\*\*(?=\S)([\s\S]*?\S)\*\*/, make: (m) => wrap('strong', m[1]) },
    { re: /__(?=\S)([\s\S]*?\S)__(?!\w)/, make: (m) => wrap('strong', m[1]) },
    { re: /~~(?=\S)([\s\S]*?\S)~~/, make: (m) => wrap('del', m[1]) },
    { re: /\*(?=[^\s*])([\s\S]*?[^\s*])\*(?!\*)/, make: (m) => wrap('em', m[1]) },
    { re: /(?<![\w\\])_(?=[^\s_])([\s\S]*?[^\s_])_(?!\w)/, make: (m) => wrap('em', m[1]) },
    { re: /\bhttps?:\/\/[^\s<>()[\]]*[^\s<>()[\].,;:!?'"）。，；：！？]/, make: (m) => link(m[0], m[0]) },
  ];

  function wrap(tag, text) {
    const node = el(tag);
    node.append(inline(text));
    return node;
  }

  function link(text, url) {
    const href = safeHref(url);
    if (!href) { const span = el('span'); span.textContent = text; return span; }
    const a = el('a');
    a.dataset.href = href;
    a.title = href;
    a.setAttribute('role', 'link');
    a.tabIndex = 0;
    a.append(inline(text));
    return a;
  }

  function inline(text) {
    const frag = document.createDocumentFragment();
    let rest = text;
    while (rest) {
      let best = null;
      for (const rule of INLINE) {
        const m = rule.re.exec(rest);
        if (m && (!best || m.index < best.m.index)) best = { m, rule };
      }
      if (!best) { frag.append(unescape(rest)); break; }
      if (best.m.index > 0) frag.append(unescape(rest.slice(0, best.m.index)));
      frag.append(best.rule.make(best.m));
      rest = rest.slice(best.m.index + best.m[0].length);
    }
    return frag;
  }

  function unescape(text) {
    return document.createTextNode(text.replace(/\\([\\`*_{}[\]()#+\-.!|~>])/g, '$1'));
  }

  // ---------------------------------------------------------------- blocks

  function codeBlock(lang, code, onCopy) {
    const box = el('div', 'code-block');
    const head = el('div', 'code-head');
    const label = el('span');
    label.textContent = lang || '代码';
    head.append(label);
    if (onCopy) {
      const btn = el('button', 'icon-btn small');
      btn.type = 'button';
      btn.title = '复制代码';
      btn.setAttribute('aria-label', '复制代码');
      btn.textContent = '复制';
      btn.style.width = 'auto';
      btn.style.padding = '0 6px';
      btn.style.fontSize = '11px';
      btn.addEventListener('click', () => onCopy(code));
      head.append(btn);
    }
    const pre = el('pre', 'selectable');
    const c = el('code');
    c.textContent = code;
    pre.append(c);
    box.append(head, pre);
    return box;
  }

  function splitRow(line) {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
    const cells = [];
    let cur = '';
    for (let i = 0; i < t.length; i++) {
      if (t[i] === '\\' && t[i + 1] === '|') { cur += '|'; i++; } else if (t[i] === '|') { cells.push(cur.trim()); cur = ''; } else cur += t[i];
    }
    cells.push(cur.trim());
    return cells;
  }

  function table(lines) {
    const t = el('table');
    const head = splitRow(lines[0]);
    const thead = el('thead');
    const tr = el('tr');
    for (const c of head) { const th = el('th'); th.append(inline(c)); tr.append(th); }
    thead.append(tr);
    const tbody = el('tbody');
    for (const line of lines.slice(2)) {
      const row = el('tr');
      const cells = splitRow(line);
      for (let i = 0; i < head.length; i++) { const td = el('td'); td.append(inline(cells[i] || '')); row.append(td); }
      tbody.append(row);
    }
    t.append(thead, tbody);
    return t;
  }

  function list(lines, start, baseIndent, opts) {
    // Returns [node, nextIndex]. Items are lines matching ITEM at baseIndent; deeper lines nest.
    const first = ITEM.exec(lines[start]);
    const ordered = /\d/.test(first[2]);
    const node = el(ordered ? 'ol' : 'ul');
    if (ordered) { const n = parseInt(first[2], 10); if (n !== 1) node.start = n; }
    let i = start;
    while (i < lines.length) {
      const m = ITEM.exec(lines[i]);
      if (!m || m[1].length !== baseIndent || /\d/.test(m[2]) !== ordered) break;
      const li = el('li');
      const body = [m[3]];
      i++;
      while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) {
          const next = lines[i + 1];
          if (next !== undefined && next.length - next.trimStart().length > baseIndent && next.trim()) { body.push(''); i++; continue; }
          break;
        }
        const sub = ITEM.exec(line);
        if (sub && sub[1].length === baseIndent) break;
        if (line.length - line.trimStart().length <= baseIndent && !sub) {
          if (FENCE.test(line) || HEADING.test(line) || QUOTE.test(line)) break;
        }
        body.push(line.slice(Math.min(baseIndent + 2, line.length - line.trimStart().length)));
        i++;
      }
      li.append(blocks(body, opts, true));
      node.append(li);
    }
    return [node, i];
  }

  function blocks(lines, opts, tight) {
    const frag = document.createDocumentFragment();
    let i = 0;
    let para = [];
    const flush = () => {
      if (!para.length) return;
      const text = para.join('\n').trim();
      para = [];
      if (!text) return;
      if (tight && !frag.childNodes.length && i >= lines.length) { frag.append(inline(text)); return; }
      const p = el('p');
      const parts = text.split(/ {2,}\n|\\\n/);
      parts.forEach((part, k) => { if (k) p.append(el('br')); p.append(inline(part)); });
      frag.append(p);
    };
    while (i < lines.length) {
      const line = lines[i];
      const fence = FENCE.exec(line);
      if (fence) {
        flush();
        const marker = fence[1];
        const code = [];
        i++;
        while (i < lines.length && !lines[i].trimStart().startsWith(marker)) { code.push(lines[i]); i++; }
        i++;
        frag.append(codeBlock(fence[2] || '', code.join('\n'), opts.onCopy));
        continue;
      }
      if (!line.trim()) { flush(); i++; continue; }
      const heading = HEADING.exec(line);
      if (heading) { flush(); const hN = el(`h${heading[1].length}`); hN.append(inline(heading[2])); frag.append(hN); i++; continue; }
      if (RULE.test(line) && !para.length) { flush(); frag.append(el('hr')); i++; continue; }
      if (QUOTE.test(line)) {
        flush();
        const quoted = [];
        while (i < lines.length && QUOTE.test(lines[i])) { quoted.push(QUOTE.exec(lines[i])[1]); i++; }
        const bq = el('blockquote');
        bq.append(blocks(quoted, opts, false));
        frag.append(bq);
        continue;
      }
      if (line.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]) && lines[i + 1].includes('-')) {
        flush();
        const rows = [line, lines[i + 1]];
        i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(lines[i]); i++; }
        frag.append(table(rows));
        continue;
      }
      const item = ITEM.exec(line);
      if (item && (!para.length || item[1].length === 0)) {
        flush();
        const [node, next] = list(lines, i, item[1].length, opts);
        frag.append(node);
        i = next;
        continue;
      }
      para.push(line);
      i++;
    }
    flush();
    return frag;
  }

  window.renderMarkdown = function renderMarkdown(text, opts = {}) {
    const root = el('div', 'md');
    root.append(blocks(String(text || '').replace(/\r\n?/g, '\n').split('\n'), opts, false));
    return root;
  };
}());
