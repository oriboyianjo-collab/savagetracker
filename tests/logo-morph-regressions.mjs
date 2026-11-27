import fs from 'node:fs'; import assert from 'node:assert/strict'; import vm from 'node:vm';
const src=fs.readFileSync(new URL('../index.html',import.meta.url),'utf8');
assert.ok(/\.logo img\.ok\{opacity:1\}/.test(src),'.logo img.ok rule');
const mk=src.match(/function morphKids\(a, b\)\{[\s\S]*?\n  for\(let i=A\.length-1;i>=Bn\.length;i--\) a\.removeChild\(A\[i\]\); \}/);
assert.ok(mk,'morphKids found');
assert.ok(/dataset\.lsym/.test(mk[0])&&/classList\.add\('ok'\)/.test(mk[0]),'morphKids restores ok on loaded logos');
const lh=src.match(/function logoHtml\([\s\S]*?\n\}/)[0];
assert.ok(/data-lsym=/.test(lh),'logoHtml emits data-lsym');
assert.ok(!/class="ok"|' ok'|\bok\b'/.test(lh.replace(/\.ok/g,'')),'logoHtml must not emit a default ok class');
assert.ok(/function logoReveal\(/.test(src)&&/M\(body\)\.h = html; logoReveal\(body\)/.test(src)&&/logoReveal\(\$\('etfHd'\)\)/.test(src),'logoReveal wired after both drawEtf morphs');
// tiny fake DOM running the real morphKids
class Node_{constructor(t,name){this.nodeType=t;this.nodeName=name;this.childNodes=[];this.parent=null;}
 appendChild(c){c.parent=this;this.childNodes.push(c);} replaceChild(n,o){const i=this.childNodes.indexOf(o);this.childNodes[i]=n;n.parent=this;} removeChild(c){this.childNodes.splice(this.childNodes.indexOf(c),1);}}
class El extends Node_{constructor(tag,attrs={},extra={}){super(1,tag.toUpperCase());this.tagName=tag.toUpperCase();this.attrs=new Map(Object.entries(attrs));Object.assign(this,extra);
  const self=this;this.classList={add(c){const s=new Set((self.attrs.get('class')||'').split(/\s+/).filter(Boolean));s.add(c);self.attrs.set('class',[...s].join(' '));}};
  this.dataset={};if(attrs['data-lsym'])this.dataset.lsym=attrs['data-lsym'];}
 get attributes(){return [...this.attrs].map(([name,value])=>({name,value}));} hasAttribute(n){return this.attrs.has(n);} getAttribute(n){return this.attrs.get(n);} setAttribute(n,v){this.attrs.set(n,v);} removeAttribute(n){this.attrs.delete(n);}}
const ctx={}; vm.createContext(ctx); vm.runInContext(mk[0]+';this.morphKids=morphKids;',ctx);
const build=(img)=>{const root=new El('div');const span=new El('span',{class:'logo'});span.appendChild(img);root.appendChild(span);return root;};
const old=build(new El('img',{'data-lsym':'CRWV','data-li':'0',src:'u',class:'ok'},{complete:true,naturalWidth:100}));
ctx.morphKids(old,build(new El('img',{'data-lsym':'CRWV','data-li':'0',src:'u'})));
assert.ok(/\bok\b/.test(old.childNodes[0].childNodes[0].getAttribute('class')||''),'loaded logo keeps ok after morph');
const pend=build(new El('img',{'data-lsym':'CRWV','data-li':'0',src:'u',class:'ok'},{complete:false,naturalWidth:0}));
ctx.morphKids(pend,build(new El('img',{'data-lsym':'CRWV','data-li':'0',src:'u'})));
assert.ok(!/\bok\b/.test(pend.childNodes[0].childNodes[0].getAttribute('class')||''),'not-loaded image does not get ok');
console.log('logo-morph regressions passed');
