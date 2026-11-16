'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const src=fs.readFileSync(__dirname+'/universal-consumer-insert.js','utf8');
const ih='c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083';
const url='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/report.htm';
const shard={schema_version:1,inventory_sha256:ih,as_of:'2026-11-15',symbols:{ABC:{cik:'0000000123',reports:{2027:{Q1:url}},ledger:[{slot:'2027-Q1',url,body_sha256:'a'.repeat(64),period_end:'2026-10-01',filing_date:'2026-11-01'}]}}};
const bytes=Buffer.from(JSON.stringify(shard)+'\n');const hash=crypto.createHash('sha256').update(bytes).digest('hex');
const manifest={schema_version:1,inventory_sha256:ih,as_of:'2026-11-15',symbols:{ABC:{cik:'0000000123',sha256:hash}}};
const delay=()=>new Promise(r=>setImmediate(r));
async function setup({wrongHash=false,badManifest=false,shardFail=false}={}){
 const calls=[];const m=JSON.parse(JSON.stringify(manifest));if(wrongHash)m.symbols.ABC.sha256='b'.repeat(64);if(badManifest)m.inventory_sha256='c'.repeat(64);
 const context={URL,Date,Set,Map,console:{warn:()=>{}},TextDecoder,crypto:crypto.webcrypto,REPORT_PDFS:{ABC:{2027:{Q1:'old',Q2:'keep'}}},document:{querySelectorAll:()=>[]},fetch:async u=>{calls.push(u);if(u==='report-links-all.json')return {ok:true,text:async()=>JSON.stringify(m)};if(shardFail)return {ok:false};return {ok:true,arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)}}};
 vm.createContext(context);vm.runInContext(src,context);await delay();return {context,calls};
}
(async()=>{
 let {context:c,calls}=await setup();assert.deepEqual(calls,['report-links-all.json']);assert.equal(c.reportYears('ABC')[2027].Q1,'old');await vm.runInContext("UNIVERSAL_REPORT_REQUESTS.get('ABC')",c);assert.equal(c.reportYears('ABC')[2027].Q1,url);assert.equal(c.reportYears('ABC')[2027].Q2,'keep');assert.equal(calls.length,2);c.reportYears('ABC');assert.equal(calls.length,2);console.log('ok lazy selected-symbol fetch, hash validation, merge and dedup');
 c.REPORT_PDFS.ABC={2027:{Q1:'late-old',Q2:'late-keep'}};assert.equal(c.reportYears('ABC')[2027].Q1,url);assert.equal(c.reportYears('ABC')[2027].Q2,'late-keep');console.log('ok dedicated late-loader race');
 for(const mode of [{wrongHash:true},{badManifest:true},{shardFail:true}]){
  const x=await setup(mode);x.context.reportYears('ABC');await vm.runInContext("UNIVERSAL_REPORT_REQUESTS.get('ABC')",x.context);assert.equal(x.context.reportYears('ABC')[2027].Q1,'old');console.log('ok preserves prior mapping on '+Object.keys(mode)[0]);
 }
 console.log('5 async consumer tests passed');
})().catch(e=>{console.error(e);process.exit(1)});
