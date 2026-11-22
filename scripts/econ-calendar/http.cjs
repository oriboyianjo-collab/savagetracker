'use strict';

const UA = 'SavageTracker Savtra12@gmail.com';
const MIN_GAP_MS = 1000;

/** Never let an API key reach a log, report or error message. */
function redact(u) {
  return String(u || '').replace(/([?&](?:UserID|registrationkey|api_key|key)=)[^&#\s]*/gi, '$1***');
}

function createHttp() {
  let lastAt = 0;
  let blocked = null; // { status, url, at }
  const log = [];

  function isBlocked() { return blocked; }

  async function waitGap() {
    const wait = lastAt + MIN_GAP_MS - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  }

  async function get(url, opts = {}) {
    if (blocked) {
      const err = new Error(`http blocked after ${blocked.status} from ${blocked.url}`);
      err.code = 'HTTP_BLOCKED';
      err.status = blocked.status;
      throw err;
    }
    await waitGap();
    lastAt = Date.now();
    const headers = { 'User-Agent': UA, Accept: opts.accept || '*/*', ...(opts.headers || {}) };
    let res;
    try {
      res = await fetch(url, { method: opts.method || 'GET', headers, body: opts.body, redirect: 'follow' });
    } catch (e) {
      throw new Error(`fetch failed for ${redact(url)}: ${redact(e.message)}`);
    }
    const buf = Buffer.from(await res.arrayBuffer());
    const rec = { url: redact(url), status: res.status, bytes: buf.length };
    log.push(rec);
    if (res.status === 403 || res.status === 429) {
      blocked = { status: res.status, url: redact(url), at: new Date().toISOString() };
      const err = new Error(`Stopped after HTTP ${res.status} from ${redact(url)} (no retry/workaround)`);
      err.code = 'HTTP_STOP';
      err.status = res.status;
      err.url = redact(url);
      throw err;
    }
    if (!res.ok && !opts.allowStatuses?.includes(res.status)) {
      const err = new Error(`HTTP ${res.status} ${redact(url)}`);
      err.status = res.status;
      err.url = redact(url);
      err.body = buf.slice(0, 400).toString('utf8');
      throw err;
    }
    const ct = res.headers.get('content-type') || '';
    return { status: res.status, headers: res.headers, buf, text: () => buf.toString('utf8'), contentType: ct, url: redact(res.url || url) };
  }

  async function getText(url, opts) {
    const r = await get(url, opts);
    return r.text();
  }

  return { UA, get, getText, isBlocked, log, waitGap };
}

module.exports = { UA, createHttp, redact };
