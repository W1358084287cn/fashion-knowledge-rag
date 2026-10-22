const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT || 3003);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const WEB_DIR = path.join(__dirname, 'web');
const PROJECT_IDS = ['rag', 'xct', 'ouc', 'fall'];
const PROJECT_SET = new Set(PROJECT_IDS);
const ENDPOINTS = new Set(['client', 'admin', 'video']);

fs.mkdirSync(DATA_DIR, { recursive: true });

const fmtDateTime = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'medium'
});
const fmtDate = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
});

function nowTs() { return fmtDateTime.format(new Date()).replace('T', ' '); }
function today() { return fmtDate.format(new Date()); }

function appendLine(file, obj) {
  try {
    fs.appendFileSync(path.join(DATA_DIR, file), JSON.stringify(obj) + '\n');
  } catch (err) {
    console.error('写入失败', file, err.message);
  }
}

function readLines(file) {
  const p = path.join(DATA_DIR, file);
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      try { return JSON.parse(line); } catch { return null; }
    })
    .filter(Boolean);
}

function visitorId(ip, ua) {
  return crypto.createHash('sha1').update(`${ip}|${ua}`).digest('hex').slice(0, 16);
}

function deviceOf(ua) {
  const s = (ua || '').toLowerCase();
  return /mobile|android|iphone|ipad|ipod|harmony/.test(s) ? 'mobile' : 'pc';
}

function clientIp(req) {
  const fwd = req.headers['x-forwarded-for'];
  if (fwd) return String(fwd).split(',')[0].trim();
  return (req.socket.remoteAddress || '').replace('::ffff:', '');
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.mp4': 'video/mp4'
};

function sendJson(res, status, data) {
  const body = JSON.stringify(data);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'Content-Length': Buffer.byteLength(body)
  });
  res.end(body);
}

function sendFile(req, res, filePath, cache) {
  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('404');
      return;
    }
    const ext = path.extname(filePath).toLowerCase();
    const type = MIME[ext] || 'application/octet-stream';
    const cacheHeader = cache ? 'public, max-age=300' : 'no-store';
    const range = req.headers.range;

    // 视频需要支持 Range 请求，否则 iOS 与部分安卓浏览器无法播放/拖动
    if (ext === '.mp4' && range) {
      const m = /^bytes=(\d*)-(\d*)$/.exec(String(range));
      if (!m) {
        res.writeHead(416, { 'Content-Range': `bytes */${stat.size}` });
        res.end();
        return;
      }
      let start = m[1] ? Number(m[1]) : 0;
      let end = m[2] ? Number(m[2]) : stat.size - 1;
      if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= stat.size) {
        res.writeHead(416, { 'Content-Range': `bytes */${stat.size}` });
        res.end();
        return;
      }
      end = Math.min(end, stat.size - 1);
      res.writeHead(206, {
        'Content-Type': type,
        'Accept-Ranges': 'bytes',
        'Content-Range': `bytes ${start}-${end}/${stat.size}`,
        'Content-Length': end - start + 1,
        'Cache-Control': cacheHeader
      });
      fs.createReadStream(filePath, { start, end }).pipe(res);
      return;
    }

    res.writeHead(200, {
      'Content-Type': type,
      'Content-Length': stat.size,
      'Accept-Ranges': 'bytes',
      'Cache-Control': cacheHeader
    });
    fs.createReadStream(filePath).pipe(res);
  });
}

function readBody(req, limit = 8192) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) { reject(new Error('请求体过大')); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on('end', () => {
      try {
        const text = Buffer.concat(chunks).toString('utf8');
        resolve(text ? JSON.parse(text) : {});
      } catch { resolve({}); }
    });
    req.on('error', reject);
  });
}

const recentTrack = new Map();
function isDuplicate(key) {
  const now = Date.now();
  const last = recentTrack.get(key) || 0;
  recentTrack.set(key, now);
  if (recentTrack.size > 5000) recentTrack.clear();
  return now - last < 3000;
}

function logOp(ip, action, detail) {
  appendLine('ops.ndjson', { ts: nowTs(), ip, action, detail: detail || '' });
}

// 后台免登录，同一 IP 10 分钟内只记一条「打开统计后台」，避免刷新刷屏
const adminViewHits = new Map();
function logAdminView(ip) {
  const now = Date.now();
  const last = adminViewHits.get(ip) || 0;
  if (now - last < 600000) return;
  adminViewHits.set(ip, now);
  logOp(ip, '打开统计后台', '免登录访问');
}

