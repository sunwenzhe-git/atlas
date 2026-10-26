#!/usr/bin/env node
/* atlas-map.html 七项断言检查器(2026-10-25 落盘,防每会话重建口径漂移;2026-10-26 升:
   7 连线共道——两边的共线段重叠会让并行流看不出谁是哪条,apply 子图曾四线并一)
   断言:节点重叠 / 连线穿卡 / 标签牌互撞 / 标签牌压卡 / 标签牌越界 / 分区标签压卡
   数据与几何函数直接从 atlas-map.html 抽取求值,不复制坐标,防双源漂移。
   口径:连线穿卡只判非首尾卡(端点按边界贴合设计);其余五项全量。
   用法:node docs/map/atlas-map.check.js  → 违例退出码 1
   配套:系统 Chrome headless --headless=new --window-size=1440,778 --screenshot
   (注意 headless=new 的 innerHeight 比 --window-size 恒小 87px) */
const fs = require('fs');
const path = require('path');
const HTML = path.join(__dirname, 'atlas-map.html');
const html = fs.readFileSync(HTML, 'utf8');
const s = html.indexOf('const KIND');
const e = html.indexOf('/* 渲染一张拓扑图');
if (s < 0 || e < 0 || e <= s) { console.error('从 HTML 抽取数据失败'); process.exit(2); }
const fns = new Function(html.slice(s, e) + '\n;return {VIEWS,NW,NH,nbox,edgePath};')();
const { VIEWS, NW, NH, nbox, edgePath } = fns;

