/* ───── state ───── */
let state = { page: 'list', projectId: null, network: null, live: false, eventSource: null };
let currentProject = null;

/* ───── routing ───── */
function navigate(page, projectId) {
  state.page = page;
  state.projectId = projectId || null;
  render();
}

/* ───── entry ───── */
document.addEventListener('DOMContentLoaded', () => {
  const hash = location.hash.slice(1) || '/';
  if (hash.startsWith('/project/')) {
    state.page = 'detail';
    state.projectId = hash.split('/')[2];
  }
  render();
});

window.addEventListener('hashchange', () => {
  const hash = location.hash.slice(1) || '/';
  if (hash.startsWith('/project/')) {
    state.page = 'detail';
    state.projectId = hash.split('/')[2];
  } else {
    state.page = 'list';
    state.projectId = null;
  }
  render();
});

/* ───── render ───── */
async function render() {
  const main = document.getElementById('main');
  const navInfo = document.getElementById('navInfo');

  if (state.page === 'list') {
    state.live = false;
    stopLive();
    if (state.network) { state.network.destroy(); state.network = null; }
    navInfo.textContent = '';
    main.innerHTML = '<div class="empty-state"><div class="icon">⏳</div><p>加载中...</p></div>';
    try {
      const projects = await api('/api/projects');
      main.innerHTML = renderProjectList(projects);
    } catch (e) {
      main.innerHTML = `<div class="empty-state"><div class="icon">⚠️</div><p>无法连接到服务器</p><p style="font-size:12px;margin-top:8px">${e.message}</p></div>`;
    }
  } else if (state.page === 'detail' && state.projectId) {
    navInfo.textContent = `项目 ${state.projectId.slice(0, 8)}`;
    main.innerHTML = `<div class="detail-layout">
      <div class="graph-panel"><div id="graph-container"></div></div>
      <div class="side-panel" id="sidePanel"></div>
    </div>`;
    await loadDetail(state.projectId);
  }
}

/* ───── project list ───── */
function renderProjectList(projects) {
  if (!projects || projects.length === 0) {
    return '<div class="empty-state"><div class="icon">📂</div><p>暂无项目</p></div>';
  }
  let cards = projects.map(p => {
    const statusBadge = p.status === 'completed' ? 'badge-completed' : p.status === 'failed' ? 'badge-failed' : 'badge-running';
    const origin = trunc(p.origin, 30);
    const goal = trunc(p.goal, 30);
    return `<div class="project-card" onclick="navigate('detail','${p.id}')">
      <div class="left">
        <div class="title">${esc(origin)} → ${esc(goal)}</div>
        <div class="meta">${p.id.slice(0, 12)} · ${fmtTime(p.updated_at)}</div>
      </div>
      <div class="right">
        <div class="stats">
          <span style="color:var(--accent)">●</span> ${p.facts}
          <span style="color:var(--orange)">◇</span> ${p.intents}
        </div>
        <span class="badge ${statusBadge}">${p.status}</span>
      </div>
    </div>`;
  }).join('');
  return `<div class="project-list"><h2>项目列表</h2><div class="project-cards">${cards}</div></div>`;
}

/* ───── detail ───── */
async function loadDetail(projectId) {
  const sidePanel = document.getElementById('sidePanel');
  sidePanel.innerHTML = '<div class="panel-header"><h3>加载中...</h3></div>';

  try {
    currentProject = await api(`/api/projects/${projectId}`);
    const graphData = await api(`/api/projects/${projectId}/graph`);
    renderSidePanel(currentProject);
    renderGraph(graphData);
    startLive(projectId);
  } catch (e) {
    sidePanel.innerHTML = `<div class="panel-header"><h3>加载失败</h3></div><div class="panel-body"><p style="padding:12px;color:var(--red)">${e.message}</p></div>`;
  }
}

function renderSidePanel(project) {
  const panel = document.getElementById('sidePanel');
  const facts = project.facts || [];
  const intents = project.intents || [];
  const openCnt = intents.filter(i => i.status === 'pending').length;

  const liveBtn = state.live
    ? `<button class="btn btn-sm btn-primary" id="liveBtn"><span class="live-dot active"></span>实时</button>`
    : `<button class="btn btn-sm" id="liveBtn"><span class="live-dot inactive"></span>实时</button>`;

  panel.innerHTML = `
    <div class="panel-header">
      <h3>Facts (${facts.length}) · Intents (${intents.length}) <span style="font-size:12px;font-weight:400;color:var(--text2)">待处理 ${openCnt}</span></h3>
      ${liveBtn}
    </div>
    <div class="panel-body" id="panelBody">
      ${facts.map((f, idx) => `
        <div class="fact-card" data-type="fact" data-idx="${idx}">
          <div class="label">● Fact</div>
          <div class="body">${esc(trunc(f.description, 160))}</div>
          <div class="meta">${esc(f.source || '未知来源')} · ${fmtTime(f.created_at)}</div>
        </div>
      `).reverse().join('')}
      ${intents.map((i, idx) => {
        const badgeCls = i.status === 'completed' ? 'badge-completed' : i.status === 'failed' ? 'badge-failed' : 'badge-pending';
        return `<div class="intent-card" data-type="intent" data-idx="${idx}">
          <div class="label">◇ Intent</div>
          <div class="body">${esc(trunc(i.description, 120))}</div>
          <div class="meta"><span class="badge ${badgeCls}">${i.status}</span> ${fmtTime(i.created_at)}</div>
        </div>`;
      }).reverse().join('')}
      ${facts.length === 0 && intents.length === 0 ? '<div class="empty-state" style="padding:30px"><p>暂无数据</p></div>' : ''}
    </div>`;

  if (!panel._delegated) {
    panel.addEventListener('click', handlePanelClick);
    panel._delegated = true;
  }
}

