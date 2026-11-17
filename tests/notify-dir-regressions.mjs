// Notification RTL marks: Hebrew title/body that start in English still render RTL.
// No network, no sending, no portfolio data.
import fs from 'fs';
import vm from 'vm';
import {pathToFileURL} from 'url';

const root = new URL('..', import.meta.url);
const read = f => fs.readFileSync(new URL(f, root), 'utf8');
vm.runInContext(read('alerts-core.js'), vm.createContext({self: globalThis, globalThis}));
const notifyText = globalThis.AlertsCore.notifyText;
let failed = 0;
const ok = (name, cond, detail='') => { if(!cond){ failed++; console.log('FAIL', name, detail); } else console.log('PASS', name); };

const RLM = '\u200F', RLE = '\u202B', PDF = '\u202C';
const marks = /[\u200F\u202B\u202C]/g;
const body = 'ExxonMobil (XOM): SBM Offshore זכתה בחוזי בנייה והתקנה של FPSO ל-Longtail בגיאנה';
const title = '📰 חדשות על XOM';
const markedBody = notifyText(body, 'he');
const markedTitle = notifyText(title, 'he');

ok('helper is exported', typeof notifyText === 'function');
ok('hebrew body starting in Latin gets RLM+RLE prefix and PDF suffix', markedBody.startsWith(RLM + RLE) && markedBody.endsWith(PDF) && markedBody.slice(2, -1) === body);
ok('hebrew title is marked the same way', markedTitle.startsWith(RLM + RLE) && markedTitle.endsWith(PDF) && markedTitle.slice(2, -1) === title);
ok('visible characters are unchanged', markedBody.replace(marks, '') === body && markedTitle.replace(marks, '') === title);
ok('already-marked text is not prefixed again', notifyText(markedBody, 'he') === markedBody && notifyText(markedTitle, 'he') === markedTitle);
ok('english notifications stay unmarked', notifyText(body, 'en') === body && notifyText(title, 'en') === title);
ok('empty and missing stay empty', notifyText('', 'he') === '' && notifyText(null, 'he') === '' && notifyText(undefined, 'he') === '');
ok('missing lang is treated as hebrew', notifyText(body).startsWith(RLM + RLE) && notifyText(body).endsWith(PDF));

const sw = read('sw.js');
const html = read('index.html');
ok('sw alShow prefixes through notifyText', sw.includes('alNotifyText(it.title, it.lang)') && sw.includes('alNotifyText(it.body||\'\', it.lang)'));
ok('page alNotify prefixes through notifyText', html.includes('AlertsCore.notifyText(it.title, I18n.language)') && html.includes("AlertsCore.notifyText(it.body||'', I18n.language)"));
ok('sw cache bumped and alerts-core query matches', sw.includes("const CACHE = 'portfolio-shell-v323'") && sw.includes('alerts-core.js?v=271') && html.includes('alerts-core.js?v=271') && !sw.includes('alerts-core.js?v=270') && !html.includes('alerts-core.js?v=270'));

if (failed) { console.log(failed + ' failed'); process.exit(1); }
console.log('all notify-dir checks passed');
