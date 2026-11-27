import fs from 'node:fs'; import assert from 'node:assert/strict';
const src=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8'),sw=fs.readFileSync(new URL('../sw.js',import.meta.url),'utf8');
const m=src.match(/const LOGO_FIX = \{([\s\S]*?)\n\};/);assert.ok(m,'LOGO_FIX');
const fix=k=>{const r=m[1].match(new RegExp("(?:^|[\\s,])'?"+k+"'?:('[^']*')"));return r&&r[1].slice(1,-1)};
for(const t of 'XLI XLY XLF XLE XAR XLU XLB XLV XLC XLP'.split(' '))assert.equal(fix(t),'logos/spdr.png',t);
for(const t of ['IGV','SOXX'])assert.equal(fix(t),'logos/ishares.png',t);
for(const t of 'PRAM DRNZ NECK NUKZ NCLD DRAM JEDI'.split(' '))assert.equal(fix(t),'',t+' initials');
const ini=src.match(/const LOGO_INI = (\{[^}]*\})/);assert.ok(ini);const I=eval('('+ini[1]+')');
assert.deepEqual(Object.values(I),['PRA','DRN','NEC','NUK','NCL','DRA','JED']);assert.equal(new Set(Object.values(I)).size,7);
for(const f of ['logos/spdr.png','logos/ishares.png']){assert.ok(fs.existsSync(new URL('../'+f,import.meta.url)),f);assert.ok(sw.includes("'./"+f+"'"),'sw precache '+f);}
assert.ok(/portfolio-shell-v35\d/.test(sw));
console.log('fund-logo regressions passed');
