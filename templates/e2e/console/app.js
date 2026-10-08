/* E2E 用例评审控制台 —— 前端
 *
 * 状态模型（用户 2026-09-23 定「乙」）：
 *   committed = 最近一次「提交」的快照（服务端账本里读出来）
 *   draft     = 页面上还没提交的执行结果与勾选（存浏览器 localStorage，刷新不丢）
 *   effective = draft 覆盖 committed
 * 只有点「提交」才会把 draft 一次性写进账本 + 回写索引；执行与勾选本身不落任何服务端文件。
 */
'use strict';

const DRAFT_KEY = (src) => `atlas-console-draft:v3:${src}`;

const S = {
  source: 'app', sources: {},
  cases: [], nodeids: {}, committed: { ts: null, actor: null, cases: {} },
  draft: {}, open: new Set(), outputs: {}, busy: null, logCase: null, heldCase: null,
  filter: { type: 'all', page: 'all', unreviewed: false, q: '' },
  cfg: { slowmo: 500, timeout: 120, head: true },
};

const $ = (id) => document.getElementById(id);
const hhmm = (ts) => String(ts || '').slice(11, 16);
const nowISO = () => new Date().toISOString().replace('T', ' ').slice(0, 19).replace(' ', 'T');
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* ---------------- 本地草稿 ---------------- */
function loadDraft() {
  try { S.draft = JSON.parse(localStorage.getItem(DRAFT_KEY(S.source)) || '{}') || {}; }
  catch (e) { S.draft = {}; }
}
function saveDraft() {
  try { localStorage.setItem(DRAFT_KEY(S.source), JSON.stringify(S.draft)); } catch (e) { /* 忽略配额错误 */ }
}
const srcCfg = () => S.sources[S.source] || {};
const canRun = () => !!srcCfg().configured;
function patch(id, obj) {
  S.draft[id] = Object.assign({}, S.draft[id] || {}, obj);
  saveDraft();
}
function dropDraft() { S.draft = {}; saveDraft(); }
const effective = (id) => S.draft[id] || S.committed.cases[id] || null;
const pendingCount = () => Object.keys(S.draft).length;

async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  return r.json();
}

