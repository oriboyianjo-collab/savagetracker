// Earnings card: investor-call line is a separate muted row, only when call_time_il is a real clock.
// Service worker cache bump for the new line. No network.
import { readFileSync } from 'fs';
import assert from 'assert';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const html = readFileSync(join(root, 'index.html'), 'utf8');
const en = readFileSync(join(root, 'i18n-en.js'), 'utf8');
const sw = readFileSync(join(root, 'sw.js'), 'utf8');

assert.match(html, /callTime:\s*\['call_time_il',\s*'שעת_שיחת_משקיעים'\]/);
assert.match(html, /class="rcall"/);
assert.match(html, /I18n\.p\("ui-1526","שיחת משקיעים"\)/);
assert.match(html, /callClock \? `/);
assert.match(html, /\.rrow \.rcall\{/);
// Sun/moon titles may say לפני פתיחה / אחרי סגירה; the visible clock cell must not gain that label.
assert.doesNotMatch(html, /rrelease[^>]*>[^<]*(?:לפני פתיחה|אחרי סגירה)/);
assert.doesNotMatch(html, /class="rrelease[^"]*"[^>]*>\s*(?:לפני פתיחה|אחרי סגירה)/);
assert.match(en, /"ui-1526"\s*:\s*"Investor call"/);
assert.match(sw, /portfolio-shell-v338/);
console.log('PASS earnings call-time UI, i18n, and SW v338');
