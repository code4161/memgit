"""Graph builder and HTML visualizer for memgit memory stores."""

from __future__ import annotations
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Mnemonic, Checkpoint
    from .repo import Repository

_TYPE_COLOR = {
    "fb": "#f97316",  # orange   — feedback
    "us": "#3b82f6",  # blue     — user
    "pj": "#10b981",  # teal     — project
    "rf": "#8b5cf6",  # violet   — reference
    "cn": "#eab308",  # yellow   — convention
    "lx": "#ec4899",  # pink     — lesson
}
_TYPE_LABEL = {
    "fb": "feedback",
    "us": "user",
    "pj": "project",
    "rf": "reference",
    "cn": "convention",
    "lx": "lesson",
}

_WIKILINK_RE = re.compile(r'\[\[([a-z0-9_-]+)\]\]', re.IGNORECASE)


def _extract_edges(mnemonics: list["Mnemonic"]) -> list[dict]:
    slug_set = {m.slug for m in mnemonics}
    edges = []
    seen = set()
    for m in mnemonics:
        # Explicit links
        for ref in m.related:
            if ref in slug_set:
                key = (m.slug, ref, "related")
                if key not in seen:
                    edges.append({"source": m.slug, "target": ref, "type": "related"})
                    seen.add(key)
        for ref in m.supersedes:
            if ref in slug_set:
                key = (m.slug, ref, "supersedes")
                if key not in seen:
                    edges.append({"source": m.slug, "target": ref, "type": "supersedes"})
                    seen.add(key)
        # Implicit [[wikilink]] refs in text fields
        text = " ".join(filter(None, [m.rule, m.why, m.when, m.desc]))
        for ref in _WIKILINK_RE.findall(text):
            if ref in slug_set and ref != m.slug:
                key = (m.slug, ref, "ref")
                if key not in seen:
                    edges.append({"source": m.slug, "target": ref, "type": "ref"})
                    seen.add(key)
    return edges