const EPS = 1;
function hit(a, b) { // 两矩形各向内缩 EPS 后是否相交
  return a.x + EPS < b.x + b.w - EPS && b.x + EPS < a.x + a.w - EPS &&
         a.y + EPS < b.y + b.h - EPS && b.y + EPS < a.y + a.h - EPS;
}
function pathPts(d) {
  const t = d.match(/[MHV]|-?\d+(?:\.\d+)?/g); const pts = []; let i = 0, x = 0, y = 0;
  while (i < t.length) {
    const c = t[i++];
    if (c === 'M') { x = +t[i++]; y = +t[i++]; } else if (c === 'H') { x = +t[i++]; } else { y = +t[i++]; }
    pts.push([x, y]);
  }
  return pts;
}
function sample(pts, step = 2) {
  const out = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    const n = Math.max(1, Math.ceil(Math.hypot(x2 - x1, y2 - y1) / step));
    for (let k = 0; k <= n; k++) out.push([x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n]);
  }
  return out;
}
function inRect(p, r) { return p[0] > r.x + 2 && p[0] < r.x + r.w - 2 && p[1] > r.y + 2 && p[1] < r.y + r.h - 2; }
function strW(s2, fs2, ls) { let w = 0; for (const ch of s2) w += (ch.charCodeAt(0) > 0x2e80 ? fs2 : fs2 * .55) + ls; return w; }
function labelRects(v) { // 与 renderMap 内标签牌落位逻辑逐字一致
  const out = [];
  for (const ed of v.edges) {
    if (!ed.label) continue;
    const a = nbox(v, ed.from), b = nbox(v, ed.to), tw = ed.label.length * 12 + 12;
    let lx, ly;
    if (ed.route === 'v') { lx = a.x + a.w / 2 + 4; ly = a.y + a.h + 12; }
    else if (!ed.route && Math.abs(b.x - a.x) < 20) { const mx = (a.x + b.x + b.w) / 2, my = (a.y + b.y + NH) / 2; lx = mx - tw / 2; ly = my + 2; }
    else { lx = a.x + a.w + 4; ly = a.y + a.h / 2 - 9; if (lx + tw > v.vb[0] + v.vb[2] - 4) lx = a.x - tw - 6; }
    out.push({ id: ed.from + '→' + ed.to + '「' + ed.label + '」', x: lx, y: ly - 11, w: tw, h: 17 });
  }
  return out;
}
function zoneLabelRects(v) {
  return v.zones.map(z => {
    const y = v.zoneLabIn ? z.y + 20 : z.y - 9;
    return { id: '分区「' + z.label + '」', x: z.x + 10, y: y - 10.5, w: strW(z.label, 11.5, 1.5) + 4, h: 14 };
  });
}
let total = 0;
for (const vid in VIEWS) {
  const v = VIEWS[vid];
  const nodes = v.nodes.map(n => ({ key: n.id, id: n.title, x: n.x, y: n.y, w: NW, h: NH }));
  const labels = labelRects(v);
  const zlabels = zoneLabelRects(v);
  const bad = [];
  // 1 节点重叠
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++)
    if (hit(nodes[i], nodes[j])) bad.push(['节点重叠', nodes[i].id + ' × ' + nodes[j].id]);
  // 2 连线穿卡(只判非首尾卡)
  for (const ed of v.edges) {
    const pts = sample(pathPts(edgePath(v, ed)));
    for (const nd of nodes) {
      if (nd.key === ed.from || nd.key === ed.to) continue;
      if (pts.some(p => inRect(p, nd))) bad.push(['连线穿卡', ed.from + '→' + ed.to + ' 穿过 ' + nd.id]);
    }
  }
  // 3 标签牌互撞
  for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++)
    if (hit(labels[i], labels[j])) bad.push(['标签牌互撞', labels[i].id + ' × ' + labels[j].id]);
  // 4 标签牌压卡
  for (const L of labels) for (const nd of nodes)
    if (hit(L, nd)) bad.push(['标签牌压卡', L.id + ' 压 ' + nd.id]);
  // 5 标签牌越界(vb 四元组 [x,y,w,h])
  for (const L of labels)
    if (L.x < v.vb[0] - 1 || L.y < v.vb[1] - 1 || L.x + L.w > v.vb[0] + v.vb[2] + 1 || L.y + L.h > v.vb[1] + v.vb[3] + 1)
      bad.push(['标签牌越界', L.id + ' rect=' + [L.x, L.y, L.w, L.h].join(',') + ' vb=' + v.vb]);
  // 6 分区标签压卡
  for (const Z of zlabels) for (const nd of nodes)
    if (hit(Z, nd)) bad.push(['分区标签压卡', Z.id + ' 压 ' + nd.id]);
  // 7 连线共道:竖/横共线段重叠 >6px(允许同一 x/y 的相接与垂直交叉,禁的是看不出是两条线的并行重合)
  {
    const segs = v.edges.map(ed => {
      const pts = pathPts(edgePath(v, ed)); const out = [];
      for (let i = 0; i + 1 < pts.length; i++) out.push({ id: ed.from + '→' + ed.to, a: pts[i], b: pts[i + 1] });
      return out;
    }).flat();
    for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
      const s1 = segs[i], s2 = segs[j];
      if (s1.id === s2.id) continue;
      let overlap = 0;
      if (s1.a[1] === s1.b[1] && s2.a[1] === s2.b[1] && s1.a[1] === s2.a[1]) {          // 同 y 横线
        const lo = Math.max(Math.min(s1.a[0], s1.b[0]), Math.min(s2.a[0], s2.b[0]));
        const hi = Math.min(Math.max(s1.a[0], s1.b[0]), Math.max(s2.a[0], s2.b[0]));
        overlap = hi - lo;
      } else if (s1.a[0] === s1.b[0] && s2.a[0] === s2.b[0] && s1.a[0] === s2.a[0]) {   // 同 x 竖线
        const lo = Math.max(Math.min(s1.a[1], s1.b[1]), Math.min(s2.a[1], s2.b[1]));
        const hi = Math.min(Math.max(s1.a[1], s1.b[1]), Math.max(s2.a[1], s2.b[1]));
        overlap = hi - lo;
      }
      if (overlap > 6) bad.push(['连线共道', s1.id + ' × ' + s2.id + ' 重叠 ' + overlap.toFixed(0) + 'px']);
    }
  }
  console.log('== ' + vid + ' vb=' + v.vb + ' ==');
  if (bad.length) { total += bad.length; bad.forEach(b => console.log('  ✗ ' + b[0] + ': ' + b[1])); }
  else console.log('  七项断言全过');
}
console.log(total ? ('共 ' + total + ' 处违例') : '全部视图七项断言通过');
process.exit(total ? 1 : 0);
