const PROJECTS = [
  {
    id: 'rag',
    no: '01',
    type: 'AI · RAG',
    name: '服装多源资料智能问答系统',
    desc: '把 Word、Excel、PPT、PDF、扫描件、SQL 等分散资料，自动整理成「能问答」的知识库；提问时同时查相近段落与实体关系，查不到就明确说不知道，不编造。',
    tags: ['6 类资料导入', '双引擎检索', '自动召回自测', '可视化运维'],
    ends: [
      {
        key: 'client',
        label: '客户端',
        env: '手机 H5 端',
        envClass: 'h5',
        desc: '直接提问，查看回答与引用来源，手机浏览器即可使用。',
        account: '演示账号 demo / 123456（已预填，直接登录）',
        url: 'http://49.232.131.254:3002/'
      },
      {
        key: 'admin',
        label: '管理端',
        env: 'PC 电脑端',
        envClass: 'pc',
        desc: '知识库上传、切片与召回测试、向量库与知识图谱、检索与操作日志。',
        account: '管理员 admin / 123456（已预填）',
        url: 'http://49.232.131.254:3002/admin'
      }
    ]
  },
  {
    id: 'xct',
    no: '02',
    type: '全栈 · 政策平台',
    name: '乡策通 · 助农扶持政策平台',
    desc: '村民用大白话提问，系统先检索政策原文再生成回答；支持在线提交补贴申请，走村级、镇级多级审批，四类角色各看各的数据。',
    tags: ['RAG 政策问答', '多级审批', '四角色权限', 'PC + H5'],
    ends: [
      {
        key: 'client',
        label: '客户端 · 村民端',
        env: '手机 H5 端',
        envClass: 'h5',
        desc: '自然语言提问政策，查看补贴申请入口与办理进度。',
        account: '演示账号 15632489079 / 123456（已预填）',
        url: 'http://49.232.131.254/'
      },
      {
        key: 'admin',
        label: '管理端 · 统一后台',
        env: 'PC 电脑端',
        envClass: 'pc',
        desc: '政策维护、补贴审批、用户与角色管理（系统管理员 / 村管 / 镇管）。',
        account: 'admin / 123456，登录时必须选择对应角色',
        url: 'http://49.232.131.254/admin/'
      }
    ]
  },
  {
    id: 'ouc',
    no: '03',
    type: '全栈 · 点餐系统',
    name: 'OUC 智慧食堂 · 扫码点餐',
    desc: '扫桌上二维码点餐，同桌可共用一辆购物车拼单；覆盖下单、后厨接单、叫号取餐、退款与营收统计的完整流程。',
    tags: ['扫码点餐', '共享购物车', '后厨叫号', '退款与营收'],
    ends: [
      {
        key: 'client',
        label: '客户端 · 顾客点餐',
        env: '手机 H5 端',
        envClass: 'h5',
        desc: '扫码进入、选菜下单、同桌拼单、查看订单与申请退款。',
        account: '演示环境无需填写账号，直接点击登录',
        url: 'http://49.232.131.254:8090/front/index.html'
      },
      {
        key: 'admin',
        label: '管理端 · 商家后台',
        env: 'PC 电脑端',
        envClass: 'pc',
        desc: '菜品与套餐、订单与后厨、退款审核、营收统计，新单与退款有语音提醒。',
        account: '商家账号 admin / 123456（已预填）',
        url: 'http://49.232.131.254:8090/backend/index.html'
      }
    ]
  },
  {
    id: 'fall',
    no: '04',
    type: '物联网 · 硬件',
    name: '老人防摔监护系统',
    desc: '用传感器实时监测老人姿态，识别到跌倒立即触发告警；负责传感器与主控电路搭建、检测与告警程序编写、整机联调，获市赛奖项。',
    tags: ['姿态识别', '跌倒告警', '电路搭建', '整机联调'],
    video: {
      url: '/media/elder-fall.mp4',
      poster: '/media/elder-fall.jpg',
      note: '实机演示 · 约 1 分 23 秒，建议打开声音'
    },
    ends: []
  }
];

const PROJECT_MAP = new Map(PROJECTS.map((p) => [p.id, p]));

