'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync(__dirname+'/universal-consumer-insert.js','utf8').split('(async function loadUniversalReports')[0];
const context={URL,Date,Set,Map,console,REPORT_PDFS:{}};vm.createContext(context);vm.runInContext(src,context);
function validate(x,p=[]){return context.validateUniversalReportIndex(vm.runInContext('('+JSON.stringify(x)+')',context),new Set(p));}
const url='https://www.sec.gov/Archives/edgar/data/123/000119312526000001/sample.htm';
const fixture=()=>({schema_version:1,inventory_sha256:'c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083',as_of:'2026-11-15',symbols:{ABC:{cik:'0000000123',reports:{2027:{Q1:url}},ledger:[{slot:'2027-Q1',url,body_sha256:'a'.repeat(64),period_end:'2026-10-03',filing_date:'2026-11-01'}]}}});
let count=0;function test(name,fn){fn();count++;console.log('ok '+name);}
function rejects(fn){assert.throws(fn);}
test('noncalendar fiscal year preserved',()=>assert.equal(validate(fixture()).ABC[2027].Q1,url));
test('third party accession prefix allowed',()=>assert.equal(validate(fixture()).ABC[2027].Q1,url));
test('existing verified slot eligible for replacement',()=>assert.equal(validate(fixture()).ABC[2027].Q1,url));
test('per-slot merge preserves unmatched and wins async loader race',()=>{context.REPORT_PDFS.ABC={2027:{Q1:'old',Q2:'keep'}};vm.runInContext('UNIVERSAL_REPORT_OVERRIDES='+JSON.stringify(validate(fixture())),context);assert.equal(context.reportYears('ABC')[2027].Q1,url);assert.equal(context.reportYears('ABC')[2027].Q2,'keep');context.REPORT_PDFS.ABC={2027:{Q1:'late-loader',Q2:'keep'}};assert.equal(context.reportYears('ABC')[2027].Q1,url);assert.equal(context.reportYears('ABC')[2027].Q2,'keep');});
test('no replacement means no old-link change',()=>{context.REPORT_PDFS.XYZ={2025:{FY:'unchanged'}};assert.equal(context.reportYears('XYZ')[2025].FY,'unchanged');});
test('empty output accepted without deleting previous map',()=>{let x=fixture();x.symbols={};assert.equal(Object.keys(validate(x)).length,0);});
test('successor registrant may link its confirmed predecessor filings',()=>{let x=fixture();const u='https://www.sec.gov/Archives/edgar/data/34088/000003408826000093/xom-20260630.htm';x.symbols.ABC.cik='0002115436';x.symbols.ABC.reports[2027].Q1=u;x.symbols.ABC.ledger[0].url=u;assert.equal(validate(x).ABC[2027].Q1,u);});
test('predecessor path not allowed for other issuers',()=>{let x=fixture();const u='https://www.sec.gov/Archives/edgar/data/34088/000003408826000093/xom-20260630.htm';x.symbols.ABC.reports[2027].Q1=u;x.symbols.ABC.ledger[0].url=u;rejects(()=>validate(x));});
for(const [label,change] of [
 ['wrong inventory',x=>x.inventory_sha256='b'.repeat(64)],
 ['wrong issuer path',x=>x.symbols.ABC.cik='0000000456'],
 ['future actual period',x=>x.symbols.ABC.ledger[0].period_end='2099-01-01'],
 ['unpublished filing date',x=>x.symbols.ABC.ledger[0].filing_date='2099-01-01'],
 ['nonexistent date',x=>x.symbols.ABC.ledger[0].period_end='2026-02-31'],
 ['bad hash',x=>x.symbols.ABC.ledger[0].body_sha256='z'.repeat(64)],
 ['missing ledger',x=>x.symbols.ABC.ledger=[]],
 ['extra ledger',x=>x.symbols.ABC.ledger.push({...x.symbols.ABC.ledger[0]})],
 ['ledger URL mismatch',x=>x.symbols.ABC.ledger[0].url=url+'x'],
 ['unexpected period',x=>x.symbols.ABC.reports[2027]={Q5:url}],
 ['before history floor',x=>{x.symbols.ABC.reports={2019:{FY:url}};x.symbols.ABC.ledger[0].slot='2019-FY';}],
 ['wrong official host',x=>{x.symbols.ABC.reports[2027].Q1=url.replace('www.sec.gov','evil.test');x.symbols.ABC.ledger[0].url=x.symbols.ABC.reports[2027].Q1;}],
 ['query exfiltration',x=>{x.symbols.ABC.reports[2027].Q1=url+'?x=1';x.symbols.ABC.ledger[0].url=x.symbols.ABC.reports[2027].Q1;}],
 ['extra uncontrolled field',x=>x.execute='fetch(secrets)'],
 ['empty issuer row',x=>{x.symbols.ABC.reports={};}],
 ['filing before period',x=>x.symbols.ABC.ledger[0].filing_date='2026-01-01']
])test(label,()=>{let x=fixture();change(x);rejects(()=>validate(x));});
console.log(count+' consumer tests passed');