function buildStats() {
  const events = readLines('events.ndjson');
  const todayStr = today();
  const views = events.filter((e) => e.event !== 'click');
  const clicks = events.filter((e) => e.event === 'click');
  const visitorSet = new Set(events.map((e) => e.visitor).filter(Boolean));

  const projects = PROJECT_IDS.map((id) => {
    const rows = clicks.filter((e) => e.project === id);
    return {
      project: id,
      total: rows.length,
      client: rows.filter((e) => e.endpoint === 'client').length,
      admin: rows.filter((e) => e.endpoint === 'admin').length,
      video: rows.filter((e) => e.endpoint === 'video').length
    };
  }).sort((a, b) => b.total - a.total);

  const daily = [];
  for (let i = 6; i >= 0; i -= 1) {
    const d = new Date(Date.now() - i * 86400000);
    const key = fmtDate.format(d);
    daily.push({
      date: key,
      views: views.filter((e) => String(e.ts).startsWith(key)).length,
      clicks: clicks.filter((e) => String(e.ts).startsWith(key)).length
    });
  }

  const devices = [
    { device: 'mobile', count: events.filter((e) => e.device === 'mobile').length },
    { device: 'pc', count: events.filter((e) => e.device === 'pc').length }
  ];

  return {
    pv: views.length,
    uv: visitorSet.size,
    todayPv: views.filter((e) => String(e.ts).startsWith(todayStr)).length,
    todayUv: new Set(views.filter((e) => String(e.ts).startsWith(todayStr)).map((e) => e.visitor)).size,
    clicks: clicks.length,
    todayClicks: clicks.filter((e) => String(e.ts).startsWith(todayStr)).length,
    projects,
    daily,
    devices,
    events: events.slice(-60).reverse(),
    ops: readLines('ops.ndjson').slice(-40).reverse()
  };
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = url.pathname;

  if (pathname === '/api/health') {
    sendJson(res, 200, { code: 0, msg: 'ok', data: { service: 'project-hub', time: nowTs() } });
    return;
  }

  if (pathname === '/api/track' && req.method === 'POST') {
    const body = await readBody(req);
    const event = String(body.event || '');
    const project = String(body.project || '');
    const endpoint = String(body.endpoint || '');
    if (!['page_view', 'project_view', 'click'].includes(event)) {
      sendJson(res, 200, { code: 1001, msg: '事件类型非法' });
      return;
    }
    if (project && !PROJECT_SET.has(project)) {
      sendJson(res, 200, { code: 1001, msg: '项目非法' });
      return;
    }
    if (endpoint && !ENDPOINTS.has(endpoint)) {
      sendJson(res, 200, { code: 1001, msg: '端类型非法' });
      return;
    }
    if (!project && event !== 'page_view') {
      sendJson(res, 200, { code: 1001, msg: '缺少项目' });
      return;
    }
    if (event !== 'click' && !endpoint) {
      // 页面浏览不记录端类型
    }
    const ip = clientIp(req);
    const ua = String(req.headers['user-agent'] || '').slice(0, 300);
    const visitor = visitorId(ip, ua);
    if (event !== 'click' && isDuplicate(`${visitor}|${event}|${project}`)) {
      sendJson(res, 200, { code: 0, msg: 'ignored' });
      return;
    }
    appendLine('events.ndjson', {
      ts: nowTs(), event, project, endpoint,
      ip, ua, device: deviceOf(ua), visitor
    });
    sendJson(res, 200, { code: 0, msg: 'ok' });
    return;
  }

  if (pathname === '/api/stats' && req.method === 'GET') {
    sendJson(res, 200, { code: 0, msg: 'ok', data: buildStats() });
    return;
  }

  if (pathname === '/' || pathname === '/index.html') {
    sendFile(req, res, path.join(WEB_DIR, 'index.html'), false);
    return;
  }
  if (pathname === '/admin' || pathname === '/admin/' || pathname === '/admin.html') {
    logAdminView(clientIp(req));
    sendFile(req, res, path.join(WEB_DIR, 'admin.html'), false);
    return;
  }

  const rel = pathname.replace(/^\/+/, '');
  const target = path.resolve(WEB_DIR, rel);
  if (target.startsWith(WEB_DIR) && fs.existsSync(target) && fs.statSync(target).isFile()) {
    sendFile(req, res, target, true);
    return;
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('404 Not Found');
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`project hub listening on ${PORT}`);
});
