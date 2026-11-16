/* Begin universal report-data consumer. Data only; existing controls are unchanged. */
let UNIVERSAL_REPORT_OVERRIDES = {};
let UNIVERSAL_REPORT_MANIFEST = null;
const UNIVERSAL_REPORT_REQUESTS = new Map();
function reportYears(sym){
  const key=String(sym||'').toUpperCase(),base=REPORT_PDFS[key],extra=UNIVERSAL_REPORT_OVERRIDES[key];
  if(!extra){loadUniversalReportSymbol(key);return base;}
  const merged={};for(const [year,periods] of Object.entries(base||{}))merged[year]={...periods};
  for(const [year,periods] of Object.entries(extra))merged[year]={...(merged[year]||{}),...periods};
  return merged;
}
function validateUniversalReportIndex(data){
  const fail=()=>{throw new Error('Invalid universal report index');};
  const plain=x=>x!==null && typeof x==='object' && !Array.isArray(x) && Object.getPrototypeOf(x)===Object.prototype;
  const iso=s=>{if(typeof s!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(s))return false;const d=new Date(s+'T00:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===s;};
  const exact=(o,keys)=>plain(o)&&Object.keys(o).sort().join('|')===keys.slice().sort().join('|');
  if(!exact(data,['schema_version','inventory_sha256','as_of','symbols'])||data.schema_version!==1||data.inventory_sha256!=='c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083'||!iso(data.as_of)||data.as_of>new Date().toISOString().slice(0,10)||!plain(data.symbols)||Object.keys(data.symbols).length>6315)fail();
  const out={};
  for(const [sym,row] of Object.entries(data.symbols)){
    if(!/^[A-Z0-9][A-Z0-9.\-]{0,31}$/.test(sym)||['__proto__','constructor','prototype'].includes(sym)||!exact(row,['cik','reports','ledger'])||!/^\d{10}$/.test(row.cik)||/^0+$/.test(row.cik)||!plain(row.reports)||!Array.isArray(row.ledger)||!row.ledger.length||row.ledger.length>200)fail();
    const numericCik=String(Number(row.cik)),flat=new Map(),ledger=new Map();
    for(const [year,periods] of Object.entries(row.reports)){
      if(!/^20\d{2}$/.test(year)||Number(year)<2020||!plain(periods)||!Object.keys(periods).length)fail();
      for(const [period,url] of Object.entries(periods)){
        if(!/^(FY|Q[1-4])$/.test(period)||typeof url!=='string')fail();
        let u;try{u=new URL(url);}catch(e){fail();}
        if(u.protocol!=='https:'||u.hostname!=='www.sec.gov'||u.port||u.username||u.password||u.search||u.hash||u.href!==url||!new RegExp('^/Archives/edgar/data/(?:'+numericCik+(numericCik==='2115436'?'|34088':'')+')/\\d{18}/[A-Za-z0-9][A-Za-z0-9_.-]*\\.html?$').test(u.pathname))fail();
        const slot=year+'-'+period;if(flat.has(slot))fail();flat.set(slot,url);
      }
    }
    if(!flat.size||flat.size!==row.ledger.length)fail();
    for(const e of row.ledger){
      if(!exact(e,['slot','url','body_sha256','period_end','filing_date'])||!flat.has(e.slot)||flat.get(e.slot)!==e.url||ledger.has(e.slot)||!/^\w{64}$/.test(e.body_sha256)||!/^[a-f0-9]{64}$/.test(e.body_sha256)||!iso(e.period_end)||!iso(e.filing_date)||e.period_end>e.filing_date||e.filing_date>data.as_of)fail();
      ledger.set(e.slot,e);
    }
    const clean={};for(const [year,periods] of Object.entries(row.reports))clean[year]={...periods};out[sym]=clean;
  }
  return out;
}
function refreshUniversalReportControls(sym){
  document.querySelectorAll('.report-pick').forEach(p=>{
    if(p.dataset.pdfSymbol!==sym)return;
    const selected=p.querySelector('select')?.value;
    const shell=document.createElement('div');shell.innerHTML=reportPdfControlsAny(sym);
    const fresh=shell.querySelector('.report-pick');
    if(selected&&fresh){
      const select=fresh.querySelector('select');
      if(select&&[...select.options].some(o=>o.value===selected)){
        select.value=selected;
        fresh.querySelector('[data-pdf-year-text]').textContent=selected;
        fresh.querySelectorAll('[data-pdf-year]').forEach(b=>{const on=b.dataset.pdfYear===selected;b.classList.toggle('on',on);b.setAttribute('aria-selected',String(on));b.querySelector('small').textContent=on?'✓':'';});
        fresh.querySelector('[data-pdf-actions]').innerHTML=reportPdfActions(reportYears(sym)[selected]||{});
      }
    }
    if(fresh)p.replaceWith(fresh);
  });
}
function loadUniversalReportSymbol(sym){
  if(!UNIVERSAL_REPORT_MANIFEST||!Object.hasOwn(UNIVERSAL_REPORT_MANIFEST.symbols,sym)||UNIVERSAL_REPORT_REQUESTS.has(sym))return;
  const meta=UNIVERSAL_REPORT_MANIFEST.symbols[sym];
  const promise=(async()=>{
    try{
      const response=await fetch('report-links-all/'+sym+'.'+meta.sha256+'.json',{cache:'force-cache'});
      if(!response.ok)return;
      const raw=await response.arrayBuffer();if(raw.byteLength>512000)throw new Error('Oversized report shard');
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw))).map(b=>b.toString(16).padStart(2,'0')).join('');
      if(hash!==meta.sha256)throw new Error('Report shard integrity mismatch');
      const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
      const addition=validateUniversalReportIndex(data);
      if(Object.keys(addition).length!==1||!Object.hasOwn(addition,sym)||data.symbols[sym].cik!==meta.cik||data.as_of!==UNIVERSAL_REPORT_MANIFEST.as_of)throw new Error('Report shard scope mismatch');
      UNIVERSAL_REPORT_OVERRIDES[sym]=addition[sym];
      refreshUniversalReportControls(sym);
    }catch(e){console.warn('Universal report links unchanged:',e&&e.message||e);}
  })();
  UNIVERSAL_REPORT_REQUESTS.set(sym,promise);
}
function validateUniversalReportManifest(data){
  const plain=x=>x!==null&&typeof x==='object'&&!Array.isArray(x)&&Object.getPrototypeOf(x)===Object.prototype;
  if(!plain(data)||Object.keys(data).sort().join('|')!=='as_of|inventory_sha256|schema_version|symbols'||data.schema_version!==1||data.inventory_sha256!=='c17c10642864e2255eb55dd3f819daf40e34b894c87b6cf877c06afb41e3c083'||!/^\d{4}-\d{2}-\d{2}$/.test(data.as_of)||new Date(data.as_of+'T00:00:00Z').toISOString().slice(0,10)!==data.as_of||data.as_of>new Date().toISOString().slice(0,10)||!plain(data.symbols)||Object.keys(data.symbols).length>6315)throw new Error('Invalid report manifest');
  for(const [sym,row]of Object.entries(data.symbols)){
    if(!/^[A-Z0-9][A-Z0-9.\-]{0,31}$/.test(sym)||!plain(row)||Object.keys(row).sort().join('|')!=='cik|sha256'||!/^\d{10}$/.test(row.cik)||/^0+$/.test(row.cik)||!/^[a-f0-9]{64}$/.test(row.sha256))throw new Error('Invalid report manifest entry');
  }
  return data;
}
(async function loadUniversalReports(){
  try{
    const response=await fetch('report-links-all.json',{cache:'no-cache'});if(!response.ok)return;
    const text=await response.text();if(text.length>2000000)throw new Error('Oversized report manifest');
    const data=validateUniversalReportManifest(JSON.parse(text));
    UNIVERSAL_REPORT_MANIFEST=data;
    document.querySelectorAll('.report-pick').forEach(p=>loadUniversalReportSymbol(p.dataset.pdfSymbol));
  }catch(e){console.warn('Universal reports left unchanged:',e&&e.message||e);}
})();
/* End universal report-data consumer. */
