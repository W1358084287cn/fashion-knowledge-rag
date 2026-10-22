const PROJECT_NAMES = {
  rag: '服装多源资料智能问答',
  xct: '乡策通 · 助农政策平台',
  ouc: 'OUC 智慧食堂 · 扫码点餐',
  fall: '老人防摔监护系统'
};
const EVENT_LABELS = {
  page_view: '打开首页',
  project_view: '查看项目',
  click: '打开链接'
};
const END_LABELS = { client: '客户端', admin: '管理端', video: '演示视频' };

let timer = null;
let lastData = null;

function esc(text) {
  return String(text == null ? '' : text).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function statCard(label, value, note) {
  return `
    <div class="stat">
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${esc(value)}</div>
      <div class="stat-note">${esc(note)}</div>
    </div>`;
}

function rankPanel(projects) {
  const max = Math.max(1, ...projects.map((p) => p.total));
  const rows = projects.map((p) => {
    const width = Math.max(4, Math.round((p.total / max) * 100));
    return `
      <div class="rank-row">
        <span class="rank-name">${esc(PROJECT_NAMES[p.project] || p.project)}</span>
        <span class="rank-total">${p.total} 次</span>
        <div class="rank-track"><div class="rank-fill" style="width:${width}%"></div></div>
        <span class="rank-note">客户端 ${p.client} · 管理端 ${p.admin}${p.video ? ` · 视频 ${p.video}` : ''}</span>
      </div>`;
  }).join('');
  return `
    <div class="panel">
      <h2 class="panel-title">项目点击排行 <span>按「直接访问」按钮统计</span></h2>
      ${projects.some((p) => p.total > 0) ? rows : '<div class="empty">还没有人点击项目链接</div>'}
    </div>`;
}

function chartPanel(daily) {
  const max = Math.max(1, ...daily.map((d) => d.views));
  const today = daily[daily.length - 1] ? daily[daily.length - 1].date : '';
  const cols = daily.map((d) => {
    const height = Math.max(3, Math.round((d.views / max) * 82));
    return `
      <div class="chart-col">
        <span class="chart-count">${d.views}</span>
        <div class="chart-bar${d.date === today ? ' today' : ''}" style="height:${height}px"></div>
        <span class="chart-label">${esc(d.date.slice(5))}</span>
      </div>`;
  }).join('');
  return `
    <div class="panel">
      <h2 class="panel-title">近 7 天访问 <span>页面浏览次数</span></h2>
      <div class="chart">${cols}</div>
    </div>`;
}

function eventsPanel(events) {
  const rows = events.map((e) => `
    <tr>
      <td class="dim">${esc(e.ts.slice(5))}</td>
      <td>${esc(EVENT_LABELS[e.event] || e.event)}</td>
      <td>${esc(PROJECT_NAMES[e.project] || '—')}</td>
      <td class="dim">${esc(END_LABELS[e.endpoint] || '—')}</td>
      <td class="dim">${e.device === 'mobile' ? '手机' : '电脑'}</td>
      <td class="dim">${esc(e.ip)}</td>
    </tr>`).join('');
  return `
    <div class="panel">
      <h2 class="panel-title">最近访问明细 <span>最新 60 条</span></h2>
      <div class="table-scroll">
        <table>
          <thead><tr><th>时间</th><th>动作</th><th>项目</th><th>端</th><th>设备</th><th>IP</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6" class="empty">暂无访问记录</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function opsPanel(ops) {
  const rows = ops.map((o) => `
    <tr>
      <td class="dim">${esc(o.ts.slice(5))}</td>
      <td>${esc(o.action)}</td>
      <td class="dim">${esc(o.ip)}</td>
      <td class="dim">${esc(o.detail)}</td>
    </tr>`).join('');
  return `
    <div class="panel">
      <h2 class="panel-title">操作日志 <span>后台访问记录</span></h2>
      <div class="table-scroll">
        <table>
          <thead><tr><th>时间</th><th>操作</th><th>IP</th><th>详情</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="4" class="empty">暂无操作记录</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function renderDashboard(data) {
  document.getElementById('admin').innerHTML = `
    <div class="wrap">
      <div class="admin-head">
        <div>
          <h1>访问统计</h1>
          <p>演示页与项目链接的访问情况 · 每 20 秒自动刷新</p>
        </div>
        <div style="display:flex;gap:8px;flex:none;">
          <button class="btn-ghost" id="refresh-btn" type="button">刷新</button>
        </div>
      </div>
      <div class="stat-grid">
        ${statCard('今日访问', data.todayPv, `今日独立访客 ${data.todayUv} 人`)}
        ${statCard('累计访问', data.pv, `独立访客 ${data.uv} 人`)}
        ${statCard('链接点击', data.clicks, `今日 ${data.todayClicks} 次`)}
        ${statCard('手机 / 电脑', `${data.devices[0].count} / ${data.devices[1].count}`, '按访问设备统计')}
      </div>
      ${rankPanel(data.projects)}
      ${chartPanel(data.daily)}
      ${eventsPanel(data.events)}
      ${opsPanel(data.ops)}
      <div class="admin-foot">数据保存在服务器本地，仅用于项目演示统计 · 王浩源</div>
    </div>`;

  document.getElementById('refresh-btn').addEventListener('click', load);
}

function renderError(message) {
  document.getElementById('admin').innerHTML = `
    <div class="wrap">
      <div class="admin-head">
        <div>
          <h1>访问统计</h1>
          <p>暂时没能读取到数据</p>
        </div>
        <button class="btn-ghost" id="retry-btn" type="button">重试</button>
      </div>
      <div class="panel"><div class="empty">${esc(message)}</div></div>
    </div>`;
  document.getElementById('retry-btn').addEventListener('click', load);
}

async function load() {
  try {
    const resp = await fetch('/api/stats', { cache: 'no-store' });
    const data = await resp.json();
    if (data.code !== 0) throw new Error(data.msg || '读取失败');
    lastData = data.data;
    renderDashboard(lastData);
    if (!timer) timer = setInterval(load, 20000);
  } catch (err) {
    renderError(err.message === 'Failed to fetch' ? '网络异常，请检查网络后重试' : err.message);
  }
}

load();