function notify(msg, code) {
  const el = $('notify');
  if (!msg) { el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerText = msg;
  el.style.background = code ? 'var(--bad-bg)' : 'var(--warn-bg)';
  el.style.color = code ? 'var(--bad)' : 'var(--warn)';
  el.style.borderColor = code ? '#f0cdc9' : '#e8dcbb';
}
function notifyHTML(html, code) {
  const el = $('notify');
  el.hidden = false;
  el.innerHTML = html;
  el.style.background = code ? 'var(--bad-bg)' : 'var(--warn-bg)';
  el.style.color = code ? 'var(--bad)' : 'var(--warn)';
  el.style.borderColor = code ? '#f0cdc9' : '#e8dcbb';
}

async function load() {
  const d = await api(`api/cases?source=${S.source}`);
  S.cases = d.cases; S.nodeids = d.nodeids; S.committed = d.committed || { cases: {} };
  S.manual = d.manual || [];
  // 手工项并入列表（类型 manual）：与用例同列表渲染/筛选/评审，但不进「用例 N」统计
  S.cases = S.cases.concat(S.manual.map((m) => ({
    id: m.id, page: m.page, title: m.title, type: 'manual', status: 'manual',
    ac: '', need: '', intent: m.note, note: m.note,
  })));
  S.manualCount = S.manual.length;
  S.sources = d.sources || {};
  S.cfg = { slowmo: d.slowmo, timeout: d.timeout, head: d.head };
  $('slowmo').value = d.slowmo;
  const c = S.committed;
  S.heldCase = d.held_case || null;
  const cfg = srcCfg();
  $('meta').textContent = `来源 ${cfg.label || S.source}（${cfg.base_url || '未配置'}）`
    + ` · ${d.head ? '执行时弹出浏览器窗口' : '无头执行（不弹窗口）'} · 一次跑一条 · 单条超时 ${d.timeout}s`
    + (c.ts ? ` · 最近提交 ${hhmm(c.ts)}（${c.actor || ''}）` : ' · 尚未提交过');
  const pages = [...new Set(S.cases.map((x) => x.page))];
  $('f-page').innerHTML = '<option value="all">全部</option>' + pages.map((p) => `<option value="${p}">${p}</option>`).join('');
  if (d.problem) notify(d.problem, true);
  else if (!cfg.configured) notify(`${cfg.why}。本来源暂不可执行；其余照旧可看用例与已提交结果。`);
  render();
}

/* ---------------- 视图 ---------------- */
const isPass = (id) => !!(effective(id) || {}).ok;
const isReviewed = (id) => !!(((effective(id) || {}).reviewed) || {}).pass;

function visible(c) {
  const f = S.filter;
  if (f.type !== 'all' && c.type !== f.type) return false;
  if (f.page !== 'all' && c.page !== f.page) return false;
  if (f.unreviewed && isReviewed(c.id)) return false;   // 按**人工 review** 状态筛（与顶栏「待评审」同口径）
  if (f.q) {
    const hay = `${c.id} ${c.title} ${c.intent} ${c.page} ${c.testid.join(' ')}`.toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  return true;
}

function counts() {
  let ran = 0, pass = 0, bad = 0, reviewed = 0;
  for (const c of S.cases) {
    const e = effective(c.id);
    if (e && typeof e.ok === 'boolean') { ran++; e.ok ? pass++ : bad++; }
    if (isReviewed(c.id)) reviewed++;
  }
  const realTotal = S.cases.length - (S.manualCount || 0);
  return { total: realTotal, ran, pass, bad, reviewed, left: S.cases.length - reviewed, pending: pendingCount() };
}

function render() {
  const k = counts();
  $('stats').innerHTML = [
    ['用例', k.total], ['已执行', k.ran], ['执行通过', k.pass], ['执行失败', k.bad],
    ['已评审', k.reviewed], ['待评审', k.left], ['未提交', k.pending],
  ].map(([label, n], i) => {
    const hot = (i === 6 && n > 0) ? ' hot' : '';
    return `<div class="stat${hot}"><b>${n}</b><span>${label}</span></div>`;
  }).join('');

  const shown = S.cases.filter(visible);
  $('closewin').hidden = !S.heldCase;
  $('closewin').textContent = S.heldCase ? `关闭浏览器窗口（${S.heldCase}）` : '关闭浏览器窗口';
  const tbody = $('tbody');
  if (!shown.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty">没有匹配的用例。</td></tr>'; return; }
  const byPage = new Map();
  for (const c of shown) { if (!byPage.has(c.page)) byPage.set(c.page, []); byPage.get(c.page).push(c); }

  let html = '';
  for (const [page, list] of byPage) {
    const collapsed = S.open.has(page);
    html += `<tr class="group"><td colspan="4">`
      + `<span class="gtoggle" data-toggle="${page}">${collapsed ? '▸' : '▾'}</span>`
      + `<span class="gname">${esc(page)}</span>`
      + `<span class="gcount">${list.length} 条 · 执行通过 ${list.filter((c) => isPass(c.id)).length}/${list.length}`
      + ` · 已评审 ${list.filter((c) => isReviewed(c.id)).length}</span></td></tr>`;
    if (collapsed) continue;
    for (const c of list) html += rowHTML(c);
  }
  tbody.innerHTML = html;
}

function rowHTML(c) {
  const isManual = c.type === 'manual';
  const e = effective(c.id);
  const busy = S.busy === c.id;
  const nodeid = S.nodeids[c.id];
  const out = S.outputs[c.id] || (e && e.tail) || '';
  const reviewed = (e || {}).reviewed;
  const reviewedPass = !!(reviewed && reviewed.pass);
  const unlocked = isManual || !!(e && e.ok);
  const canCheck = unlocked || reviewedPass;

  let pill = isManual ? '<span class="pill none">走查</span>' : '<span class="pill none">未跑</span>';
  let excerpt = '';
  if (e && typeof e.ok === 'boolean') {
    pill = e.timeout ? '<span class="pill warn">超时</span>'
      : e.ok ? '<span class="pill ok">通过</span>' : '<span class="pill bad">失败</span>';
    if (!e.ok) {
      const tail = String(out).split('\n')
        .filter((l) => /Error|assert|E  {2,}|FAILED|passed|failed|不可见|Timeout/i.test(l)).slice(-3).join('\n');
      excerpt = `<div class="excerpt">${esc(tail || '（点「输出」看失败原文）')}</div>`;
    }
  }
  if (busy) pill = '<span class="pill run">执行中…</span>';

  const reviewCell = `<label class="chk${canCheck ? '' : ' off'}" title="${unlocked ? '勾选＝复核该条执行结果符合业务预期；再点一次取消（提交后才落账本）' : reviewedPass ? '取消勾选即撤销评审' : '执行通过后才可勾选'}">
      <input type="checkbox" data-review="${c.id}" ${reviewedPass ? 'checked' : ''} ${canCheck ? '' : 'disabled'}>
      <span>通过</span>
    </label>`
    + (reviewedPass
        ? `<div class="who" title="勾选 ${esc(reviewed.checked_at || '')}${reviewed.unchecked_at ? ` · 上次撤销 ${esc(reviewed.unchecked_at)}` : ''}">`
          + `勾于 ${esc(hhmm(reviewed.checked_at))}${reviewed.unchecked_at ? ` · 撤过 ${esc(hhmm(reviewed.unchecked_at))}` : ''}</div>`
        : (unlocked ? '' : `<div class="why">执行通过未达成</div>`));

  return `<tr class="row${busy ? ' busy' : ''}" data-case="${c.id}">
    <td class="pagecell">${esc(c.page)}</td>
    <td>
      <span class="cid">${esc(c.id)}</span><span class="ctitle">${esc(c.title)}</span>
      <div class="cline">${esc(c.intent)}</div>
      <div class="cmeta">
        ${isManual ? '' : `<span class="tag">${esc(c.type)}</span>`}
        <span class="tag">${esc(c.ac)}</span>
        ${c.need ? `<span class="tag">需求 ${esc(c.need)}</span>` : ''}
        ${S.draft[c.id] ? '<span class="tag dirty">未提交</span>' : ''}
        ${isManual ? '' : `<button class="btn btn-ghost" data-detail="${c.id}">${S.open.has('d:' + c.id) ? '收起' : '展开'}</button>`}
      </div>
      ${S.open.has('d:' + c.id) ? detailHTML(c) : ''}
    </td>
    <td>
      ${isManual
        ? `<button class="btn btn-run" data-open="${c.id}" ${S.busy ? 'disabled' : ''}
            title="自动打开浏览器到 ${esc(c.page)} 页，剩下的自己点；点完勾右侧「通过」">打开</button>`
        : `<button class="btn btn-run" data-run="${c.id}" ${(S.busy || !canRun() || c.status === 'blocked' || c.status === 'skipped') ? 'disabled' : ''}
            title="${c.status === 'blocked' || c.status === 'skipped'
              ? esc(`[${c.status}] ${c.reason || '合法不可跑'}——不进走查面，合法性已留痕索引`)
              : (canRun() ? '' : esc(srcCfg().why || '该来源不可执行'))}">执行</button>`}
      <span style="margin-left:6px">${pill}</span>
      ${e ? `<div class="who" title="${esc(e.ts || '')} · exit=${e.exit} · slowmo ${e.slowmo || ''}">`
        + `${esc(hhmm(e.ts))} · exit=${e.exit} · ${Math.round((e.duration_ms || 0) / 1000)}s${nodeid ? '' : ' · ⚠ 无 node id'}</div>` : ''}
      ${excerpt}
      ${out ? `<button class="btn btn-ghost" data-out="${c.id}">输出</button>` : ''}
    </td>
    <td>${reviewCell}</td>
  </tr>`;
}

function detailHTML(c) {
  const li = (a) => a.map((x) => {
    const [code, note] = String(x).split('#');
    return `<li>${esc(code.trim())}${note ? ` <span class="note">#${esc(note)}</span>` : ''}</li>`;
  }).join('');
  return `<div class="detail">
    <h4>数据前提（precondition，不执行）</h4><ul>${li(c.precondition)}</ul>
    <h4>步骤（step）</h4><ul>${li(c.step)}</ul>
    <h4>预期（expected）</h4><ul>${li(c.expected)}</ul>
    <h4>testid（${c.testid.length}）</h4><ul>${c.testid.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
    <h4>分片</h4><div><code>${esc(c.shard)}</code></div>
  </div>`;
}

function rerenderRow(id) {
  const tr = document.querySelector(`tr[data-case="${id}"]`);
  if (!tr) return;
  const c = S.cases.find((x) => x.id === id);
  const tmp = document.createElement('tbody');
  tmp.innerHTML = rowHTML(c);
  tr.replaceWith(tmp.firstElementChild);
}

/* ---------------- 底部日志面板 ---------------- */
function openLog(id) {
  const c = S.cases.find((x) => x.id === id) || { id };
  const e = effective(id);
  S.logCase = id;
  $('log-title').textContent = `${id}  ${c.title || ''}`;
  $('log-meta').textContent = e ? `exit=${e.exit} · ${Math.round((e.duration_ms || 0) / 1000)}s · ${hhmm(e.ts)}` : '尚未执行';
  $('log-body').textContent = S.outputs[id] || (e && e.tail) || '（暂无输出）';
  $('log').hidden = false;
  $('log-body').scrollTop = $('log-body').scrollHeight;
}

/* ---------------- 执行（SSE；结果只进本地草稿） ---------------- */
function run(id) {
  notify('');
  const slowmo = Number($('slowmo').value || 500);
  api('api/run', { id, slowmo, source: S.source }).then((res) => {
    if (!res.ok) { notify(`未启动：${res.error}`, true); return; }
    S.busy = id;
    S.outputs[id] = '';
    // 不自动展开底部日志面板：
    // 输出照旧往里流（点该行的「输出」随时打开，刷新不丢）。
    render();
    const es = new EventSource('api/stream');
    es.onmessage = (ev) => {
      const d = JSON.parse(ev.data);
      if (d.kind === 'line') {
        S.outputs[id] = (S.outputs[id] || '') + d.text + '\n';
        rerenderRow(id);
        if (S.logCase === id) { $('log-body').textContent = S.outputs[id]; $('log-body').scrollTop = $('log-body').scrollHeight; }
      } else if (d.kind === 'done') {
        es.close();
        S.busy = null;
        S.heldCase = d.held ? id : null;
        patch(id, { ok: d.ok, exit: d.exit, duration_ms: d.duration_ms, timeout: d.timeout,
                    tail: S.outputs[id] || d.tail || '', ts: d.ts, slowmo: d.slowmo });
        render();
        // 跑完不关窗的状态已在右上角「关闭浏览器窗口（E2E-XXX）」按钮上可见，不再多弹一条提示。
        if (!d.ok) notify(`${id} 执行${d.timeout ? '超时' : '失败'}——点「输出」看回溯；问题在用例本身的话回对话改用例后重生成脚本。`, true);
      }
    };
    es.onerror = () => { es.close(); S.busy = null; render(); };
  });
}

/* ---------------- 提交 ---------------- */
function changeLines(changes) {
  return changes.map((c) =>
    `<div>${esc(c.id)}  状态 <i>${esc(c.from['状态'])}</i> → <b>${esc(c.to['状态'])}</b>`
    + `${c.note ? `  · ${esc(c.note)}` : ''}</div>`).join('');
}

async function preview() {
  if (pendingCount() === 0) { notify('没有未提交的改动（执行或勾选之后再来提交）。'); return; }
  const res = await api('api/submit', { draft: S.draft, apply: false, source: S.source });
  const k = counts();
  const summary = `<div><b>提交预览</b>（来源 ${esc(srcCfg().label || S.source)}）：账本会追加 <b>1 条快照</b>（${pendingCount()} 条用例 · 执行通过 ${k.pass}`
    + ` · 已评审 ${k.reviewed}）；索引 <code>product/e2e/e2e-index.md</code> 将改 ${res.changed} 行。</div>`;
  const body = res.changed ? `<div class="chg">${changeLines(res.changes)}</div>` : '';
  notifyHTML(summary + body
    + `<div class="wb-actions"><button class="btn btn-ok" data-wb="apply">确认提交</button>`
    + `<button class="btn" data-wb="cancel">取消</button>`
    + `<button class="btn" data-wb="drop">丢弃本地改动</button></div>`);
}

async function submitApply() {
  const res = await api('api/submit', { draft: S.draft, apply: true, source: S.source });
  notifyHTML(`<div><b>已提交</b>：账本追加 1 条快照（${pendingCount()} 条用例）；索引写入 ${res.changed} 行。</div>`
    + `<div class="chg">${changeLines(res.changes)}</div>`
    + `<div class="wb-actions"><button class="btn" data-wb="cancel">知道了</button></div>`);
  S.draft = {};
  saveDraft();
  await load();
}

/* ---------------- 事件 ---------------- */
document.addEventListener('click', (ev) => {
  const wb = ev.target.closest('[data-wb]');
  if (wb) {
    if (wb.dataset.wb === 'apply') submitApply();
    else if (wb.dataset.wb === 'drop') { dropDraft(); notify('已丢弃本地改动（账本与索引未被触碰，页面回到最近提交的状态）。'); render(); }
    else notify('');
    return;
  }
  const t = ev.target.closest('[data-run],[data-open],[data-review],[data-toggle],[data-detail],[data-out]');
  if (!t) return;
  if (t.dataset.run) run(t.dataset.run);
  else if (t.dataset.open) {
    api('api/open', { id: t.dataset.open }).then((res) => {
      notify(res.ok
        ? (res.opened ? `已在浏览器打开 ${res.url} —— 自己点完勾右侧「通过」。` : `${res.note}：${res.url}`)
        : res.error, res.ok ? false : true);
    });
  }
  else if (t.dataset.review) {
    const id = t.dataset.review;
    const prev = ((effective(id) || {}).reviewed) || {};
    patch(id, { reviewed: t.checked
      ? { pass: true, checked_at: nowISO(), unchecked_at: prev.unchecked_at || null }
      : { pass: false, checked_at: prev.checked_at || null, unchecked_at: nowISO() } });
    render();
  } else if (t.dataset.toggle) {
    const p = t.dataset.toggle;
    S.open.has(p) ? S.open.delete(p) : S.open.add(p);
    render();
  } else if (t.dataset.out) openLog(t.dataset.out);
  else if (t.dataset.detail) {
    const k = 'd:' + t.dataset.detail;
    S.open.has(k) ? S.open.delete(k) : S.open.add(k);
    rerenderRow(t.dataset.detail);
  }
});

$('log-close').onclick = () => { $('log').hidden = true; S.logCase = null; };
$('closewin').onclick = () => {
  api('api/close-window', {}).then((res) => {
    S.heldCase = null;
    render();
    notify(res.closed ? `已关闭 ${res.closed} 保留的浏览器窗口。` : '当前没有保留的浏览器窗口。');
  });
};
$('submit').onclick = () => preview();
$('reload').onclick = () => load();
for (const id of ['f-type', 'f-page']) {
  $(id).onchange = (e) => { S.filter[id.slice(2)] = e.target.value; render(); };
}
$('f-unreviewed').onchange = (e) => { S.filter.unreviewed = e.target.checked; render(); };
$('f-q').oninput = (e) => { S.filter.q = e.target.value; render(); };

loadDraft();
load();
