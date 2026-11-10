#!/usr/bin/env node
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const grab=(a,b)=>{const i=html.indexOf(a),j=html.indexOf(b,i);assert(i>=0&&j>i,'tracking implementation markers missing');return html.slice(i,j)};
const ctx={Intl,Date,Set,Map,Math,Number,console,US_HOLIDAYS:new Set(['2026-12-25']),US_EARLY:new Set(['2026-11-27']),tzFmt:{},quotes:{},etfP0:{},I18n:{language:'en'},haltOf:q=>q.hlt||null,iq:it=>ctx.quotes[it.sym]||null,addDays:(d,n)=>new Date(Date.parse(d+'T12:00:00Z')+n*864e5).toISOString().slice(0,10)};
vm.createContext(ctx);
vm.runInContext(grab('function zoned(', '// ---- US trading sessions')+grab('function usSession(', '// usable pre-market quote')+grab('function preOf(', '// v65: small extended-hours line')+grab('function etfEstimate(', 'const etfInst ='),ctx);
const d={asOf:'2026-11-09',rows:[['AAA','Alpha',60],['BBB','Beta',40]]},its=d.rows.map(x=>({sym:x[0]}));
ctx.etfP0['TST|2026-11-09']={p:{AAA:100,BBB:100}};
let tests=0;const close=(a,b)=>assert(Math.abs(a-b)<1e-8,`${a} != ${b}`);
function setup(now,session){const t=Date.parse(now),reg=Date.parse(session==='reg'||session==='post'||now.startsWith('2026-11-11T03')?'2026-11-10T20:59:00Z':'2026-11-09T20:59:00Z');ctx.quotes={AAA:{price:105,prev:100,ts:session==='reg'?t-10000:reg},BBB:{price:100,prev:100,ts:session==='reg'?t-10000:reg}};if(session!=='reg'){ctx.quotes.AAA.pre={price:108,ts:t-10000,kind:session==='post'?'after':session};ctx.quotes.BBB.pre={price:100,ts:t-10000,kind:session==='post'?'after':session};}return t;}
for(const [now,phase] of [['2026-11-10T13:00:00Z','pre'],['2026-11-10T20:00:00Z','reg'],['2026-11-10T22:00:00Z','post'],['2026-11-11T03:00:00Z','night'],['2026-11-10T07:00:00Z','night']]){
 const t=setup(now,phase),e=ctx.etfEstimate('TST',d,its,t);assert.equal(e.session,phase);close(e.weights.reduce((a,b)=>a+b,0),100);close(e.pct,3);close(e.covered,100);assert(!e.partial);close(e.weights[0],phase==='reg'?63/103*100:64.8/104.8*100);if(phase!=='reg')close(e.extPct,(104.8/103-1)*100);tests++;
}
let t=setup('2026-11-10T13:00:00Z','pre');ctx.quotes.AAA.pre.ts=t-16*60000;let e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);close(e.weights[0],63/103*100);assert(e.partial);tests++;
t=setup('2026-11-10T13:00:00Z','pre');ctx.quotes.AAA.pre.kind='night';e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);tests++;
t=setup('2026-11-10T13:00:00Z','pre');ctx.quotes.AAA.pre.ts=t+121000;e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);tests++;
t=setup('2026-11-10T20:00:00Z','reg');delete ctx.etfP0['TST|2026-11-09'].p.AAA;e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);assert(e.partial);ctx.etfP0['TST|2026-11-09'].p.AAA=100;tests++;
t=setup('2026-11-10T20:00:00Z','reg');ctx.quotes.AAA.hlt='Halted';e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);assert(e.partial);tests++;
t=setup('2026-11-10T20:00:00Z','reg');ctx.quotes.AAA.ts=t-16*60000;e=ctx.etfEstimate('TST',d,its,t);close(e.covered,40);tests++;
ctx.quotes={};e=ctx.etfEstimate('TST',d,its,t);assert.equal(e.pct,null);assert(e.partial);close(e.weights[0],60);tests++;
assert.equal(ctx.usSession(new Date('2026-12-25T17:00:00Z')),'closed');assert.equal(ctx.usSession(new Date('2026-11-27T19:00:00Z')),'post');tests++;
assert(html.includes('etfEstimateHtml(estimate)'),'estimate is not connected to the displayed fund');assert(html.includes('estimate.weights'),'weights are not connected to the estimate');assert(html.includes('etfItems(etfData[etfUi.sel]).filter'),'selected fund is not in the live quote subscriptions');tests++;
const report={checked_at:new Date().toISOString(),logic_tests:tests,phases:['pre','regular','after','night'],live_sample:null,warnings:[]};
async function main(){
 if(process.argv.includes('--live')){
  const issuer=JSON.parse(fs.readFileSync(path.join(root,'holdings/issuer.json'),'utf8'));
  assert(issuer.funds&&Object.keys(issuer.funds).length,'issuer snapshot missing');
  for(const [ticker,fund] of Object.entries(issuer.funds)){assert(/^\d{4}-\d{2}-\d{2}/.test(fund.asOf),ticker+' invalid snapshot date');assert(fund.rows.every(r=>Number.isFinite(+r[2])&&+r[2]>0),ticker+' invalid weights');}
  const age=Date.now()-Date.parse(issuer.generated||issuer.generatedAt||'');if(!Number.isFinite(age)||age>36*3600e3)report.warnings.push('issuer file generation is missing or over 36 hours old');
  const symbols=[...new Set(Object.values(issuer.funds).flatMap(f=>f.rows.slice(0,2).map(r=>r[0])).filter(s=>/^[A-Z]{1,5}$/.test(s)))].slice(0,40);
  const url='https://savage-orderbook.oriboyianjo.workers.dev/night?s='+symbols.join(',');
  const r=await fetch(url,{signal:AbortSignal.timeout(20000)});assert(r.ok,'night quote route HTTP '+r.status);const j=await r.json();assert(j.quotes&&typeof j.quotes==='object','night quote route shape changed');
  const session=ctx.usSession(new Date()),quotes=Object.entries(j.quotes).filter(([,q])=>q.price>0&&q.ts>0),fresh=quotes.filter(([,q])=>Date.now()-q.ts<=15*60000&&q.ts<=Date.now()+120000);
  report.live_sample={source:url,session,requested:symbols.length,quotes:quotes.length,current_quotes:fresh.length,symbols:fresh.map(([s])=>s),scope:'Two largest labelled US holdings per issuer fund, deduplicated; not a full-fund coverage audit.'};
  if(session==='night'&&!fresh.length)throw new Error('No current overnight trade in the representative sample');
  if(session==='night'&&fresh.length<symbols.length)report.warnings.push('Partial current overnight quote coverage; unavailable/stale holdings must not be called live');
 }
 fs.writeFileSync(path.join(root,'etf-tracking-check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
}
main().catch(e=>{report.error=e.message;fs.writeFileSync(path.join(root,'etf-tracking-check.json'),JSON.stringify(report,null,2));console.error(e.stack);process.exitCode=1});
