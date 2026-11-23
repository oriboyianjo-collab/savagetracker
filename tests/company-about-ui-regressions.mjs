// About-the-company card: placement, copy, language, SW cache, hide-when-empty.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'index.html'), 'utf8');
const sw = readFileSync(join(root, 'sw.js'), 'utf8');
const i18n = readFileSync(join(root, 'i18n-en.js'), 'utf8');

const inst = html.slice(html.indexOf('function instSheetHtml'), html.indexOf('function detHtml()'));
const detAt = inst.indexOf('detHtml()');
const aboutAt = inst.indexOf('aboutCardHtml()');
const wlAt = inst.indexOf('wlAddHtml(');
assert.ok(detAt >= 0 && aboutAt > detAt && wlAt > aboutAt, 'instrument sheet: about card between details and watchlist button');

const pos = html.slice(html.indexOf('function openPosition'), html.indexOf('function openPosition') + 12000);
const pDet = pos.indexOf('detHtml()');
const pAbout = pos.indexOf('aboutCardHtml()');
const pBtn = pos.indexOf('data-pact="buy"');
assert.ok(pDet >= 0 && pAbout > pDet && pBtn > pAbout, 'position sheet: about card between details and action buttons');

assert.match(html, /id="isAbout" hidden/);
assert.match(html, /box\.hidden = true/);
assert.match(html, /I18n\.p\("ui-1523","על החברה"\)/);
assert.match(html, /I18n\.p\("ui-1524","קרא עוד"\)/);
assert.match(html, /I18n\.p\("ui-1525","הצג פחות"\)/);
assert.match(html, /Source: Annual report/);
assert.match(html, /מקור: דוח שנתי/);
assert.match(html, /fetch\('company-profiles\/'\+encodeURIComponent\(aboutSym\)\+'\.json/);
assert.match(html, /aboutData = \(j && \(j\.short_en\|\|j\.short_he\)\) \? j : null/);
assert.match(html, /en \? aboutData\.short_en : \(aboutData\.short_he \|\| aboutData\.short_en\)/);
assert.match(sw, /portfolio-shell-v338/);
assert.ok(sw.includes('company-profiles') && sw.includes('portfolio-shell-v338'), 'SW v338 bypasses company-profiles JSON');
assert.match(i18n, /"ui-1523":"About the company"/);
assert.match(i18n, /"ui-1524":"Read more"/);
assert.match(i18n, /"ui-1525":"Show less"/);
console.log('PASS about-company card placement, i18n, hide-when-empty, and SW v338');
