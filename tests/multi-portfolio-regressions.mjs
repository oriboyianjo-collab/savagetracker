import { chromium } from '/home/box/.local/lib/node_modules/playwright/index.mjs';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname);
const OUT = '/workspace/outputs';
const PORT = 8771;
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.map': 'application/json',
};

const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://127.0.0.1');
  let p = decodeURIComponent(u.pathname);
  if (p === '/') p = '/index.html';
  const fp = path.normalize(path.join(ROOT, p));
  if (!fp.startsWith(ROOT)) { res.writeHead(403); res.end(); return; }
  fs.readFile(fp, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(data);
  });
});
await new Promise(r => server.listen(PORT, '127.0.0.1', r));
const origin = `http://127.0.0.1:${PORT}/index.html`;

function tx(partial){ return Object.assign({id:'t-'+Math.random().toString(36).slice(2,8), ts:Date.now(), fee:0, note:'DEMO FAKE'}, partial); }
function settings(){ return {commission:{USD:{fixed:0,pct:0,min:7.5,perShare:0.01,max:0,smallBelow:2000,smallFee:7}, ILS:{fixed:0,pct:0.08,min:4.65,perShare:0,max:0,smallBelow:0,smallFee:0}}, fxFeePct:0, taxRate:25, benchmarks:['SPY'], refreshSec:0, hideAmounts:false, hideHistory:false, hideTxHistory:false}; }
function quotes(){
  const ts = Date.now();
  return {
    AAPL:{price:200, prev:198, name:'Apple Inc', ts},
    MSFT:{price:400, prev:395, name:'Microsoft', ts},
    NVDA:{price:180, prev:175, name:'NVIDIA', ts},
    VOO:{price:500, prev:498, name:'Vanguard S&P 500', ts},
    JPM:{price:250, prev:248, name:'JPMorgan', ts},
    TSLA:{price:200, prev:190, name:'Tesla Demo', ts},
    AMD:{price:150, prev:148, name:'AMD Demo', ts},
  };
}
function assets(){ return {
  AAPL:{name:'Apple Inc', type:'stock', currency:'USD'},
  MSFT:{name:'Microsoft', type:'stock', currency:'USD'},
  NVDA:{name:'NVIDIA', type:'stock', currency:'USD'},
  VOO:{name:'Vanguard S&P 500', type:'etf', currency:'USD'},
  JPM:{name:'JPMorgan', type:'stock', currency:'USD'},
  TSLA:{name:'Tesla Demo', type:'stock', currency:'USD'},
  AMD:{name:'AMD Demo', type:'stock', currency:'USD'},
}; }
function fx(){ return {rate:3.7, prev:3.69, updated:Date.now(), source:'demo'}; }

function oldSingleState(){
  return {
    version:2,
    txs:[
      tx({id:'old-d', ts:1, type:'deposit', date:'2024-01-02', currency:'USD', amount:10000, note:'DEMO opening cash'}),
      tx({id:'old-a', ts:2, type:'buy', date:'2024-01-03', symbol:'AAPL', currency:'USD', qty:20, price:150, fee:7.5, note:'DEMO AAPL'}),
      tx({id:'old-m', ts:3, type:'buy', date:'2024-01-04', symbol:'MSFT', currency:'USD', qty:10, price:300, fee:7.5, note:'DEMO MSFT'}),
      tx({id:'old-div', ts:4, type:'dividend', date:'2024-06-01', currency:'USD', amount:40, symbol:'AAPL', note:'DEMO dividend'}),
    ],
    assets: assets(),
    quotes: quotes(),
    manual:{},
    fx: fx(),
    settings: settings(),
    lastRefresh: Date.now(),
    refreshErrors:0,
    hiddenClosed:[],
    removedSymbols:[],
    importMap:{},
  };
}

function book(id, name, rows){
  return {id, name, txs: rows, hiddenClosed:[], removedSymbols:[], importMap:{}};
}

