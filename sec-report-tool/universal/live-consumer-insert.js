/* Begin live report overlay. Data only; adds slots that the universal data does not hold yet, never replaces one. */
const LIVE_REPORT_OVERLAY = {};
const reportYearsWithoutLive = reportYears;
reportYears = function reportYears(sym){
  const key=String(sym||'').toUpperCase(),base=reportYearsWithoutLive(sym),live=LIVE_REPORT_OVERLAY[key];
  if(!live)return base;
  const merged={};for(const [year,periods] of Object.entries(base||{}))merged[year]={...periods};
  for(const [year,periods] of Object.entries(live)){
    merged[year]=merged[year]||{};
    for(const [period,url] of Object.entries(periods))if(!merged[year][period])merged[year][period]=url;
  }
  return merged;
};
(async function loadLiveReportOverlay(){
  try{
    const response=await fetch('report-links-live.json',{cache:'no-cache'});if(!response.ok)return;
    const text=await response.text();if(text.length>512000)throw new Error('Oversized live report overlay');
    const add=validateUniversalReportIndex(JSON.parse(text));
    const symbols=Object.keys(add);if(!symbols.length)return;
    for(const sym of symbols)LIVE_REPORT_OVERLAY[sym]=add[sym];
    for(const sym of symbols)refreshUniversalReportControls(sym);
  }catch(e){console.warn('Live report links unchanged:',e&&e.message||e);}
})();
/* End live report overlay. */