def build_graph_data(repo: "Repository") -> dict:
    mnemonics = repo.list()
    checkpoints = repo.log(limit=20)

    nodes = []
    for m in mnemonics:
        rule_preview = m.rule[:120] + "…" if len(m.rule) > 120 else m.rule
        nodes.append({
            "id": m.slug,
            "type": m.type_code,
            "priority": m.priority,
            "rule": rule_preview,
            "tags": m.tags,
            "color": _TYPE_COLOR.get(m.type_code, "#94a3b8"),
            "type_label": _TYPE_LABEL.get(m.type_code, m.type_code),
        })

    edges = _extract_edges(mnemonics)

    ck_list = []
    for ck in checkpoints:
        d = ck.diff_summary
        ck_list.append({
            "sha": ck.sha[:8] if ck.sha else "?",
            "message": ck.message,
            "date": ck.timestamp.strftime("%Y-%m-%d %H:%M"),
            "trigger": ck.trigger,
            "added": len(d.added) if d else 0,
            "modified": len(d.modified) if d else 0,
            "removed": len(d.removed) if d else 0,
        })

    type_counts: dict[str, int] = {}
    for m in mnemonics:
        type_counts[m.type_code] = type_counts.get(m.type_code, 0) + 1

    thread = repo.current_thread()
    head = repo.head_sha()

    return {
        "nodes": nodes,
        "edges": edges,
        "checkpoints": ck_list,
        "type_counts": type_counts,
        "type_colors": _TYPE_COLOR,
        "type_labels": _TYPE_LABEL,
        "meta": {
            "thread": thread,
            "head": head[:8] if head else "?",
            "total": len(mnemonics),
            "edge_count": len(edges),
        },
    }


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>memgit graph — {thread} / {head}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'SF Mono', 'Fira Code', monospace; background: #0f1117; color: #e2e8f0; height: 100vh; display: flex; flex-direction: column; }

  #header { padding: 10px 16px; border-bottom: 1px solid #1e293b; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  #header h1 { font-size: 14px; font-weight: 600; color: #38bdf8; letter-spacing: 0.05em; }
  #header .meta { font-size: 11px; color: #64748b; }
  #header .badge { background: #1e293b; border: 1px solid #334155; border-radius: 4px; padding: 2px 8px; font-size: 11px; color: #94a3b8; }

  #main { display: flex; flex: 1; overflow: hidden; }

  #sidebar { width: 240px; flex-shrink: 0; border-right: 1px solid #1e293b; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 14px; }
  #sidebar h2 { font-size: 10px; font-weight: 600; letter-spacing: 0.1em; color: #475569; text-transform: uppercase; margin-bottom: 6px; }

  .filter-btn { display: flex; align-items: center; gap: 6px; padding: 5px 8px; border-radius: 5px; border: 1px solid #1e293b; background: #1e293b; cursor: pointer; font-size: 11px; font-family: inherit; color: #94a3b8; width: 100%; text-align: left; transition: all 0.15s; }
  .filter-btn .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .filter-btn .count { margin-left: auto; color: #475569; }
  .filter-btn.active { border-color: currentColor; color: #e2e8f0; background: #0f172a; }
  .filter-btn:hover { border-color: #334155; }

  #stats-list { list-style: none; }
  #stats-list li { display: flex; justify-content: space-between; font-size: 11px; padding: 3px 0; border-bottom: 1px solid #1e293b; color: #94a3b8; }
  #stats-list li span:last-child { color: #e2e8f0; font-weight: 600; }

  .ck-entry { background: #1e293b; border-radius: 6px; padding: 7px 9px; margin-bottom: 6px; border-left: 3px solid #334155; }
  .ck-sha { font-size: 11px; color: #fbbf24; font-weight: 600; }
  .ck-msg { font-size: 11px; color: #94a3b8; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ck-date { font-size: 10px; color: #475569; margin-top: 2px; }
  .ck-delta { font-size: 10px; margin-top: 3px; display: flex; gap: 6px; }
  .ck-add { color: #34d399; }
  .ck-mod { color: #fbbf24; }
  .ck-del { color: #f87171; }

  #canvas-wrap { flex: 1; position: relative; overflow: hidden; }
  #canvas-wrap svg { width: 100%; height: 100%; }

  #tooltip { position: absolute; background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px 13px; font-size: 11px; max-width: 280px; pointer-events: none; display: none; z-index: 100; box-shadow: 0 8px 24px rgba(0,0,0,0.5); }
  #tooltip .t-slug { font-weight: 700; color: #38bdf8; font-size: 12px; margin-bottom: 4px; }
  #tooltip .t-type { font-size: 10px; color: #64748b; margin-bottom: 6px; }
  #tooltip .t-rule { color: #cbd5e1; line-height: 1.5; }
  #tooltip .t-tags { margin-top: 6px; color: #64748b; font-size: 10px; }

  #search-wrap { padding: 10px; border-bottom: 1px solid #1e293b; flex-shrink: 0; }
  #search { width: 100%; background: #1e293b; border: 1px solid #334155; border-radius: 5px; padding: 6px 10px; color: #e2e8f0; font-family: inherit; font-size: 12px; outline: none; }
  #search:focus { border-color: #38bdf8; }
  #search::placeholder { color: #475569; }

  .node circle { cursor: pointer; stroke-width: 1.5px; }
  .node text { font-size: 9px; fill: #94a3b8; pointer-events: none; font-family: 'SF Mono', monospace; }
  .node.highlighted circle { stroke: #fff; stroke-width: 2.5px; }
  .node.dimmed circle { opacity: 0.15; }
  .node.dimmed text { opacity: 0.1; }

  .link { stroke-opacity: 0.4; }
  .link.related { stroke: #22d3ee; stroke-dasharray: 0; }
  .link.supersedes { stroke: #f87171; stroke-dasharray: 4 2; }
  .link.ref { stroke: #64748b; stroke-dasharray: 0; }
  .link.dimmed { stroke-opacity: 0.05; }

  #legend { position: absolute; bottom: 12px; right: 12px; background: rgba(15,17,23,0.9); border: 1px solid #1e293b; border-radius: 8px; padding: 10px 12px; font-size: 10px; color: #64748b; }
  #legend div { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
  #legend .ldot { width: 8px; height: 8px; border-radius: 50%; }
  #legend .lline { width: 20px; height: 2px; }
  #legend .lref { border-top: 2px solid #64748b; }
  #legend .lrelated { border-top: 2px solid #22d3ee; }
  #legend .lsupersedes { border-top: 2px dashed #f87171; }
</style>
</head>
<body>

<div id="header">
  <h1>memgit graph</h1>
  <span class="badge">thread: {thread}</span>
  <span class="badge">HEAD: {head}</span>
  <span class="meta" id="vis-count"></span>
</div>

<div id="main">
  <div id="sidebar">
    <div>
      <h2>Filter by type</h2>
      <div id="filter-btns"></div>
    </div>
    <div>
      <h2>Stats</h2>
      <ul id="stats-list"></ul>
    </div>
    <div>
      <h2>Checkpoints</h2>
      <div id="ck-list"></div>
    </div>
  </div>

  <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
    <div id="search-wrap">
      <input id="search" type="text" placeholder="Search memories…">
    </div>
    <div id="canvas-wrap">
      <svg id="graph"></svg>
      <div id="tooltip"></div>
      <div id="legend">
        <div><span style="color:#94a3b8;font-size:10px;font-weight:600">Node size = priority</span></div>
        <div><span class="lline lref"></span> wikilink ref</div>
        <div><span class="lline lrelated"></span> related</div>
        <div><span class="lline lsupersedes"></span> supersedes</div>
      </div>
    </div>
  </div>
</div>

<script>
const DATA = __GRAPH_DATA__;

const TYPE_LABELS = DATA.type_labels;
const TYPE_COLORS = DATA.type_colors;
const nodes = DATA.nodes;
const edges = DATA.edges;
const checkpoints = DATA.checkpoints;
const typeCounts = DATA.type_counts;
const meta = DATA.meta;

// ── Sidebar: filters ─────────────────────────────────────────────────────────

document.getElementById('vis-count').textContent =
  `${meta.total} memories · ${meta.edge_count} links`;

const filterBtns = document.getElementById('filter-btns');
let activeTypes = new Set(Object.keys(typeCounts));

Object.entries(typeCounts).sort((a,b) => b[1]-a[1]).forEach(([tc, cnt]) => {
  const btn = document.createElement('button');
  btn.className = 'filter-btn active';
  btn.dataset.type = tc;
  const col = TYPE_COLORS[tc] || '#94a3b8';
  btn.innerHTML = `<span class="dot" style="background:${col}"></span>${TYPE_LABELS[tc]||tc}<span class="count">${cnt}</span>`;
  btn.style.color = col;
  btn.addEventListener('click', () => {
    if (activeTypes.has(tc)) {
      if (activeTypes.size === 1) return;
      activeTypes.delete(tc);
      btn.classList.remove('active');
    } else {
      activeTypes.add(tc);
      btn.classList.add('active');
    }
    updateVisibility();
  });
  filterBtns.appendChild(btn);
});

// ── Sidebar: stats ────────────────────────────────────────────────────────────

const statsList = document.getElementById('stats-list');
[
  ['Memories', meta.total],
  ['Links', meta.edge_count],
  ['Types', Object.keys(typeCounts).length],
  ['Checkpoints', checkpoints.length],
].forEach(([k, v]) => {
  statsList.innerHTML += `<li><span>${k}</span><span>${v}</span></li>`;
});

// ── Sidebar: checkpoints ──────────────────────────────────────────────────────

const ckList = document.getElementById('ck-list');
checkpoints.forEach(ck => {
  const div = document.createElement('div');
  div.className = 'ck-entry';
  const delta = [
    ck.added   ? `<span class="ck-add">+${ck.added}</span>` : '',
    ck.modified? `<span class="ck-mod">~${ck.modified}</span>` : '',
    ck.removed ? `<span class="ck-del">-${ck.removed}</span>` : '',
  ].filter(Boolean).join('');
  div.innerHTML = `
    <div class="ck-sha">${ck.sha}</div>
    <div class="ck-msg">${ck.message}</div>
    <div class="ck-date">${ck.date} · ${ck.trigger}</div>
    ${delta ? `<div class="ck-delta">${delta}</div>` : ''}
  `;
  ckList.appendChild(div);
});

// ── D3 Graph ──────────────────────────────────────────────────────────────────

const svg = d3.select('#graph');
const wrap = document.getElementById('canvas-wrap');

let W = wrap.clientWidth, H = wrap.clientHeight;

const g = svg.append('g');

svg.call(d3.zoom()
  .scaleExtent([0.1, 4])
  .on('zoom', e => g.attr('transform', e.transform))
);

const priorityRadius = { 1: 5, 2: 8, 3: 13 };

const sim = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(edges).id(d => d.id).distance(80).strength(0.4))
  .force('charge', d3.forceManyBody().strength(-120))
  .force('center', d3.forceCenter(W / 2, H / 2))
  .force('collision', d3.forceCollide().radius(d => (priorityRadius[d.priority] || 8) + 4));

const link = g.append('g').attr('class', 'links')
  .selectAll('line')
  .data(edges)
  .enter().append('line')
  .attr('class', d => `link ${d.type}`);

const node = g.append('g').attr('class', 'nodes')
  .selectAll('g')
  .data(nodes)
  .enter().append('g')
  .attr('class', 'node')
  .call(d3.drag()
    .on('start', dragstart)
    .on('drag', dragged)
    .on('end', dragend)
  );

node.append('circle')
  .attr('r', d => priorityRadius[d.priority] || 8)
  .attr('fill', d => d.color)
  .attr('stroke', d => d.color)
  .attr('fill-opacity', 0.85);

node.append('text')
  .attr('dy', d => (priorityRadius[d.priority] || 8) + 10)
  .attr('text-anchor', 'middle')
  .text(d => d.id.length > 18 ? d.id.slice(0, 17) + '…' : d.id);

sim.on('tick', () => {
  link
    .attr('x1', d => d.source.x)
    .attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x)
    .attr('y2', d => d.target.y);
  node.attr('transform', d => `translate(${d.x},${d.y})`);
});

// Resize
window.addEventListener('resize', () => {
  W = wrap.clientWidth; H = wrap.clientHeight;
  sim.force('center', d3.forceCenter(W / 2, H / 2)).alpha(0.1).restart();
});

// Tooltip
const tooltip = document.getElementById('tooltip');

node.on('mouseover', (event, d) => {
  const tags = d.tags.filter(t => !['fb','pj','us','rf','cn','lx'].includes(t));
  tooltip.innerHTML = `
    <div class="t-slug">${d.id}</div>
    <div class="t-type">[${d.type}] ${d.type_label} · priority ${d.priority}</div>
    <div class="t-rule">${d.rule}</div>
    ${tags.length ? `<div class="t-tags">tags: ${tags.join(', ')}</div>` : ''}
  `;
  tooltip.style.display = 'block';
  moveTooltip(event);
})
.on('mousemove', moveTooltip)
.on('mouseout', () => { tooltip.style.display = 'none'; });

function moveTooltip(event) {
  const rect = wrap.getBoundingClientRect();
  let x = event.clientX - rect.left + 14;
  let y = event.clientY - rect.top + 14;
  if (x + 290 > W) x -= 300;
  if (y + 150 > H) y -= 160;
  tooltip.style.left = x + 'px';
  tooltip.style.top = y + 'px';
}

// Click to highlight neighbours
const edgeSet = new Map();
edges.forEach(e => {
  const src = typeof e.source === 'object' ? e.source.id : e.source;
  const tgt = typeof e.target === 'object' ? e.target.id : e.target;
  if (!edgeSet.has(src)) edgeSet.set(src, new Set());
  if (!edgeSet.has(tgt)) edgeSet.set(tgt, new Set());
  edgeSet.get(src).add(tgt);
  edgeSet.get(tgt).add(src);
});

let selected = null;

node.on('click', (event, d) => {
  event.stopPropagation();
  if (selected === d.id) {
    selected = null;
    node.classed('highlighted', false).classed('dimmed', false);
    link.classed('dimmed', false);
    return;
  }
  selected = d.id;
  const neighbours = edgeSet.get(d.id) || new Set();
  node.classed('highlighted', n => n.id === d.id || neighbours.has(n.id));
  node.classed('dimmed', n => n.id !== d.id && !neighbours.has(n.id));
  link.classed('dimmed', l => {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    return src !== d.id && tgt !== d.id;
  });
});

svg.on('click', () => {
  selected = null;
  node.classed('highlighted', false).classed('dimmed', false);
  link.classed('dimmed', false);
});

// Search
const searchInput = document.getElementById('search');
searchInput.addEventListener('input', () => {
  const q = searchInput.value.trim().toLowerCase();
  if (!q) {
    node.classed('highlighted', false).classed('dimmed', false);
    link.classed('dimmed', false);
    return;
  }
  const matches = new Set(
    nodes.filter(n => n.id.includes(q) || n.rule.toLowerCase().includes(q) || n.tags.some(t => t.includes(q)))
       .map(n => n.id)
  );
  node.classed('highlighted', n => matches.has(n.id));
  node.classed('dimmed', n => !matches.has(n.id));
  link.classed('dimmed', l => {
    const src = typeof l.source === 'object' ? l.source.id : l.source;
    const tgt = typeof l.target === 'object' ? l.target.id : l.target;
    return !matches.has(src) && !matches.has(tgt);
  });
});

// Type filter → show/hide nodes
function updateVisibility() {
  node.style('display', d => activeTypes.has(d.type) ? null : 'none');
  link.style('display', l => {
    const src = typeof l.source === 'object' ? l.source : nodes.find(n=>n.id===l.source);
    const tgt = typeof l.target === 'object' ? l.target : nodes.find(n=>n.id===l.target);
    return (src && activeTypes.has(src.type) && tgt && activeTypes.has(tgt.type)) ? null : 'none';
  });
  const visible = nodes.filter(n => activeTypes.has(n.type)).length;
  document.getElementById('vis-count').textContent =
    `${visible}/${meta.total} memories · ${meta.edge_count} links`;
}

// Drag helpers
function dragstart(event, d) { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(event, d)   { d.fx = event.x; d.fy = event.y; }
function dragend(event, d)   { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }
</script>
</body>
</html>
"""


def render_html(data: dict) -> str:
    html = _HTML_TEMPLATE
    html = html.replace("{thread}", data["meta"]["thread"])
    html = html.replace("{head}", data["meta"]["head"])
    html = html.replace("__GRAPH_DATA__", json.dumps(data, ensure_ascii=False))
    return html
