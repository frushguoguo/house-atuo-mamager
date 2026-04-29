const fs = require('fs');
const path = require('path');

const DEFAULT_DEBUG_PORT = parseInt(process.env.APLUS_DEBUG_PORT || '9222', 10);
const DEFAULT_DURATION = parseInt(process.env.APLUS_CAPTURE_SECONDS || '180', 10);
const DEFAULT_OUTPUT = process.env.APLUS_CAPTURE_OUTPUT || path.resolve(process.cwd(), 'runtime', 'aplus_click_capture.json');

function parseArgs(argv) {
  const args = {
    port: DEFAULT_DEBUG_PORT,
    seconds: DEFAULT_DURATION,
    output: DEFAULT_OUTPUT,
    keyword: '',
    includeStatic: false,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const token = argv[i];
    const next = argv[i + 1];
    if (token === '--port' && next) {
      args.port = parseInt(next, 10);
      i += 1;
      continue;
    }
    if (token === '--seconds' && next) {
      args.seconds = parseInt(next, 10);
      i += 1;
      continue;
    }
    if (token === '--output' && next) {
      args.output = path.resolve(next);
      i += 1;
      continue;
    }
    if (token === '--keyword' && next) {
      args.keyword = String(next).toLowerCase();
      i += 1;
      continue;
    }
    if (token === '--include-static') {
      args.includeStatic = true;
      continue;
    }
  }
  return args;
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} for ${url}`);
  }
  return await res.json();
}

function isCaptureTarget(item) {
  if (!item || !item.webSocketDebuggerUrl) return false;
  const t = String(item.type || '').toLowerCase();
  if (t !== 'page' && t !== 'webview') return false;
  const url = String(item.url || '').toLowerCase();
  if (
    url.startsWith('devtools://') ||
    url.startsWith('chrome://') ||
    url.startsWith('edge://') ||
    url.startsWith('about:blank')
  ) {
    return false;
  }
  return true;
}

function scoreTarget(item) {
  const url = String(item.url || '').toLowerCase();
  const title = String(item.title || '').toLowerCase();
  const t = String(item.type || '').toLowerCase();
  let score = 0;
  if (t === 'webview') score += 25;
  if (
    url.includes('xinfang.a.ke.com') ||
    url.includes('deal.fang.lianjia.com') ||
    url.includes('linkconsole.fang.lianjia.com') ||
    url.includes('house.link.lianjia.com') ||
    url.includes('shouye.link.lianjia.com')
  ) {
    score += 30;
  }
  if (url.includes('ke.com') || url.includes('lianjia.com')) score += 12;
  if (url.startsWith('file:///')) score += 2;
  if (title.includes('a+')) score += 4;
  return score;
}

function pickTargets(targets, maxTargets = 12) {
  return targets
    .filter(isCaptureTarget)
    .map((item) => ({ ...item, _score: scoreTarget(item) }))
    .sort((a, b) => (b._score - a._score))
    .slice(0, maxTargets);
}

function shouldKeepUrl(rawUrl, includeStatic, keyword) {
  const url = String(rawUrl || '');
  const lower = url.toLowerCase();
  if (!lower.startsWith('http://') && !lower.startsWith('https://')) return false;
  if (!includeStatic && /\.(?:js|css|png|jpg|jpeg|gif|svg|ico|woff2?|ttf|map)(?:\?|$)/i.test(lower)) {
    return false;
  }
  if (keyword && !lower.includes(keyword)) {
    return false;
  }
  return lower.includes('ke.com') || lower.includes('lianjia.com') || lower.includes('/api/');
}

function normalizePath(rawUrl) {
  try {
    const u = new URL(rawUrl);
    return u.pathname || '';
  } catch {
    return '';
  }
}

function shouldTrackAsBusiness(rawUrl) {
  const lower = String(rawUrl || '').toLowerCase();
  return (
    lower.includes('/api/') ||
    lower.includes('/search/') ||
    lower.includes('/pc/risk/') ||
    lower.includes('/layer/')
  );
}

function shouldFetchBody(rawUrl, mimeType) {
  const lower = String(rawUrl || '').toLowerCase();
  const mime = String(mimeType || '').toLowerCase();
  if (mime.includes('json')) return true;
  return (
    lower.includes('/api/') ||
    lower.includes('/search/') ||
    lower.includes('/pc/risk/') ||
    lower.includes('/layer/')
  );
}

function extractPath(data, selector) {
  const tokens = String(selector || '').split('.').map((x) => x.trim()).filter(Boolean);
  let cur = data;
  for (const t of tokens) {
    if (cur && typeof cur === 'object' && !Array.isArray(cur)) {
      cur = cur[t];
      continue;
    }
    if (Array.isArray(cur) && /^\d+$/.test(t)) {
      const idx = parseInt(t, 10);
      cur = (idx >= 0 && idx < cur.length) ? cur[idx] : undefined;
      continue;
    }
    return undefined;
  }
  return cur;
}

function summarizeBody(bodyText) {
  const summary = {
    bodySample: String(bodyText || '').slice(0, 1200),
    jsonKeys: [],
    listPath: '',
    listSize: 0,
    dictRowCount: 0,
    listRows: [],
  };
  if (!bodyText) return summary;
  try {
    const obj = JSON.parse(bodyText);
    if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
      summary.jsonKeys = Object.keys(obj).slice(0, 40);
    }
    const selectors = [
      'data.list',
      'data.rows',
      'data.records',
      'data.result.list',
      'result.list',
      'list',
      'rows',
      'records',
      'data.data',
      'data.houses',
    ];
    for (const s of selectors) {
      const v = extractPath(obj, s);
      if (!Array.isArray(v)) continue;
      const dictCount = v.filter((it) => it && typeof it === 'object' && !Array.isArray(it)).length;
      summary.listPath = s;
      summary.listSize = v.length;
      summary.dictRowCount = dictCount;
      if (dictCount > 0) {
        const rows = [];
        for (const row of v) {
          if (!row || typeof row !== 'object' || Array.isArray(row)) continue;
          rows.push(row);
          if (rows.length >= 200) break;
        }
        summary.listRows = rows;
      }
      break;
    }
  } catch {
    // ignore non-json
  }
  return summary;
}

async function main() {
  const args = parseArgs(process.argv);
  const debugBase = `http://127.0.0.1:${args.port}`;

  console.log(`[aplus-cdp] connect ${debugBase}`);
  let targets;
  try {
    targets = await fetchJson(`${debugBase}/json/list`);
  } catch (err) {
    console.error(`[aplus-cdp] cannot connect CDP: ${err.message}`);
    console.error('[aplus-cdp] 请先用 --remote-debugging-port=9222 方式启动 A+，再重试');
    process.exit(2);
  }

  if (!Array.isArray(targets) || targets.length === 0) {
    console.error('[aplus-cdp] no target pages from /json/list');
    process.exit(3);
  }

  const selectedTargets = pickTargets(targets);
  if (!selectedTargets.length) {
    console.error('[aplus-cdp] no websocket debugger target found');
    process.exit(4);
  }

  console.log(`[aplus-cdp] selected targets: ${selectedTargets.length}`);
  for (const target of selectedTargets) {
    console.log(`[aplus-cdp] target: ${target.title || '(untitled)'} -> ${target.url}`);
  }

  const startedAt = new Date();
  const requestRows = [];
  const responseRows = [];
  const apiCounter = new Map();
  const sockets = [];
  let captureBannerShown = false;

  function send(ws, state, method, params = {}) {
    const id = state.nextId;
    const payload = { id, method, params };
    state.nextId += 1;
    ws.send(JSON.stringify(payload));
    return id;
  }

  for (const target of selectedTargets) {
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    const state = {
      nextId: 1,
      target,
      requestMetaById: new Map(),
      pendingBodyByCmdId: new Map(),
    };
    sockets.push(ws);

    ws.onopen = () => {
      send(ws, state, 'Network.enable');
      send(ws, state, 'Page.enable');
      send(ws, state, 'Runtime.enable');
      if (!captureBannerShown) {
        captureBannerShown = true;
        console.log(`[aplus-cdp] capturing ${args.seconds}s, 请现在点击 A+ 页面...`);
      }
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg.id && state.pendingBodyByCmdId.has(msg.id)) {
        const meta = state.pendingBodyByCmdId.get(msg.id);
        state.pendingBodyByCmdId.delete(msg.id);

        if (msg.error) {
          responseRows.push({
            ...meta,
            bodyError: String(msg.error.message || msg.error.code || 'getResponseBody failed'),
            bodySample: '',
            jsonKeys: [],
            listPath: '',
            listSize: 0,
            dictRowCount: 0,
          });
          return;
        }

        const result = msg.result || {};
        let bodyText = String(result.body || '');
        if (result.base64Encoded) {
          try {
            bodyText = Buffer.from(bodyText, 'base64').toString('utf8');
          } catch {
            bodyText = '';
          }
        }
        const bodySummary = summarizeBody(bodyText);
        responseRows.push({
          ...meta,
          ...bodySummary,
        });
        if (responseRows.length <= 80) {
          console.log(`[resp] ${meta.method} ${meta.url} status=${meta.status} list=${bodySummary.listPath || '-'}:${bodySummary.listSize}`);
        }
        return;
      }

      if (msg.method === 'Network.requestWillBeSent') {
        const params = msg.params || {};
        const req = params.request || {};
        const url = String(req.url || '');
        if (!shouldKeepUrl(url, args.includeStatic, args.keyword)) return;

        const method = String(req.method || 'GET').toUpperCase();
        const type = String(params.type || 'unknown');
        const ts = new Date().toISOString();

        state.requestMetaById.set(String(params.requestId || ''), {
          method,
          url,
          ts,
          type,
        });

        requestRows.push({
          ts,
          method,
          type,
          url,
          referer: String((req.headers || {}).Referer || ''),
          postDataSample: String(req.postData || '').slice(0, 300),
          targetId: state.target.id,
          targetTitle: state.target.title || '',
          targetUrl: state.target.url || '',
        });

        if (shouldTrackAsBusiness(url)) {
          const p = normalizePath(url);
          const key = `${method} ${p || url}`;
          apiCounter.set(key, (apiCounter.get(key) || 0) + 1);
        }

        if (requestRows.length <= 200) {
          console.log(`[hit] ${method} ${url}`);
        }
        return;
      }

      if (msg.method === 'Network.responseReceived') {
        const params = msg.params || {};
        const response = params.response || {};
        const requestId = String(params.requestId || '');
        const url = String(response.url || '');
        if (!shouldKeepUrl(url, args.includeStatic, args.keyword)) return;

        const reqMeta = state.requestMetaById.get(requestId) || {};
        const method = String(reqMeta.method || '').toUpperCase() || 'GET';
        const mimeType = String(response.mimeType || '');

        if (!shouldFetchBody(url, mimeType)) return;

        if (responseRows.length >= 500) return;

        const cmdId = send(ws, state, 'Network.getResponseBody', { requestId });
        state.pendingBodyByCmdId.set(cmdId, {
          ts: new Date().toISOString(),
          method,
          url,
          status: Number(response.status || 0),
          mimeType,
          targetId: state.target.id,
          targetTitle: state.target.title || '',
          targetUrl: state.target.url || '',
        });
        return;
      }
    };

    ws.onerror = (err) => {
      console.error('[aplus-cdp] websocket error', err.message || err);
    };
  }

  const finish = () => {
    for (const ws of sockets) {
      try {
        ws.close();
      } catch {}
    }

    const topApis = Array.from(apiCounter.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 120)
      .map(([api, count]) => ({ api, count }));

    const payload = {
      generated_at: new Date().toISOString(),
      started_at: startedAt.toISOString(),
      port: args.port,
      seconds: args.seconds,
      target: selectedTargets[0]
        ? {
          id: selectedTargets[0].id,
          title: selectedTargets[0].title,
          url: selectedTargets[0].url,
          ws: selectedTargets[0].webSocketDebuggerUrl,
        }
        : null,
      targets: selectedTargets.map((item) => ({
        id: item.id,
        title: item.title,
        type: item.type,
        url: item.url,
        ws: item.webSocketDebuggerUrl,
      })),
      total_hits: requestRows.length,
      response_hits: responseRows.length,
      api_top: topApis,
      requests: requestRows,
      responses: responseRows,
    };

    const out = path.resolve(args.output);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    fs.writeFileSync(out, JSON.stringify(payload, null, 2), 'utf8');

    console.log(`[aplus-cdp] done: hits=${requestRows.length}, responses=${responseRows.length}, api_top=${topApis.length} -> ${out}`);
  };

  setTimeout(finish, Math.max(args.seconds, 10) * 1000);
}

main().catch((err) => {
  console.error('[aplus-cdp] fatal', err && err.message ? err.message : err);
  process.exit(1);
});
