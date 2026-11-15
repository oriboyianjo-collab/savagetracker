#!/usr/bin/env node
// Official one-request EDGAR GET. Same legal client pattern as scripts/fetch-fundamentals.cjs.
// Declared User-Agent, official sec.gov hosts only, no retries, no proxies, no disguised UA.
const { URL } = require('url');
const UA = process.env.SEC_UA || 'SavageTracker Savtra12@gmail.com';
const url = process.argv[2];
if (!url) {
  console.error('usage: node sec_fetch.cjs URL');
  process.exit(2);
}
if (/Mozilla/i.test(UA) || !UA.includes('@') || !UA.includes('SavageTracker')) {
  console.error('refusing to send an undeclared or disguised User-Agent');
  process.exit(2);
}
let parsed;
try { parsed = new URL(url); } catch (e) {
  console.error('invalid url');
  process.exit(2);
}
if (parsed.protocol !== 'https:' || !['data.sec.gov', 'www.sec.gov'].includes(parsed.hostname) || parsed.username || parsed.password || parsed.search || parsed.hash) {
  console.error('refusing non-official SEC URL');
  process.exit(2);
}
if (!(parsed.pathname.startsWith('/Archives/edgar/data/1035267/') || parsed.pathname.startsWith('/submissions/CIK0001035267'))) {
  console.error('refusing wrong issuer/route');
  process.exit(2);
}

const ac = new AbortController();
const timer = setTimeout(() => ac.abort(), 30000);
(async () => {
  const r = await fetch(url, {
    headers: { 'User-Agent': UA, 'Accept-Encoding': 'gzip, deflate', Accept: '*/*' },
    redirect: 'manual',
    signal: ac.signal,
  });
  const buf = Buffer.from(await r.arrayBuffer());
  const out = {
    status: r.status,
    final_url: r.url,
    headers: Object.fromEntries(r.headers.entries()),
    hex: buf.subarray(0, 25 * 1024 * 1024 + 1).toString('hex'),
    bytes: buf.length,
  };
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  console.error(String(e && e.message || e));
  process.exit(3);
}).finally(() => clearTimeout(timer));
