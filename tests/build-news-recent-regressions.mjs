import fs from 'node:fs'; import os from 'node:os'; import path from 'node:path'; import crypto from 'node:crypto'; import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const run=(dir)=>execFileSync('node',['scripts/build-news-recent.cjs',path.join(dir,'news.json'),path.join(dir,'news-recent.json')]);
const mk=(n,extra=[])=>{const a=[];for(let i=0;i<n;i++){const d=new Date(Date.UTC(2026,9,1)+i*3600e3*5);a.push({'מזהה':'n-'+i,date:d.toISOString().slice(0,10),uploaded:d.toISOString().slice(0,16).replace('T',' ')});}return a.concat(extra);};
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'nr-'));
const items=mk(700,[{'מזהה':'u-0',title:'no date'}]);
const bytes=Buffer.from(JSON.stringify(items));fs.writeFileSync(path.join(dir,'news.json'),bytes);
run(dir);
assert.ok(fs.readFileSync(path.join(dir,'news.json')).equals(bytes),'input untouched');
const rec=JSON.parse(fs.readFileSync(path.join(dir,'news-recent.json')));
const sha=crypto.createHash('sha256').update(bytes).digest('hex');
assert.equal(rec.version,1);assert.equal(rec.items.length,50);assert.equal(rec.total,701);assert.equal(rec.archive_sha256,sha);
const idx=JSON.parse(fs.readFileSync(path.join(dir,'news-archive','index.json')));
assert.equal(idx.archive_sha256,sha);assert.equal(idx.total,701);assert.equal(idx.page_size,300);
assert.deepEqual(idx.pages.map(p=>p.id),['p00003','p00002','p00001']);
assert.deepEqual(idx.pages.map(p=>p.open),[true,false,false]);
assert.equal(idx.pages.reduce((a,p)=>a+p.count,0),701);
const seen=new Set();let prev=null;
for(const p of idx.pages){const f=JSON.parse(fs.readFileSync(path.join(dir,p.file)));assert.equal(f.items.length,p.count);f.items.forEach(o=>{assert.ok(!seen.has(o['מזהה']));seen.add(o['מזהה']);});}
assert.equal(seen.size,701);
const p3=JSON.parse(fs.readFileSync(path.join(dir,'news-archive','p00003.json')));
assert.deepEqual(rec.items.map(o=>o['מזהה']),p3.items.slice(0,50).map(o=>o['מזהה']));
// closed pages stay byte-stable when newer items arrive
const closed=['p00001','p00002'].map(id=>fs.readFileSync(path.join(dir,'news-archive',id+'.json')));
fs.writeFileSync(path.join(dir,'news.json'),JSON.stringify(mk(700,[{'מזהה':'u-0',title:'no date'}]).concat([{'מזהה':'new-1',date:'2027-06-01',uploaded:'2027-06-01 10:00'},{'מזהה':'new-2',date:'2027-06-02',uploaded:'2027-06-02 10:00'}])));
run(dir);
['p00001','p00002'].forEach((id,k)=>assert.ok(fs.readFileSync(path.join(dir,'news-archive',id+'.json')).equals(closed[k]),id+' changed'));
console.log('build-news-recent regressions passed');
