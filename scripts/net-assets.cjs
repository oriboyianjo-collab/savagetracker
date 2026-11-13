// Total net assets (AUM) per ETF from the issuers' own public fund data. Used by fetch-issuer-holdings.cjs -> holdings/issuer.json "netAssets".
// Only values an issuer publishes together with an as-of date. Any failure of one issuer leaves the previous values in place.
// Sources: iShares product screener (all US iShares ETFs), SSGA/SPDR fund finder, Global X and First Trust fund pages, NEOS official dated fund overview, YieldMax official fund details, Defiance official dated fund directory, VistaShares dated fund details, Volatility Shares dated Net Assets, and Timothy Plan dated Fund Details (source precision retained).
const fs = require('fs'), path = require('path');
const UA = {'User-Agent': 'Mozilla/5.0 (compatible; savage-tracker-netassets)', 'Accept': '*/*'};
const iso8 = n => { const s = String(n); return /^\d{8}$/.test(s) ? `${s.slice(0,4)}-${s.slice(4,6)}-${s.slice(6,8)}` : null; };
const MON = {jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12};
const parseDate = t => { const m = String(t||'').match(/([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})/); return m && MON[m[1].toLowerCase()] ? `${m[3]}-${String(MON[m[1].toLowerCase()]).padStart(2,'0')}-${m[2].padStart(2,'0')}` : null; };
const get = async (url, ms = 30000) => { const c = new AbortController(), t = setTimeout(() => c.abort(), ms); try{ const r = await fetch(url, {headers: UA, signal: c.signal}); if(!r.ok) throw new Error('HTTP ' + r.status); return await r.text(); } finally { clearTimeout(t); } };
const plain = h => h.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/g, ' ').replace(/<[^>]+>/g, ' ').replace(/&nbsp;|&#160;/g, ' ').replace(/\s+/g, ' ');
const money = s => { const m = String(s||'').match(/\$\s*([\d,]+(?:\.\d+)?)\s*([BMK]?)/i); if(!m) return null; const k = {B:1e9, M:1e6, K:1e3}[m[2].toUpperCase()] || 1; return Math.round(parseFloat(m[1].replace(/,/g,'')) * k); };
async function ishares(){ const out = {}, j = JSON.parse(await get('https://www.ishares.com/us/product-screener/product-screener-v3.1.jsn?dcrPath=/templatedata/config/product-screener-v3/data/en/us-ishares/ishares-product-screener-backend-config&siteEntryPassthrough=true', 60000));
  for(const id of Object.keys(j)){ const x = j[id]; if(!x || !Array.isArray(x.productView) || !x.productView.includes('etf')) continue; const t = String(x.localExchangeTicker||'').trim().toUpperCase(), v = x.totalNetAssetsFund && x.totalNetAssetsFund.r, d = x.totalNetAssetsFundAsOf && iso8(x.totalNetAssetsFundAsOf.r);
    if(/^[A-Z][A-Z0-9.\-]{0,9}$/.test(t) && v > 0 && d) out[t] = {v: Math.round(v), asOf: d, issuer: 'iShares', src: `https://www.ishares.com/us/products/${id}/`}; } return out; }
async function ssga(){ const out = {}, j = JSON.parse(await get('https://www.ssga.com/bin/v1/ssmp/fund/fundfinder?country=us&language=en&role=intermediary&product=etfs&ui=fund-finder', 60000));
  for(const f of (((j.data||{}).funds||{}).etfs||{}).datas || []){ const t = String(f.fundTicker||'').replace(/[^A-Za-z0-9.\-]/g, '').toUpperCase(), a = f.aum, d = f.asOfDate && f.asOfDate[1];
    if(/^[A-Z][A-Z0-9.\-]{0,9}$/.test(t) && Array.isArray(a) && a[1] > 0 && /^\d{4}-\d{2}-\d{2}$/.test(d||'')) out[t] = {v: Math.round(a[1] * 1e6), asOf: d, issuer: 'SSGA (SPDR)', src: 'https://www.ssga.com' + (f.fundUri || '')}; } return out; }
async function globalx(t){ const url = `https://www.globalxetfs.com/funds/${t.toLowerCase()}/`, p = plain(await get(url)), m = p.match(/Net Assets\s+(\$[\d.,]+\s*[BMK]?)\s+As of\s+([A-Za-z]{3}[a-z]*\.? \d{1,2}, \d{4})/); if(!m) return null; const v = money(m[1]), d = parseDate(m[2]); return v && d ? {v, asOf: d, issuer: 'Global X', src: url} : null; }
async function firsttrust(t){ const url = `https://www.ftportfolios.com/retail/etf/etfsummary.aspx?Ticker=${t}`, p = plain(await get(url, 40000)), m = p.match(/Total Net Assets\s+\$([\d,]+)\s+Outstanding Shares/), d = p.match(/Total Net Assets[\s\S]{0,400}?As of\s+(\d{1,2}\/\d{1,2}\/\d{4})/i) || p.match(/as of\s+(\d{1,2}\/\d{1,2}\/\d{4})/i);
  if(!m) return null; const v = parseInt(m[1].replace(/,/g,''), 10), dm = d && d[1].match(/(\d{1,2})\/(\d{1,2})\/(\d{4})/); return v > 0 && dm ? {v, asOf: `${dm[3]}-${dm[1].padStart(2,'0')}-${dm[2].padStart(2,'0')}`, issuer: 'First Trust', src: url} : null; }
function parseNeos(h,universe){
 const out={},section=h.match(/<div\b[^>]*\bid=["']fund-overview["'][^>]*>([\s\S]*?)<\/table>/i);if(!section)return out;
 const dm=plain(section[1]).trim().match(/^As of\s+(\d{1,2})\/(\d{1,2})\/(\d{4})\b/);if(!dm)return out;
 const asOf=`${dm[3]}-${dm[1].padStart(2,'0')}-${dm[2].padStart(2,'0')}`;const d=new Date(asOf+'T00:00:00Z');if(!Number.isFinite(+d)||d.toISOString().slice(0,10)!==asOf)return out;
 const table=section[1].match(/<table\b[^>]*>([\s\S]*)/i);if(!table)return out;
 const head=table[1].match(/<thead\b[^>]*>([\s\S]*?)<\/thead>/i);if(!head)return out;
 const headers=[...head[1].matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/gi)].map(m=>plain(m[1]).trim().toLowerCase());
 if(headers.length!==8||headers[0]!=='ticker'||headers[6]!=='net assets'||headers[7]!=='inception date')return out;
 const permitted=new Set(universe.filter(x=>x&&x[2]===1&&/^NEOS\b/i.test(x[1])).map(x=>x[0]));const duplicates=new Set();
 for(const row of table[1].matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)){
  // HTML permits an omitted </td>; split on starts, not closing tags.
  const cells=row[1].split(/<td\b[^>]*>/i).slice(1).map(x=>plain(x).trim());if(cells.length!==8)continue;
  const t=cells[0],am=cells[6].match(/^\$([\d,]+(?:\.\d+)?)$/),v=am&&Number(am[1].replace(/,/g,''));
  if(!permitted.has(t)||!v||!Number.isFinite(v)||v<0||!/^\d{2}\/\d{2}\/\d{4}$/.test(cells[7]))continue;
  if(out[t]||duplicates.has(t)){delete out[t];duplicates.add(t);continue;}
  out[t]={v:Math.round(v),asOf,issuer:'NEOS',src:'https://neosfunds.com/',currency:'USD'};
 }
 return out;
}

const strip = s=>s.replace(/<[^>]+>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/\s+/g,' ').trim();
function divTree(h){const stack=[],nodes=[];for(const m of h.matchAll(/<\/?div\b[^>]*>/gi)){if(/^<\//.test(m[0])){const n=stack.pop();if(n){n.end=m.index+m[0].length;nodes.push(n);}}else{const a=m[0].match(/\bclass=["']([^"']*)["']/i);const n={start:m.index,inner:m.index+m[0].length,classes:(a?a[1]:'').split(/\s+/),parent:stack[stack.length-1]||null};stack.push(n);}}return nodes;}
function yieldmaxLinks(h,names){const out={},dup=new Set(),wanted=new Set(names.filter(x=>x&&x[2]===1&&/^YieldMax\b/i.test(x[1])).map(x=>x[0]));for(const m of h.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>/gi)){let u;try{u=new URL(m[1],'https://yieldmaxetfs.com/our-etfs/')}catch(e){continue}if(u.protocol!=='https:'||u.hostname!=='yieldmaxetfs.com')continue;const slug=u.pathname.match(/^\/our-etfs\/([a-z0-9]+)\/$/i);if(!slug)continue;const t=slug[1].toUpperCase();if(!wanted.has(t))continue;const url=u.origin+u.pathname;if(out[t]&&out[t]!==url){delete out[t];dup.add(t)}else if(!dup.has(t))out[t]=url;}return out;}
function parseYieldmax(h,t,src){
 if(![...h.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi)].some(m=>strip(m[1])===t))return null;
 const nodes=divTree(h),tables=nodes.filter(n=>n.classes.includes('fund-info-table'));
 const rows=n=>[...h.slice(n.start,n.end).matchAll(/<div\b[^>]*class=["']fund-label["'][^>]*>([\s\S]*?)<\/div>\s*<div\b[^>]*class=["']fund-value["'][^>]*>([\s\S]*?)<\/div>/gi)].map(m=>[strip(m[1]),strip(m[2])]);
 const identities=tables.map(rows).flat().filter(x=>x[0]==='Ticker:');if(identities.length!==1||identities[0][1]!==t)return null;
 const candidates=tables.map(n=>({n,r:rows(n)})).filter(x=>x.r.some(y=>y[0]==='Net Assets:'));if(candidates.length!==1)return null;
 const {n,r}=candidates[0],labels=['Net Assets:','NAV:','Shares Outstanding:','Premium/Discount Percentage','Closing Price:','Median 30-Day Spread*:'];if(r.length!==6||r.some((x,i)=>x[0]!==labels[i]))return null;
 let container=n.parent;while(container&&!container.classes.includes('e-con'))container=container.parent;if(!container?.end)return null;
 const text=strip(h.slice(container.start,container.end)),dates=[...text.matchAll(/\bAs of\s+(\d{1,2})\/(\d{1,2})\/(\d{4})\b/gi)];if(dates.length!==1||!text.startsWith('Net Assets:'))return null;
 const d=dates[0],asOf=`${d[3]}-${d[1].padStart(2,'0')}-${d[2].padStart(2,'0')}`,date=new Date(asOf+'T00:00:00Z');if(!Number.isFinite(+date)||date.toISOString().slice(0,10)!==asOf)return null;
 const m=r[0][1].match(/^\$([\d,]+(?:\.(\d+))?)\s*([BMK]?)$/);if(!m)return null;const mult={B:1e9,M:1e6,K:1e3,'':1}[m[3]],v=Number(m[1].replace(/,/g,''))*mult;if(!Number.isFinite(v)||v<=0)return null;
 return {v:Math.round(v),asOf,issuer:'YieldMax',src,currency:'USD',sourceValue:r[0][1],sourcePrecisionUSD:mult/10**(m[2]?.length||0)};
}



async function yieldmax(names,log){
 const links=Object.entries(yieldmaxLinks(await get('https://yieldmaxetfs.com/our-etfs/',40000),names)),out={};let i=0,blocked=false;
 await Promise.all(Array.from({length:2},async()=>{while(i<links.length&&!blocked){const[t,url]=links[i++];try{const r=parseYieldmax(await get(url,30000),t,url);if(r)out[t]=r;else log('NA   YieldMax gap',t);}catch(e){log('NA   YieldMax error',t,e.message);if(/HTTP (403|429)\b/.test(e.message))blocked=true;}}}));
 log('NA   YieldMax',Object.keys(out).length+'/'+links.length,blocked?'stopped on source access response':'');return out;
}

function parseDefiance(j,names){const out={},duplicates=new Set();if(!Array.isArray(j))return out;const wanted=new Set(names.filter(x=>x&&x[2]===1&&/^Defiance\b/i.test(x[1])).map(x=>x[0]));for(const f of j){if(!f||typeof f!=='object')continue;const t=f.ticker,d=f.rate_date,v=f.net_assets;if(!wanted.has(t)||!/^Defiance\b/i.test(f.name||'')||typeof v!=='number'||!Number.isFinite(v)||v<=0||!/^\d{4}-\d{2}-\d{2}$/.test(d||''))continue;const date=new Date(d+'T00:00:00Z');if(!Number.isFinite(+date)||date.toISOString().slice(0,10)!==d)continue;let u;try{u=new URL(f.url)}catch(e){continue}if(u.origin!=='https://www.defianceetfs.com'||u.pathname!=='/'+t.toLowerCase()+'/'||u.search||u.hash)continue;if(out[t]||duplicates.has(t)){delete out[t];duplicates.add(t);continue;}out[t]={v:Math.round(v),asOf:d,issuer:'Defiance',src:u.href,currency:'USD',sourceValue:v,sourcePrecisionUSD:0.01};}return out;}


function parseVista(html,t,src){const clean=s=>s.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();const one=(rx,s)=>{const m=[...s.matchAll(rx)];return m.length===1?m[0][1]:null};const key=one(/<div\b[^>]*\bid="key-information"[^>]*>([\s\S]*?<\/dl>)/g,html),tab=one(/<button\b[^>]*\bid="key-information-tab"[^>]*>([\s\S]*?)<\/button>/g,html),trading=one(/<div\b[^>]*\bid="trading-details"[^>]*>([\s\S]*?<\/dl>)/g,html);if(!key||!tab||!trading)return null;const id=one(/<dt>\s*Ticker\s*<\/dt>\s*<dd>([\s\S]*?)<\/dd>/g,trading);if(!id||clean(id)!==t)return null;const head=one(/<h1\b[^>]*>([\s\S]*?)<\/h1>/g,html);if(!head||!/^VistaShares\b/.test(clean(head)))return null;const date=one(/<span\b[^>]*class="etf-key__date"[^>]*>as of ([^<]+)<\/span>/g,tab);if(!date)return null;const m=date.match(/^([A-Z][a-z]+) (\d{1,2}), (20\d{2})$/);const months=['January','February','March','April','May','June','July','August','September','October','November','December'];if(!m||!months.includes(m[1]))return null;const d=m[3]+'-'+String(months.indexOf(m[1])+1).padStart(2,'0')+'-'+m[2].padStart(2,'0');const dd=new Date(d+'T00:00:00Z');if(!Number.isFinite(+dd)||dd.toISOString().slice(0,10)!==d)return null;const val=one(/<dt>\s*Net Assets\s*<\/dt>\s*<dd>([\s\S]*?)<\/dd>/g,key);if(!val)return null;const value=clean(val);if(!/^\$(?:\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$/.test(value))return null;const v=Number(value.replace(/[$,]/g,''));if(!Number.isFinite(v)||v<=0)return null;return{v:Math.round(v),asOf:d,issuer:'VistaShares',src,currency:'USD',sourceValue:value,sourcePrecisionUSD:0.01};}


function vistaLinks(h,names){const out={},wanted=new Set(names.filter(x=>x&&x[2]===1&&/^VistaShares\b/i.test(x[1])).map(x=>x[0]));for(const m of h.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>/gi)){let u;try{u=new URL(m[1],'https://www.vistashares.com/')}catch(e){continue}const a=u.pathname.match(/^\/etf\/([a-z]+)\/?$/);if(u.origin!=='https://www.vistashares.com'||!a||!wanted.has(a[1].toUpperCase()))continue;out[a[1].toUpperCase()]=u.origin+u.pathname.replace(/\/$/,'')+'/';}return out;}
async function vista(names,log){const links=Object.entries(vistaLinks(await get('https://www.vistashares.com/',40000),names)),out={};let i=0,blocked=false;await Promise.all(Array.from({length:2},async()=>{while(i<links.length&&!blocked){const[t,url]=links[i++];try{const r=parseVista(await get(url,30000),t,url);if(r)out[t]=r;else log('NA   VistaShares gap',t);}catch(e){log('NA   VistaShares error',t,e.message);if(/HTTP (403|429)\b/.test(e.message))blocked=true;}}}));log('NA   VistaShares',Object.keys(out).length+'/'+links.length,blocked?'stopped on source access response':'');return out;}

function volsharesLinks(h,names){const out={},wanted=new Set(names.filter(x=>x&&x[2]===1).map(x=>x[0]));for(const m of h.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)){let u;try{u=new URL(m[1],'https://www.volatilityshares.com/')}catch(e){continue}const a=u.pathname.match(/^\/([a-z]{2,5})\/?$/);if(u.origin!=='https://www.volatilityshares.com'||!a)continue;const t=a[1].toUpperCase(),txt=m[2].replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();if(!wanted.has(t)||!txt.startsWith(t+' ')||!txt.endsWith('ETF'))continue;out[t]=u.origin+u.pathname.replace(/\/$/,'');}return out;}
function parseVolshares(h,t,src){const clean=s=>s.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();const heads=[...h.matchAll(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi)];if(heads.length!==1||clean(heads[0][1])!==t)return null;const ids=[...h.matchAll(/<tr\b[^>]*>\s*<th\b[^>]*>\s*Ticker\s*<\/th>\s*<td\b[^>]*>([\s\S]*?)<\/td>\s*<\/tr>/gi)];if(ids.length!==1||clean(ids[0][1])!==t)return null;const matches=[...h.matchAll(/<tr\b[^>]*>\s*<th\b[^>]*>\s*Net Assets as of (\d{1,2})\/(\d{1,2})\/(20\d{2})\s*<\/th>\s*<td\b[^>]*>([\s\S]*?)<\/td>\s*<\/tr>/gi)];if(matches.length!==1)return null;const m=matches[0],d=m[3]+'-'+m[1].padStart(2,'0')+'-'+m[2].padStart(2,'0'),dd=new Date(d+'T00:00:00Z');if(!Number.isFinite(+dd)||dd.toISOString().slice(0,10)!==d)return null;const value=clean(m[4]);if(!/^\$(?:\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$/.test(value))return null;const v=Number(value.replace(/[$,]/g,''));if(!Number.isFinite(v)||v<=0)return null;return{v:Math.round(v),asOf:d,issuer:'Volatility Shares',src,currency:'USD',sourceValue:value,sourcePrecisionUSD:0.01};}


async function volshares(names,log){const links=Object.entries(volsharesLinks(await get('https://www.volatilityshares.com/',40000),names)),out={};let i=0,blocked=false;await Promise.all(Array.from({length:2},async()=>{while(i<links.length&&!blocked){const[t,url]=links[i++];try{const r=parseVolshares(await get(url,30000),t,url);if(r)out[t]=r;else log('NA   Volatility Shares gap',t);}catch(e){log('NA   Volatility Shares error',t,e.message);if(/HTTP (403|429)\b/.test(e.message))blocked=true;}}}));log('NA   Volatility Shares',Object.keys(out).length+'/'+links.length,blocked?'stopped on source access response':'');return out;}

function timothyLinks(h,names){const wanted=new Map(names.filter(x=>x&&x[2]===1&&/^Timothy Plan /i.test(x[1])).map(x=>[x[1].slice(13),x[0]])),out={};for(const m of h.matchAll(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)){const text=m[2].replace(/<[^>]*>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/\s+/g,' ').trim().replace(/^NEW\s+/,'');const t=wanted.get(text);if(!t)continue;let u;try{u=new URL(m[1],'https://timothyplan.com/')}catch(e){continue}if(u.origin!=='https://timothyplan.com'||!/^\/our-etfs\/summary-etf-[a-z]+\.php$/.test(u.pathname)||u.search||u.hash)continue;out[t]=u.href;}return out;}
function parseTimothy(h,t,src){const clean=s=>s.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim();const ids=[...h.matchAll(/<tr\b[^>]*>\s*<td\b[^>]*>\s*Ticker\s*<\/td>\s*<td\b[^>]*>([\s\S]*?)<\/td>\s*<\/tr>/gi)];if(ids.length!==1||clean(ids[0][1])!==t)return null;const blocks=[...h.matchAll(/<h3\b[^>]*>\s*Fund Details([\s\S]*?)<\/h3>\s*(<table\b[^>]*>[\s\S]*?<\/table>)/gi)];if(blocks.length!==1)return null;const b=blocks[0],dm=clean(b[1]).match(/\(as of (\d{1,2})\/(\d{1,2})\/(20\d{2})\)?$/);if(!dm)return null;const d=dm[3]+'-'+dm[1].padStart(2,'0')+'-'+dm[2].padStart(2,'0'),date=new Date(d+'T00:00:00Z');if(!Number.isFinite(+date)||date.toISOString().slice(0,10)!==d)return null;const amounts=[...b[2].matchAll(/<tr\b[^>]*>\s*<td\b[^>]*>\s*Net Assets\s*<\/td>\s*<td\b[^>]*>([\s\S]*?)<\/td>\s*<\/tr>/gi)];if(amounts.length!==1)return null;const value=clean(amounts[0][1]);if(!/^\$(?:\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$/.test(value))return null;const v=Number(value.replace(/[$,]/g,''));if(!Number.isFinite(v)||v<=0)return null;return{v:Math.round(v),asOf:d,issuer:'Timothy Plan',src,currency:'USD',sourceValue:value,sourcePrecisionUSD:0.01};}


async function timothy(names,log){const links=Object.entries(timothyLinks(await get('https://timothyplan.com/',40000),names)),out={};let i=0,blocked=false;await Promise.all(Array.from({length:2},async()=>{while(i<links.length&&!blocked){const[t,url]=links[i++];try{const r=parseTimothy(await get(url,30000),t,url);if(r)out[t]=r;else log('NA   Timothy Plan gap',t);}catch(e){log('NA   Timothy Plan error',t,e.message);if(/HTTP (403|429)\b/.test(e.message))blocked=true;}}}));log('NA   Timothy Plan',Object.keys(out).length+'/'+links.length,blocked?'stopped on source access response':'');return out;}

async function pool(items, n, fn){ const res = []; let i = 0; await Promise.all(Array.from({length: n}, async () => { while(i < items.length){ const k = items[i++]; try{ const r = await fn(k); if(r) res.push([k, r]); }catch(e){} } })); return res; }
module.exports = async function fetchNetAssets(root, log = console.log){ const out = {};
  for(const [name, fn] of [['iShares', ishares], ['SSGA', ssga]]){ try{ const r = await fn(); Object.assign(out, r); log('NA   ' + name, Object.keys(r).length); }catch(e){ log('NA   ' + name + ' error', e.message); } }
  let names = []; try{ names = JSON.parse(fs.readFileSync(path.join(root, 'securities-us.json'), 'utf8')).d || []; }catch(e){}
  const etfs = names.filter(x => x && x[2] === 1);
  try{ const r = parseNeos(await get('https://neosfunds.com/', 40000), etfs); Object.assign(out, r); log('NA   NEOS', Object.keys(r).length); }catch(e){ log('NA   NEOS error', e.message); }
  try{ Object.assign(out,await yieldmax(etfs,log)); }catch(e){log('NA   YieldMax error',e.message);}
  try{const r=parseDefiance(JSON.parse(await get('https://www.defianceetfs.com/wp-json/defiance/v1/etfs-explore',40000)),etfs);Object.assign(out,r);log('NA   Defiance',Object.keys(r).length);}catch(e){log('NA   Defiance error',e.message);}
  try{Object.assign(out,await vista(etfs,log));}catch(e){log('NA   VistaShares error',e.message);}
  try{Object.assign(out,await volshares(etfs,log));}catch(e){log('NA   Volatility Shares error',e.message);}
  try{Object.assign(out,await timothy(etfs,log));}catch(e){log('NA   Timothy Plan error',e.message);}
  for(const [name, rx, fn] of [['Global X', /^Global X\b/i, globalx], ['First Trust', /^(First Trust|FT )/i, firsttrust]]){ const ts = etfs.filter(x => rx.test(x[1])).map(x => x[0]).filter(t => !out[t]);
    try{ const r = await pool(ts, 6, fn); r.forEach(([t, e]) => { out[t] = e; }); log('NA   ' + name, r.length + '/' + ts.length); }catch(e){ log('NA   ' + name + ' error', e.message); } }
  return out; };
