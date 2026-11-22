'use strict';
// Derived display artifact only. The authoritative archive is never rewritten.
const fs=require('node:fs'),crypto=require('node:crypto');
function time(v){const s=String(v||'');let m=s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/);if(m)return Date.UTC(+m[1],+m[2]-1,+m[3],+(m[4]||0),+(m[5]||0));m=s.match(/^(\d{1,2})[./](\d{1,2})[./](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);return m?Date.UTC(m[3].length===2?2000 + +m[3]:+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0)):null;}
function pick(o,keys){for(const k of keys)if(o[k]!=null&&String(o[k]).trim())return String(o[k]).trim();return '';}
function recent(items){return items.map((o,i)=>({o,i,t:time(pick(o,['date','תאריך'])),u:time(pick(o,['uploaded','הועלה']))})).sort((a,b)=>((b.u??b.t??0)-(a.u??a.t??0))||((b.t??-Infinity)-(a.t??-Infinity))||a.i-b.i).slice(0,50).map(x=>x.o);}
function build(bytes){const j=JSON.parse(bytes),items=Array.isArray(j)?j:j?.items;if(!Array.isArray(items)||items.some(o=>!o||typeof o!=='object'||Array.isArray(o)))throw new Error('Invalid news archive');return {version:1,archive_sha256:crypto.createHash('sha256').update(bytes).digest('hex'),total:items.length,items:recent(items)};}
if(require.main===module){const input=process.argv[2]||'news.json',output=process.argv[3]||'news-recent.json';const bytes=fs.readFileSync(input);const result=build(bytes);fs.writeFileSync(output+'.tmp',JSON.stringify(result));fs.renameSync(output+'.tmp',output);console.log('Recent news artifact: '+result.items.length+'/'+result.total+' items; archive SHA-256 '+result.archive_sha256);}
module.exports={build,recent,time};