function handlePanelClick(e) {
  const liveBtn = e.target.closest('#liveBtn');
  if (liveBtn) {
    toggleLive();
    return;
  }
  const card = e.target.closest('[data-type]');
  if (!card) return;
  const type = card.dataset.type;
  const idx = parseInt(card.dataset.idx, 10);
  if (!currentProject) return;
  const items = type === 'fact' ? currentProject.facts : currentProject.intents;
  const raw = items ? items[idx] : null;
  if (raw) showNodeModal(type, raw);
}

/* ───── graph ───── */
function renderGraph(graphData) {
  const container = document.getElementById('graph-container');
  if (!container) return;

  if (state.network) { state.network.destroy(); state.network = null; }

  const colors = { goal: { bg: '#2ea043', bd: '#3fb950' }, origin: { bg: '#484f58', bd: '#6e7681' }, fact: { bg: '#1f6feb', bd: '#58a6ff' }, intent: { bg: '#9e6a03', bd: '#d29922' } };

  const nodes = graphData.nodes.map(n => {
    const c = colors[n.type] || colors.fact;
    const shape = n.type === 'goal' ? 'hexagon' : n.type === 'origin' ? 'ellipse' : n.type === 'fact' ? 'box' : 'diamond';
    const border = n.type === 'intent' && n.status === 'failed' ? colors.red : n.type === 'intent' && n.status === 'pending' ? undefined : c.bd;
    const dash = n.type === 'intent' && n.status === 'pending';

    const font = { color: '#c9d1d9', size: n.type === 'goal' ? 16 : 13, face: '-apple-system, sans-serif' };

    return {
      id: n.id,
      label: n.label,
      title: n.title || n.label,
      shape,
      color: { background: c.bg, border: border || c.bd },
      font,
      borderWidth: n.type === 'intent' && n.status === 'pending' ? 2 : 1,
      borderDash: dash ? [3, 3] : undefined,
      size: n.type === 'goal' ? 30 : 20,
    };
  });

  const edges = graphData.edges.map(e => ({
    from: e.from, to: e.to,
    arrows: 'to', color: { color: '#30363d', highlight: '#58a6ff' },
    width: 1, smooth: { type: 'curvedCW', roundness: 0.1 },
  }));

  const data = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    nodes: { shapeProperties: { useBorderWithImage: true } },
    edges: { smooth: { type: 'curvedCW', roundness: 0.1 } },
    physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -40, centralGravity: 0.005, springLength: 160, springConstant: 0.02, damping: 0.4 } },
    interaction: { hover: true, tooltipDelay: 200, navigationButtons: true, keyboard: true },
    layout: { improvedLayout: true },
  };

  state.network = new vis.Network(container, data, options);

  state.network.on('click', function(params) {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      const rawNode = graphData.nodes.find(n => n.id === nodeId);
      if (rawNode) showNodeModal(rawNode.type, rawNode);
    }
  });
}

/* ───── node modal ───── */
function showNodeModal(type, raw) {
  const title = typeof raw === 'string' ? raw : (raw.title || raw.description || raw.label || '');
  const detail = typeof raw === 'string' ? {} : raw;
  const typeLabel = type === 'goal' ? '目标' : type === 'origin' ? '起点' : type === 'fact' ? 'Fact' : 'Intent';

  let extraMeta = '';
  if (detail.source) extraMeta += `<div class="meta-row">来源: ${esc(detail.source)}</div>`;
  if (detail.confidence) extraMeta += `<div class="meta-row">置信度: ${detail.confidence}</div>`;
  if (detail.status) extraMeta += `<div class="meta-row">状态: ${detail.status}</div>`;
  if (detail.created_at) extraMeta += `<div class="meta-row">创建时间: ${fmtTime(detail.created_at)}</div>`;

  document.body.insertAdjacentHTML('beforeend', `
    <div class="node-modal" onclick="if(event.target===this)this.remove()">
      <div class="node-modal-content">
        <button class="node-modal-close" onclick="this.closest('.node-modal').remove()">✕</button>
        <h3 style="color:${type === 'fact' ? 'var(--accent)' : type === 'intent' ? 'var(--orange)' : 'var(--green)'}">${typeLabel}</h3>
        ${extraMeta}
        <pre>${esc(title)}</pre>
      </div>
    </div>`);
}

/* ───── live ───── */
function startLive(projectId) {
  if (!projectId) return;
  stopLive();
  if (!state.live) return;

  const es = new EventSource(`/api/projects/${projectId}/events`);
  state.eventSource = es;

  es.onmessage = function(e) {
    try {
      const payload = JSON.parse(e.data);
      if (payload.event === 'update' || payload.event === 'loop_end') {
        loadDetail(projectId);
      }
    } catch(_) {}
  };
  es.onerror = function() { setTimeout(() => startLive(projectId), 3000); };
}

function stopLive() {
  if (state.eventSource) { state.eventSource.close(); state.eventSource = null; }
}

function toggleLive() {
  state.live = !state.live;
  if (state.live) {
    startLive(state.projectId);
  } else {
    stopLive();
  }
  if (state.projectId) renderSidePanel(currentProject);
}

/* ───── helpers ───── */
async function api(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json();
}

function esc(s) {
  if (typeof s !== 'string') return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function trunc(s, max) {
  if (!s) return '';
  return s.length > max ? s.slice(0, max) + '…' : s;
}

function fmtTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  } catch(_) { return iso; }
}

function reloadDetail() {
  if (state.projectId) loadDetail(state.projectId);
}
