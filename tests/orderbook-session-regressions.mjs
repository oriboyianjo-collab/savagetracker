// v331: the order-book header (obRchg) must show the CURRENT session's price + change (pre / after / overnight), from the same preOf source as 'מחיר נוכחי · pre'
import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const s=fs.readFileSync('index.html','utf8');
const cut=(a,b)=>{const i=s.indexOf(a),j=s.indexOf(b,i);assert.ok(i>=0&&j>i,'slice '+a);return s.slice(i,j);};
const els={obRchg:{innerHTML:''},posRchg:{innerHTML:'old'}};let session='pre';
const ctx={Number,Math,isFinite,
  // stand-in for preOf: an extended tick counts only inside its own session (the real preOf also checks the date/time)
  preOf:q=>q&&q.pre&&q.pre.kind===session?Object.assign({},q.pre):null,
  $:id=>els[id]||null,posReturnMode:'price',posLive:null,obVolDraw(){},marketOf:()=>'us',isCrypto:()=>false,assetOf:()=>({currency:'USD'}),
  convertCur:v=>v,cls:v=>v>0?'up':v<0?'down':'',fmtPct:v=>(v>0?'+':'')+v.toFixed(2)+'%',fmtMoneyRaw:v=>'$'+v.toFixed(2),fmtDate:d=>d,I18n:{p:(k,t)=>t},state:{quotes:{}}};
vm.createContext(ctx);
vm.runInContext(cut('function obSessQuote(','function obMount(')+cut('function renderPosRchg(','function updatePosLive(')+';this.obSessQuote=obSessQuote;this.renderPosRchg=renderPosRchg;this.setL=L=>{posLive=L};',ctx);
// Ori's case: prior close 49.26 (+0.39% regular), pre-market last 52.89
const q={price:49.26,prev:49.07,cur:'USD',pre:{price:52.89,chg:52.89-49.26,pct:(52.89/49.26-1)*100,ts:1,kind:'pre',vol:1.2e6}};
let r=ctx.obSessQuote(q);assert.equal(r.kind,'pre');assert.equal(r.price,52.89);assert.ok(Math.abs(r.pct-7.369)<0.01,'pre % vs prior close');
ctx.state.quotes.X=q;ctx.setL({sym:'X',base:49.07,day:true,intra:true,hcur:'USD'});ctx.renderPosRchg(49.26);
assert.match(els.obRchg.innerHTML,/\$52\.89/);assert.match(els.obRchg.innerHTML,/\+7\.37%/);assert.doesNotMatch(els.obRchg.innerHTML,/49\.26|\+0\.39%/,'header must not show the regular close in pre-market');
assert.match(els.obRchg.innerHTML,/data-ob-kind="pre"/);assert.equal(els.posRchg.innerHTML,'');
// after-hours: after price vs today's close
session='after';const qa={price:50,prev:49,pre:{price:51,chg:1,pct:2,ts:1,kind:'after'}};r=ctx.obSessQuote(qa);assert.deepEqual([r.kind,r.price,r.pct],['after',51,2]);
// regular session: a leftover extended tick is ignored -> regular last vs prior close
session='reg';r=ctx.obSessQuote(q);assert.equal(r.kind,'reg');assert.equal(r.price,49.26);assert.ok(Math.abs(r.pct-(49.26/49.07-1)*100)<1e-9);
ctx.renderPosRchg(49.26);assert.match(els.obRchg.innerHTML,/\$49\.26/);assert.match(els.obRchg.innerHTML,/data-ob-kind="reg"/);
// an iq() quote that already carries .ext is used as-is (instrument sheet path)
r=ctx.obSessQuote({price:10,prev:9,ext:{kind:'pre',price:11,chg:1,pct:10}});assert.deepEqual([r.kind,r.price,r.pct],['pre',11,10]);
assert.equal(ctx.obSessQuote(null),null);
// both writers of the header go through obSessQuote; the volume keeps its session tag (pre/after volume from CNBC ExtendedMktQuote, else 'last trading day')
assert.match(cut("{ const _oh = $('obRchg');",'v165:'),/obSessQuote\(q\)/);
assert.match(cut('function renderPosRchg(','function updatePosLive('),/obSessQuote\(state\.quotes\[L\.sym\]\)/);
assert.match(cut('function obVolDraw(','function obDraw('),/q\.ext\.kind==='pre'/);
console.log('PASS order book header follows the current session: pre/after price + change, regular fallback, live re-render paths');
