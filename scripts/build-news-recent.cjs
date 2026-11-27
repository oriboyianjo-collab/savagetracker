'use strict';
// Derived display artifacts only. The authoritative news.json is never rewritten.
// Run as a script it writes news-recent.json (50 newest) FIRST, then the additive paged archive next to the output file:
// news-archive/pNNNNN.json (PAGE=300 items each, items newest-first inside a page) and news-archive/index.json LAST.
// Pages are numbered from the OLDEST item, so a full (closed) page never changes when newer items arrive; only the newest
// page (marked open:true in the index) grows. The index lists pages newest-first.
// If archive generation throws, news-recent.json stays valid, a warning is logged and the exit code stays 0,
// so publication is never worse than before. No index means clients show only the recent 50.
const fs=require('node:fs'),crypto=require('node:crypto');
function time(v){const s=String(v||'');let m=s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/);if(m)return Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0));m=s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);return m?Date.UTC(m[3].length===2?2000 + +m[3]:+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0)):null;}
function pick(o,keys){for(const k of keys)if(o[k]!=null&&String(o[k]).trim())return String(o[k]).trim();return '';}
function sorted(items){return items.map((o,i)=>({o,i,t:time(pick(o,['date','תאריך'])),u:time(pick(o,['uploaded','הועלה']))})).sort((a,b)=>((b.u??b.t??0)-(a.u??a.t??0))||((b.t??-Infinity)-(a.t??-Infinity))||a.i-b.i);}
function recent(items){return sorted(items).slice(0,50).map(x=>x.o);}
const PAGE=300;
function archive(items,sha){const asc=sorted(items).map(x=>x.o).reverse(),files=[];
  for(let k=0;k<asc.length;k+=PAGE){const n=files.length+1,id='p'+String(n).padStart(5,'0'),part=asc.slice(k,k+PAGE).reverse();files.push({id,file:'news-archive/'+id+'.json',count:part.length,open:k+PAGE>=asc.length,body:{version:1,page:n,count:part.length,items:part}});}
  files.reverse();return {files,index:{version:1,archive_sha256:sha,total:items.length,page_size:PAGE,pages:files.map(f=>({id:f.id,file:f.file,count:f.count,open:f.open}))}};}
function writeAtomic(file,text){fs.writeFileSync(file+'.tmp',text);fs.renameSync(file+'.tmp',file);}

function build(bytes){const j=JSON.parse(bytes),items=Array.isArray(j)?j:j?.items;if(!Array.isArray(items)||items.some(o=>!o||typeof o!=='object'||Array.isArray(o)))throw new Error('Invalid news archive');return {version:1,archive_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),total:items.length,items:recent(items)};}
function buildArchive(bytes){const j=JSON.parse(bytes),items=Array.isArray(j)?j:j?.items;if(!Array.isArray(items)||items.some(o=>!o||typeof o!=='object'||Array.isArray(o)))throw new Error('Invalid news archive');return archive(items,crypto.createHash('sha256').update(bytes).digest('hex'));}
if(require.main===module){const path=require('node:path');const input=process.argv[2]||'news.json',output=process.argv[3]||'news-recent.json';const bytes=fs.readFileSync(input);const result=build(bytes);writeAtomic(output,JSON.stringify(result));console.log('Recent news artifact: '+result.items.length+'/'+result.total+' items; archive SHA-256 '+result.archive_sha256);
  try{const dir=path.join(path.dirname(output),'news-archive'),a=buildArchive(bytes);fs.mkdirSync(dir,{recursive:true});for(const f of a.files)writeAtomic(path.join(dir,f.id+'.json'),JSON.stringify(f.body));writeAtomic(path.join(dir,'index.json'),JSON.stringify(a.index));console.log('News archive: '+a.files.length+' pages, '+a.index.total+' items');}
  catch(e){console.warn('Warning: news archive files unavailable ('+(e&&e.message||e)+'); news-recent.json is intact.');}}
module.exports={build,recent,time,archive,buildArchive,PAGE};
