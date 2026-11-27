import fs from 'fs';import assert from 'assert';
const s=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
// 1: items without an uploaded time fall back to article date, never to 0/undefined-high
assert(s.includes('o.u=u!=null?u:(o.t||0)'),'sort fallback to article date');
assert(!/o\.u=u!=null\?u:keep\[k\]/.test(s),'no seen-based sort fallback');
// 2: no-index branch must not prune seen: applies complete:false
const m=s.match(/if\(!newsIdx\)\{[^\n]*?no index yet/);assert(m,'no-index branch found');
assert(m[0].includes('complete:false'),'no-index branch applies complete:false');
assert(m[0].includes('newsArchiveComplete=true'));
// 3: behaviour of the sort: old item without uploaded must not outrank today's item
const now=Date.now(),L=[{i:0,t:now-86400e3*40,u:null},{i:1,t:now-1000,u:now-1000}];
L.forEach(o=>{const u=o.u;o.u=u!=null?u:(o.t||0)});
L.sort((a,b)=>(b.u-a.u)||((b.t??-Infinity)-(a.t??-Infinity))||a.i-b.i);
assert.equal(L[0].i,1,'today item stays above old item without uploaded');
console.log('news-paging regressions passed');
// 4: a 404 / invalid index.json must not tight-loop (busy stays set until the branch finishes; archive marked complete)
{
  const a=s.indexOf('async function newsLoadMore(){'),b=s.indexOf('\n}\n',a)+3;assert(a>0&&b>a,'newsLoadMore found');
  const fn=s.slice(a,b),br=fn.match(/if\(!newsIdx\)\{[^\n]*/)[0];

  assert(!/newsMoreBusy=false/.test(br),'no-index branch must not clear newsMoreBusy early (finally does it)');
  const vm=await import('node:vm');let idxReq=0;
  const ctx={newsMoreBusy:false,newsArchiveComplete:false,newsRecentRaw:[],newsMoreFailAt:0,newsSeq:1,newsIdx:null,newsAt:0,newsPage:null,newsCat:'all',
    $:()=>({value:'',hidden:false}),newsMergeOlder:x=>x,newsStateText:()=>'',newsLoadState:'',setTimeout,Date,
    newsGetJSON:async()=>{idxReq++;return null},newsApplyItems:()=>new Promise(r=>setTimeout(r,20))};
  vm.createContext(ctx);vm.runInContext(fn+';globalThis.run=newsLoadMore;',ctx);
  const first=ctx.run();for(let i=0;i<50;i++){ctx.run();await new Promise(r=>setTimeout(r,1));}  // scroll-observer style re-entry while the apply is awaited
  await first;await new Promise(r=>setTimeout(r,60));for(let i=0;i<20;i++)ctx.run();
  assert.equal(idxReq,1,'index.json requested once on a 404, got '+idxReq);assert.equal(ctx.newsArchiveComplete,true);assert.equal(ctx.newsMoreBusy,false);
}
console.log('news-paging 404 no-loop passed');
