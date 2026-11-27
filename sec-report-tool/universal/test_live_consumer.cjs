'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const uni=fs.readFileSync(__dirname+'/universal-consumer-insert.js','utf8');
const liveSrc=fs.readFileSync(__dirname+'/live-consumer-insert.js','utf8');
const ih='c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083';
const today=new Date().toISOString().slice(0,10);
const u1='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/new.htm';
const u2='https://www.sec.gov/Archives/edgar/data/123/000119312526000002/other.htm';
const overlay=(slots,asOf='2026-11-20')=>({schema_version:1,inventory_sha256:ih,as_of:asOf,symbols:{ABC:{cik:'0000000123',
  reports:slots.reduce((o,[y,p,u])=>{(o[y]=o[y]||{})[p]=u;return o;},{}),
  ledger:slots.map(([y,p,u])=>({slot:y+'-'+p,url:u,body_sha256:'a'.repeat(64),period_end:'2026-09-26',filing_date:'2026-11-20'}))}}});
const delay=()=>new Promise(r=>setImmediate(r));
async function setup(body,{ok=true,universal={}}={}){
  const refreshed=[];
  const context={URL,Date,Set,Map,console:{warn:()=>{}},TextDecoder,crypto:require('crypto').webcrypto,
    REPORT_PDFS:{ABC:{2026:{Q1:'old-q1'}}},document:{querySelectorAll:()=>[]},
    fetch:async u=>u==='report-links-live.json'?{ok,text:async()=>typeof body==='string'?body:JSON.stringify(body)}:{ok:false}};
  vm.createContext(context);vm.runInContext(uni,context);
  Object.assign(universal,{});vm.runInContext('UNIVERSAL_REPORT_OVERRIDES='+JSON.stringify(universal),context);
  vm.runInContext(liveSrc,context);await delay();await delay();return context;
}
let count=0;async function test(name,fn){await fn();count++;console.log('ok '+name);}
(async()=>{
  await test('valid overlay adds a new slot and keeps the existing ones',async()=>{
    const c=await setup(overlay([['2026','Q3',u1]]));const y=c.reportYears('ABC');
    assert.equal(y[2026].Q3,u1);assert.equal(y[2026].Q1,'old-q1');});
  await test('overlay never replaces a slot the base or the universal data holds',async()=>{
    const c=await setup(overlay([['2026','Q1',u1],['2026','Q2',u2]]),{universal:{ABC:{2026:{Q2:'universal-q2'}}}});const y=c.reportYears('ABC');
    assert.equal(y[2026].Q1,'old-q1');assert.equal(y[2026].Q2,'universal-q2');});
  await test('company without overlay is unchanged',async()=>{
    const c=await setup(overlay([['2026','Q3',u1]]));assert.equal(c.reportYears('XYZ'),undefined);});
  for(const [label,mutate] of [
    ['wrong inventory',x=>x.inventory_sha256='b'.repeat(64)],
    ['future as_of',x=>x.as_of='2999-01-01'],
    ['wrong issuer path',x=>x.symbols.ABC.cik='0000000456'],
    ['foreign host',x=>{const e=x.symbols.ABC.ledger[0];e.url=e.url.replace('www.sec.gov','evil.test');x.symbols.ABC.reports[2026].Q3=e.url;}],
    ['extra field',x=>x.run='fetch(secrets)'],
    ['ledger mismatch',x=>x.symbols.ABC.ledger[0].url=u2]])
    await test('invalid overlay changes nothing: '+label,async()=>{
      const o=overlay([['2026','Q3',u1]]);mutate(o);const c=await setup(o);
      assert.equal(JSON.stringify(c.reportYears('ABC')),JSON.stringify({2026:{Q1:'old-q1'}}));});
  await test('missing file (404), corrupt JSON and oversize leave everything unchanged',async()=>{
    for(const args of [[overlay([['2026','Q3',u1]]),{ok:false}],['{not json',{}],['x'.repeat(600000),{}]]){
      const c=await setup(args[0],args[1]);assert.equal(JSON.stringify(c.reportYears('ABC')),JSON.stringify({2026:{Q1:'old-q1'}}));}});
  console.log(count+' live consumer tests passed');
})().catch(e=>{console.error(e);process.exit(1)});