function multiPorts(){
  const main = book('p-main', 'התיק הראשי', [
    tx({id:'m-d', ts:10, type:'deposit', date:'2024-02-01', currency:'USD', amount:6500, note:'DEMO main cash'}),
    tx({id:'m-a', ts:11, type:'buy', date:'2024-02-02', symbol:'AAPL', currency:'USD', qty:10, price:200, fee:7.5, note:'DEMO'}),
    tx({id:'m-s', ts:12, type:'buy', date:'2024-02-02', symbol:'MSFT', currency:'USD', qty:6, price:400, fee:7.5, note:'DEMO'}),
    tx({id:'m-n', ts:13, type:'buy', date:'2024-02-03', symbol:'NVDA', currency:'USD', qty:10, price:180, fee:7.5, note:'DEMO'}),
  ]);
  const pen = book('p-pen', 'פנסיה', [
    tx({id:'p-d', ts:20, type:'deposit', date:'2024-03-01', currency:'USD', amount:5200, note:'DEMO pension cash'}),
    tx({id:'p-v', ts:21, type:'buy', date:'2024-03-02', symbol:'VOO', currency:'USD', qty:6, price:500, fee:7.5, note:'DEMO'}),
    tx({id:'p-j', ts:22, type:'buy', date:'2024-03-02', symbol:'JPM', currency:'USD', qty:8, price:250, fee:7.5, note:'DEMO'}),
  ]);
  const tryB = book('p-try', 'ניסיונות', [
    tx({id:'y-d', ts:30, type:'deposit', date:'2024-04-01', currency:'USD', amount:1300, note:'DEMO try cash'}),
    tx({id:'y-t', ts:31, type:'buy', date:'2024-04-02', symbol:'TSLA', currency:'USD', qty:4, price:200, fee:7.5, note:'DEMO'}),
    tx({id:'y-a', ts:32, type:'buy', date:'2024-04-02', symbol:'AMD', currency:'USD', qty:2, price:150, fee:7.5, note:'DEMO'}),
  ]);
  return {version:1, books:[main, pen, tryB], activeId:'p-main', alertId:'p-main'};
}

function storageFrom(map){
  return Object.entries(map).map(([k,v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(typeof v==='string'?v:JSON.stringify(v))});`).join('\n');
}

const browser = await chromium.launch({
  executablePath: '/usr/bin/google-chrome',
  args: ['--disable-gpu', '--no-sandbox'],
});

let failed = 0;
const results = [];
function ok(name, cond, detail=''){
  if(!cond){ failed++; results.push('FAIL '+name+(detail?' — '+detail:'')); console.log('FAIL', name, detail); }
  else { results.push('PASS '+name); console.log('PASS', name); }
}

async function newContext(initStorageFn, extraInit=''){
  const context = await browser.newContext({
    viewport: { width: 412, height: 915 },
    deviceScaleFactor: 2,
    locale: 'he-IL',
  });
  const errors = [];
  context.on('pageerror', e => errors.push(String(e)));
  await context.addInitScript(initStorageFn + `;
    localStorage.setItem('portfolioTracker.theme','dark');
    localStorage.setItem('portfolioTracker.dispCur','ILS');
    localStorage.setItem('portfolioTracker.returnMethod','TWR');
    try{ navigator.serviceWorker.getRegistrations().then(rs=>rs.forEach(r=>r.unregister())); }catch(e){}
    ${extraInit}
  `);
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.startsWith(`http://127.0.0.1:${PORT}`)) return route.continue();
    if (u.startsWith('https://cdn.jsdelivr.net/')) return route.continue();
    return route.abort();
  });
  return {context, page, errors};
}

async function boot(page){
  await page.goto(origin, {waitUntil:'domcontentloaded'});
  await page.waitForFunction(() => window.__portfolio && window.__portfolio.ports && document.getElementById('portPick'));
  await page.evaluate((q) => {
    const P = window.__portfolio;
    P.state.quotes = Object.assign({}, P.state.quotes||{}, q);
    P.state.fx = Object.assign({}, P.state.fx||{}, {rate:3.7, prev:3.69, updated:Date.now(), source:'demo'});
    P.state.settings.refreshSec = 0;
    P.save();
    P.renderAll();
  }, quotes());
  await page.waitForTimeout(250);
}

