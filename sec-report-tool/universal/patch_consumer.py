"""Apply the minimal data-binding patch to an explicitly supplied app copy. No network."""
import argparse
from pathlib import Path

MARKER='/* End NOW generated report index. */'
INSERT_END='/* End universal report-data consumer. */'

def patch(text,insertion):
    if '/* Begin universal report-data consumer.' in text:raise ValueError('already patched; do not double insert')
    if text.count(MARKER)!=1:raise ValueError('NOW end marker not unique')
    # Two dedicated consumers must use the merged selected-year data even when their fetch wins last.
    a=text.index('/* ISRG report links:');b=text.index('/* End ISRG retained-data pilot. */')
    old="reportPdfActions(reports[selected]||{})"
    if text[a:b].count(old)!=1:raise ValueError('ISRG refresh target not unique')
    section=text[a:b].replace(old,"reportPdfActions(reportYears('ISRG')[selected]||{})");text=text[:a]+section+text[b:]
    a=text.index('/* End ISRG retained-data pilot. */');b=text.index(MARKER)
    if text[a:b].count(old)!=1:raise ValueError('NOW refresh target not unique')
    section=text[a:b].replace(old,"reportPdfActions(reportYears('NOW')[selected]||{})");text=text[:a]+section+text[b:]
    replacements=[
      ("function reportPdfControls(sym){ const years=REPORT_PDFS[String(sym||'').toUpperCase()];","function reportPdfControls(sym){ const years=reportYears(sym);"),
      ("function reportPdfControlsAny(sym){ const years=REPORT_PDFS[String(sym||'').toUpperCase()];","function reportPdfControlsAny(sym){ const years=reportYears(sym);"),
      ("function reportPdfTargets(p){return ((REPORT_PDFS[p.dataset.pdfSymbol]||{})[p.querySelector('select').value]||{});}","function reportPdfTargets(p){return ((reportYears(p.dataset.pdfSymbol)||{})[p.querySelector('select').value]||{});}")]
    for old,new in replacements:
        if text.count(old)!=1:raise ValueError('report lookup target not unique')
        text=text.replace(old,new)
    return text.replace(MARKER,MARKER+'\n'+insertion,1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--insert',default=str(Path(__file__).with_name('universal-consumer-insert.js')));a=p.parse_args();Path(a.output).write_text(patch(Path(a.input).read_text(),Path(a.insert).read_text()))