function track(event, project, endpoint) {
  const payload = JSON.stringify({
    event,
    project: project || '',
    endpoint: endpoint || ''
  });
  const url = '/api/track';
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url, new Blob([payload], { type: 'application/json' }));
  } else {
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true
    }).catch(() => {});
  }
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function homeView() {
  const cards = PROJECTS.map((p) => `
    <a class="project" href="#/p/${p.id}">
      <div class="p-top">
        <span class="p-no">PROJECT ${p.no}</span>
        <span class="p-type">${esc(p.type)}</span>
      </div>
      <h2 class="p-title">${esc(p.name)}</h2>
      <p class="p-desc">${esc(p.desc)}</p>
      <div class="p-tags">${p.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
      <div class="p-foot">
        <span class="p-ends">${p.video ? '实机演示视频 · 1 个入口' : '客户端 + 管理端 · 2 个入口'}</span>
        <span class="p-open">${p.video ? '观看视频 →' : '查看演示 →'}</span>
      </div>
    </a>`).join('');

  return `
    <div class="top">
      <div>
        <div class="eyebrow">Portfolio · Online Demo</div>
        <h1 class="name">王浩源</h1>
        <div class="role">AI 应用开发 / 全栈开发 · 2027 届</div>
      </div>
      <span class="badge-demo">在线演示</span>
    </div>
    <p class="intro">这里放了我四个项目的演示入口。选一个项目，再选客户端或管理端，点「直接访问」即可打开；手机和电脑都能用，账号已预填。老人防摔系统可直接在线播放实机演示视频。</p>
    <div class="meta-row">
      <span class="meta-chip">4 个项目</span>
      <span class="meta-chip">6 个链接 + 1 段视频</span>
      <span class="meta-chip">手机 H5 / PC 双端</span>
    </div>
    <div class="section-label">项目列表 <span>按简历顺序</span></div>
    ${cards}
    <footer>
      <span>王浩源 · 项目演示入口</span>
      <a href="/admin">访问统计</a>
    </footer>`;
}

function endCard(p, end) {
  return `
    <div class="end-card">
      <div class="end-top">
        <span class="end-name">${esc(end.label)}</span>
        <span class="env ${end.envClass}">${esc(end.env)}</span>
      </div>
      <p class="end-desc">${esc(end.desc)}</p>
      <p class="end-account">${esc(end.account)}</p>
      <a class="open-btn" href="${esc(end.url)}" target="_blank" rel="noopener"
         data-project="${p.id}" data-endpoint="${end.key}">
        <span>直接访问${end.envClass === 'h5' ? '手机端' : '电脑端'}</span><span>↗</span>
      </a>
    </div>`;
}

function videoCard(p) {
  return `
    <div class="section-label">项目演示视频 <span>点击播放</span></div>
    <div class="video-card">
      <div class="video-box">
        <video controls playsinline preload="metadata" poster="${esc(p.video.poster)}" data-project="${p.id}">
          <source src="${esc(p.video.url)}" type="video/mp4" />
          当前浏览器不支持视频播放，请换用手机浏览器或 Chrome 打开。
        </video>
      </div>
      <p class="video-note">${esc(p.video.note)}</p>
    </div>`;
}

function detailView(p) {
  const endsBlock = p.ends.length
    ? `<div class="section-label">选择端 <span>点击后在新窗口打开</span></div>
    <div class="end-grid">${p.ends.map((e) => endCard(p, e)).join('')}</div>
    <div class="tip-box">
      手机 H5 端请用手机打开；PC 电脑端建议在电脑上查看。乡策通管理端为电脑布局，手机打开会错位。
      演示账号均为只读演示用途，数据会定期重置。
    </div>`
    : `<div class="tip-box">这段视频为老人防摔监护系统的实机演示：传感器采集姿态数据，识别跌倒后立即触发告警。</div>`;

  return `
    <a class="back" href="#/">← 返回项目列表</a>
    <div class="eyebrow">Project ${p.no} · ${esc(p.type)}</div>
    <h1 class="detail-title">${esc(p.name)}</h1>
    <p class="detail-desc">${esc(p.desc)}</p>
    <div class="detail-meta">${p.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    ${p.video ? videoCard(p) : ''}
    ${endsBlock}
    <footer>
      <span>王浩源 · 项目演示入口</span>
      <a href="#/">返回列表</a>
    </footer>`;
}

function render() {
  const app = document.getElementById('app');
  const route = (location.hash || '#/').replace(/^#/, '');
  const match = route.match(/^\/p\/([a-z0-9_-]+)/i);
  const project = match ? PROJECT_MAP.get(match[1]) : null;

  if (project) {
    document.title = `${project.name} · 演示`;
    app.innerHTML = detailView(project);
    track('project_view', project.id, '');
  } else {
    document.title = '王浩源 · 项目演示';
    app.innerHTML = homeView();
    track('page_view', '', '');
  }
  window.scrollTo(0, 0);
}

document.addEventListener('click', (event) => {
  const link = event.target.closest('a.open-btn');
  if (!link) return;
  track('click', link.dataset.project, link.dataset.endpoint);
});

document.addEventListener('play', (event) => {
  const video = event.target;
  if (!video || video.tagName !== 'VIDEO' || video.dataset.tracked === '1') return;
  video.dataset.tracked = '1';
  track('click', video.dataset.project, 'video');
}, true);

window.addEventListener('hashchange', render);
render();