try {
  // ---------- 1. migration from old single-book localStorage ----------
  {
    const old = oldSingleState();
    const {context, page, errors} = await newContext(`
      localStorage.removeItem('portfolioTracker.ports.v1');
      localStorage.removeItem('portfolioTracker.preMulti.v1');
      ${storageFrom({'portfolioTracker.v2': old})}
    `);
    await boot(page);
    const info = await page.evaluate(() => {
      const P = window.__portfolio;
      const bak = localStorage.getItem(P.PORTS_BAK);
      let bakKeys = null; try{ bakKeys = bak && JSON.parse(bak); }catch(e){}
      return {
        books: P.ports.books.map(b => ({id:b.id, name:b.name, nTx:b.txs.length, ids:b.txs.map(t=>t.id)})),
        active: P.ports.activeId,
        alert: P.ports.alertId,
        viewName: P.activePortName(),
        nStateTx: P.state.txs.length,
        hasBackup: !!bak,
        bakHasV2: !!(bakKeys && bakKeys.keys && bakKeys.keys['portfolioTracker.v2']),
        switcher: document.getElementById('psName')?.textContent,
        pickH: document.getElementById('portPick')?.getBoundingClientRect().height,
        perfH: document.getElementById('btnPerfTop')?.getBoundingClientRect().height,
      };
    });
    ok('migration creates one book named התיק הראשי', info.books.length===1 && info.books[0].name==='התיק הראשי');
    ok('migration keeps all old transactions', info.books[0].nTx===4 && info.nStateTx===4 && info.books[0].ids.includes('old-a'));
    ok('one-time backup of old v2 key exists', info.hasBackup && info.bakHasV2);
    ok('switcher shows התיק הראשי', info.switcher==='התיק הראשי' && info.viewName==='התיק הראשי');
    ok('switcher pill is about half the height of ביצועים', info.pickH>=16 && info.pickH<=24 && info.perfH>=32 && info.pickH < info.perfH*0.7);
    ok('no JS error after migration', errors.length===0, errors.join(' | '));
    await context.close();
  }

  // ---------- 2. screenshots + CRUD + combined + alerts + export/import ----------
  {
    const ports = multiPorts();
    const snap = Object.assign(oldSingleState(), {txs: ports.books[0].txs, quotes: quotes(), assets: assets(), fx: fx(), settings: settings()});
    const {context, page, errors} = await newContext(`
      ${storageFrom({
        'portfolioTracker.v2': snap,
        'portfolioTracker.ports.v1': ports,
      })}
    `);
    await boot(page);

    // Layout: pill to the right of ביצועים in RTL
    const layout = await page.evaluate(() => {
      const pick = document.getElementById('portPick').getBoundingClientRect();
      const perf = document.getElementById('btnPerfTop').getBoundingClientRect();
      return {pick, perf, pickRightOfPerf: pick.x > perf.x + perf.width - 1, noWideBar: !document.querySelector('.port-wide, .port-bar')};
    });
    ok('pill is immediately to the right of ביצועים', layout.pickRightOfPerf && Math.abs(layout.pick.left - layout.perf.right) < 20);
    ok('no wide switcher bar', layout.noWideBar);
    const pillText = await page.evaluate(() => { const s=document.getElementById('psName').getBoundingClientRect(); return {text:document.getElementById('psName').textContent, w:s.width}; });
    ok('pill label is visible', pillText.text==='התיק הראשי' && pillText.w>=36, JSON.stringify(pillText));

    await page.screenshot({path: path.join(OUT, 'mp-real-portfolio.png'), fullPage:false});
    ok('wrote mp-real-portfolio.png', fs.existsSync(path.join(OUT, 'mp-real-portfolio.png')));

    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    const menu = await page.evaluate(() => {
      const m = document.getElementById('portMenu');
      const items = [...m.querySelectorAll('button')].map(b => b.textContent.replace(/\s+/g,' ').trim());
      return {hidden:m.hidden, items, hasAll: items.some(t=>t.includes('כל התיקים יחד')), hasNew: items.some(t=>t.includes('תיק חדש')), hasRename: items.some(t=>t.includes('שינוי שם')), hasDelete: items.some(t=>t.includes('מחיקה')), check: [...m.querySelectorAll('button.on')].map(b=>b.textContent)};
    });
    ok('dropdown lists combined, books, new, rename, delete', menu.hasAll && menu.hasNew && menu.hasRename && menu.hasDelete && menu.items.some(t=>t.includes('התיק הראשי')) && menu.items.some(t=>t.includes('פנסיה')) && menu.items.some(t=>t.includes('ניסיונות')));
    ok('active book is checked', menu.check.some(t=>t.includes('התיק הראשי') && t.includes('✓')));
    await page.screenshot({path: path.join(OUT, 'mp-real-dropdown.png'), fullPage:false});

    // Combined view
    await page.click(`#portMenu [data-port="__all__"]`);
    await page.waitForTimeout(200);
    const comb = await page.evaluate(() => {
      const P = window.__portfolio;
      const S = P.computeAll();
      const aapl = S.positions.find(p=>p.sym==='AAPL');
      const tags = P.portTagsFor('AAPL');
      const allSyms = S.positions.map(p=>p.sym).sort();
      return {
        name: P.activePortName(),
        isAll: P.isAllView(),
        nPos: S.positions.length,
        allSyms,
        aaplQty: aapl && aapl.qty,
        aaplAvg: aapl && aapl.avg,
        header: document.querySelector('.hcard, #hdrEq, .hc-v') ? document.body.innerText.slice(0,0) : '',
        psName: document.getElementById('psName')?.textContent,
        hasPtag: !!document.querySelector('.ptag'),
        eq: P.bookEquity(P.PORT_ALL),
        main: P.bookEquity('p-main'),
        pen: P.bookEquity('p-pen'),
        tryv: P.bookEquity('p-try'),
      };
    });
    ok('combined view selected', comb.isAll && comb.psName.includes('כל התיקים יחד'));
    ok('combined holds union of symbols', ['AAPL','MSFT','NVDA','VOO','JPM','TSLA','AMD'].every(s=>comb.allSyms.includes(s)));
    const sum = (comb.main||0)+(comb.pen||0)+(comb.tryv||0);
    ok('combined equity is sum of books', comb.eq!=null && Math.abs(comb.eq - sum) < 2, `eq=${comb.eq} sum=${sum}`);
    // AAPL only in main, qty 10, avg 200. We'll add a second AAPL book below for weighted cost.
    await page.screenshot({path: path.join(OUT, 'mp-real-combined.png'), fullPage:false});

    // Adding a trade in combined is blocked
    const blocked = await page.evaluate(() => {
      const before = window.__portfolio.state.txs.length;
      window.__portfolio.openTxForm('buy');
      const sheetOpen = document.getElementById('sheet')?.classList.contains('open');
      return {before, after: window.__portfolio.state.txs.length, sheetOpen, isAll: window.__portfolio.isAllView()};
    });
    ok('combined add-trade is blocked (no sheet)', blocked.isAll && blocked.after===blocked.before && !blocked.sheetOpen);
    await page.evaluate(() => { const t=document.getElementById('toast'); if(t){ t.classList.remove('show'); t.textContent=''; } });

    // Performance: no switcher, name label, computes for selected (combined)
    await page.click('#btnPerfTop');
    await page.waitForSelector('#tab-perf.on, #tab-perf.tab.on, section#tab-perf');
    await page.waitForTimeout(400);
    const perf = await page.evaluate(() => {
      const tab = document.getElementById('tab-perf');
      return {
        on: tab.classList.contains('on') || tab.style.display!=='none',
        label: document.getElementById('perfPortLbl')?.textContent || '',
        hasSwitcher: !!tab.querySelector('#portPick, .port-switch'),
      };
    });
    ok('performance has name label and no switcher', perf.label.includes('כל התיקים יחד') && perf.label.includes('TWR') && !perf.hasSwitcher);
    await page.screenshot({path: path.join(OUT, 'mp-real-performance.png'), fullPage:false});

    // Back to portfolio, switch to main, then performance for one book
    await page.click('nav.bottom [data-tab="portfolio"]');
    await page.waitForTimeout(150);
    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click('#portMenu [data-port="p-main"]');
    await page.waitForTimeout(200);
    await page.click('#btnPerfTop');
    await page.waitForTimeout(300);
    const perfMain = await page.evaluate(() => document.getElementById('perfPortLbl')?.textContent||'');
    ok('performance label follows selected book', perfMain.includes('התיק הראשי') && !perfMain.includes('כל התיקים'));

    // Alerts settings picker
    await page.click('#btnSet');
    await page.waitForSelector('#alRow');
    await page.click('#alRow');
    await page.waitForSelector('#alPortPick');
    const alClosed = await page.evaluate(() => ({
      title: document.querySelector('#alPortSec h4')?.textContent,
      name: document.getElementById('alPortName')?.textContent,
      hold: window.__portfolio.alSyms().hold.slice().sort(),
    }));
    ok('alerts picker present and follows alert portfolio', alClosed.title.includes('תיק להתראות') && alClosed.name.includes('התיק הראשי'));
    ok('alerts hold symbols are main book only', alClosed.hold.join(',')==='AAPL,MSFT,NVDA', alClosed.hold.join(','));
    await page.screenshot({path: path.join(OUT, 'mp-real-alerts.png'), fullPage:false});

    // Change alerts portfolio to combined, hold becomes union; viewing stays main
    await page.click('#alPortPick');
    await page.waitForSelector('#alPortMenu:not([hidden])');
    await page.screenshot({path: path.join(OUT, 'mp-real-alerts-dropdown.png'), fullPage:false});
    await page.click(`#alPortMenu [data-port="__all__"]`);
    await page.waitForTimeout(200);
    const alAll = await page.evaluate(() => ({
      alertName: window.__portfolio.alertPortName(),
      viewName: window.__portfolio.activePortName(),
      hold: window.__portfolio.alSyms().hold.slice().sort(),
      isAllView: window.__portfolio.isAllView(),
    }));
    ok('alerts combined is union and does not change viewed book', alAll.alertName.includes('כל התיקים יחד') && alAll.viewName.includes('התיק הראשי') && !alAll.isAllView);
    ok('alerts combined hold is deduped union', ['AAPL','AMD','JPM','MSFT','NVDA','TSLA','VOO'].every(s=>alAll.hold.includes(s)) && alAll.hold.length===7, alAll.hold.join(','));

    // Create / rename / delete
    await page.click('nav.bottom [data-tab="portfolio"]');
    await page.waitForTimeout(150);
    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click('#portMenu [data-port-act="add"]');
    await page.waitForSelector('#portNameDialog');
    await page.fill('#portNameInput', 'נייר חדש');
    await page.click('#portNameDialog button[value="ok"]');
    await page.waitForTimeout(300);
    const afterAdd = await page.evaluate(() => ({
      names: window.__portfolio.ports.books.map(b=>b.name),
      active: window.__portfolio.activePortName(),
      n: window.__portfolio.ports.books.length,
      nTx: window.__portfolio.state.txs.length,
    }));
    ok('can create a new empty portfolio and switch to it', afterAdd.names.includes('נייר חדש') && afterAdd.active==='נייר חדש' && afterAdd.n===4 && afterAdd.nTx===0);

    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click('#portMenu [data-port-act="rename"]');
    await page.waitForSelector('#portNameDialog');
    await page.fill('#portNameInput', 'תיק בדיקה');
    await page.click('#portNameDialog button[value="ok"]');
    await page.waitForTimeout(200);
    const afterRen = await page.evaluate(() => window.__portfolio.activePortName());
    ok('can rename the selected portfolio', afterRen==='תיק בדיקה');

    page.once('dialog', d => d.accept());
    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click('#portMenu [data-port-act="delete"]');
    await page.waitForTimeout(300);
    const afterDel = await page.evaluate(() => ({
      names: window.__portfolio.ports.books.map(b=>b.name),
      n: window.__portfolio.ports.books.length,
    }));
    ok('can delete a portfolio after confirm', afterDel.n===3 && !afterDel.names.includes('תיק בדיקה') && !afterDel.names.includes('נייר חדש'));

    // Cannot delete last: reduce to one then try
    // skip actually deleting the demo books for later math; instead call delete when only one remains in a sub-evaluate after cloning? We'll test the toast path by temporarily leaving one book in a separate context later.

    // Weighted cost: add AAPL to pension at a different price, then combined
    await page.evaluate(() => {
      const P = window.__portfolio;
      const pen = P.ports.books.find(b=>b.id==='p-pen');
      pen.txs.push({id:'p-aapl', ts:25, type:'buy', date:'2024-03-10', symbol:'AAPL', currency:'USD', qty:5, price:200, fee:0, note:'DEMO overlap'});
      // need cash: the buy reduces cash; deposit already covers approx
      P.persistPorts();
    });
    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click(`#portMenu [data-port="__all__"]`);
    await page.waitForTimeout(200);
    const wavg = await page.evaluate(() => {
      const P = window.__portfolio;
      const S = P.computeAll();
      const a = S.positions.find(p=>p.sym==='AAPL');
      return {qty:a && a.qty, avg:a && a.avg, tags:P.portTagsFor('AAPL')};
    });
    ok('combined AAPL qty is 15 (10+5)', Math.abs((wavg.qty||0)-15)<1e-6, String(wavg.qty));
    ok('combined AAPL average cost includes fees (10*(200+7.5/10)+5*200)/15 = 200.5', Math.abs((wavg.avg||0)-200.5)<1e-6, String(wavg.avg));
    ok('combined AAPL is tagged with both books', wavg.tags.includes('התיק הראשי') && wavg.tags.includes('פנסיה'), JSON.stringify(wavg.tags));

    // Better weighted-cost: different prices 100 and 200
    // Use a clean compute via temporary books in evaluate (don't mess screenshots already taken)
    const w2 = await page.evaluate(() => {
      const P = window.__portfolio;
      const main = P.ports.books.find(b=>b.id==='p-main');
      const aaplBuy = main.txs.find(t=>t.id==='m-a');
      const old = aaplBuy.price;
      aaplBuy.price = 100;
      P.persistPorts();
      P.applyActiveToState();
      const S = P.computeAll();
      const a = S.positions.find(p=>p.sym==='AAPL');
      const result = {qty:a&&a.qty, avg:a&&a.avg};
      aaplBuy.price = old;
      P.persistPorts();
      P.applyActiveToState();
      P.renderAll();
      return result;
    });
    ok('combined weighted avg includes fees (10*100+7.5 + 5*200) / 15 = 133.833', Math.abs((w2.avg||0) - (1000+7.5+1000)/15) < 0.02, String(w2.avg));
    ok('qty still 15 after price tweak', Math.abs((w2.qty||0)-15)<1e-6);

    // Export / import round trip
    const round = await page.evaluate(() => {
      const P = window.__portfolio;
      const before = JSON.parse(JSON.stringify({books:P.ports.books.map(b=>({id:b.id,name:b.name,n:b.txs.length})), active:P.ports.activeId, alert:P.ports.alertId}));
      const payload = P.exportPayload();
      // wipe in place then reimport
      P.importPayload({app:'portfolio-tracker', version:2, txs:[]}, {force:true});
      const mid = P.ports.books.map(b=>({name:b.name,n:b.txs.length}));
      P.importPayload(payload, {force:true});
      P.renderAll();
      const after = {books:P.ports.books.map(b=>({id:b.id,name:b.name,n:b.txs.length})), active:P.ports.activeId, alert:P.ports.alertId, version:payload.version, hasPorts:!!payload.ports};
      return {before, mid, after, payloadVersion:payload.version, nPayloadBooks:payload.ports.books.length};
    });
    ok('export is version 3 and includes all portfolios', round.payloadVersion===3 && round.nPayloadBooks>=3);
    ok('import of empty old backup becomes a single empty main book', round.mid.length===1 && round.mid[0].n===0);
    ok('re-import of new backup restores all books', JSON.stringify(round.before.books)===JSON.stringify(round.after.books));

    // Old single-portfolio backup import
    const oldImp = await page.evaluate((oldJson) => {
      const P = window.__portfolio;
      P.importPayload(oldJson, {force:true});
      P.renderAll();
      return {
        n: P.ports.books.length,
        name: P.ports.books[0].name,
        ids: P.ports.books[0].txs.map(t=>t.id),
        nTx: P.state.txs.length,
      };
    }, oldSingleState());
    ok('old backup import replaces data with התיק הראשי and original txs', oldImp.n===1 && oldImp.name==='התיק הראשי' && oldImp.ids.includes('old-a') && oldImp.nTx===4);

    // Privacy toggle still works
    const privacy = await page.evaluate(() => {
      const before = window.__portfolio.state.settings.hideAmounts;
      document.getElementById('btnEye').click();
      const mid = window.__portfolio.state.settings.hideAmounts;
      const hiddenUI = document.body.innerText.includes('••') || document.body.innerText.includes('✱') || window.__portfolio.state.settings.hideAmounts;
      document.getElementById('btnEye').click();
      const after = window.__portfolio.state.settings.hideAmounts;
      return {before, mid, after, hiddenUI};
    });
    ok('privacy eye toggle still flips hideAmounts', privacy.before===false && privacy.mid===true && privacy.after===false);

    // No JS errors across tabs
    const tabs = ['portfolio','tx','fin','news','market','watch'];
    for (const t of tabs){
      await page.click(`nav.bottom [data-tab="${t}"]`);
      await page.waitForTimeout(200);
    }
    await page.click('#btnSet');
    await page.waitForTimeout(200);
    await page.click('#btnPerfTop').catch(()=>{});
    // may be on settings; go portfolio then perf
    await page.click('nav.bottom [data-tab="portfolio"]');
    await page.waitForTimeout(150);
    await page.click('#btnPerfTop');
    await page.waitForTimeout(200);
    ok('no JS errors across tabs', errors.length===0, errors.join(' | '));

    await context.close();
  }

  // ---------- 3. cannot delete the last portfolio ----------
  {
    const ports = {version:1, books:[{id:'p-main', name:'התיק הראשי', txs:[], hiddenClosed:[], removedSymbols:[], importMap:{}}], activeId:'p-main', alertId:'p-main'};
    const {context, page, errors} = await newContext(`${storageFrom({'portfolioTracker.ports.v1': ports, 'portfolioTracker.v2': Object.assign(oldSingleState(),{txs:[]})})}`);
    await boot(page);
    const msgs = [];
    page.on('dialog', d => { msgs.push(d.message()); d.dismiss(); });
    await page.click('#portPick');
    await page.waitForSelector('#portMenu:not([hidden])');
    await page.click('#portMenu [data-port-act="delete"]');
    await page.waitForTimeout(400);
    const left = await page.evaluate(() => window.__portfolio.ports.books.length);
    const toast = await page.evaluate(() => document.body.innerText.includes('לא ניתן למחוק את התיק האחרון') || document.body.innerText.includes("Can't delete"));
    ok('cannot delete the last portfolio', left===1 && (toast || msgs.length===0), `left=${left} toast=${toast}`);
    ok('no JS error on last-delete', errors.length===0, errors.join(' | '));
    await context.close();
  }

} catch (e) {
  failed++;
  console.log('FAIL uncaught', e);
  results.push('FAIL uncaught '+e.stack);
}

await browser.close();
server.close();
fs.writeFileSync(path.join(OUT, 'mp-real-test-log.txt'), results.join('\n')+'\n');
console.log('\n'+(failed?failed+' failed':'All passed'));
process.exit(failed?1:0);
