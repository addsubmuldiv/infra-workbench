import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const script=()=>readFileSync(new URL('../../desktop/bootstrap/startup.js',import.meta.url),'utf8');
function harness(origin='http://127.0.0.1:8765',lang='en') {
 const nodes=new Map(),intervals=new Map(),timeouts=new Map(),observers=[];let now=0,nextId=0,reloads=0;
 const element=()=>({style:{},attributes:{},listeners:{},setAttribute(k,v){this.attributes[k]=v},remove(){this.removed=true},addEventListener(k,fn){this.listeners[k]=fn}});
 const document={documentElement:{lang,appendChild(node){nodes.set(node.id,node)}},createElement:element,getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}};
 class MutationObserver {constructor(callback){this.callback=callback;observers.push(this)} observe(target,options){this.options=options} disconnect(){this.disconnected=true}}
 const window={};const context={window,document,MutationObserver,setTimeout(fn,delay){const id=++nextId;timeouts.set(id,{fn,delay});return id},clearTimeout(id){timeouts.delete(id)},location:{origin,reload(){reloads++}},navigator:{language:'en-US'},performance:{now:()=>now},setInterval(fn){const id=++nextId;intervals.set(id,fn);return id},clearInterval(id){intervals.delete(id)},Date};
 vm.runInNewContext(script(),context);return {window,nodes,intervals,timeouts,observers,get reloads(){return reloads},tick(ms){now=ms;intervals.forEach(fn=>fn())},setLang(value){document.documentElement.lang=value;observers.filter(o=>!o.disconnected).forEach(o=>o.callback())}};
}
test('bootstrap uses OS fallback, progresses only at milestones, and counts elapsed independently',()=>{
 const h=harness('http://tauri.localhost','zh-CN');
 assert.equal(h.nodes.get('iwb-startup-percent').textContent,'5%');
 assert.match(h.nodes.get('iwb-startup-status').textContent,/Connecting/);
 assert.equal(h.timeouts.size,0);
 h.window.__iwbStartup.update('backend',20);h.tick(12000);
 assert.equal(h.nodes.get('iwb-startup-percent').textContent,'20%');
 assert.match(h.nodes.get('iwb-startup-elapsed').textContent,/Elapsed 12 s/);
 h.window.__iwbStartup.update('frontend',85);assert.equal(h.nodes.get('iwb-startup-percent').textContent,'85%');
 h.window.__iwbStartup.update('health',70);assert.equal(h.nodes.get('iwb-startup-percent').textContent,'85%');
});
test('service overlay uses document locale and follows shared locale changes',()=>{
 const h=harness(undefined,'zh-CN');
 assert.match(h.nodes.get('iwb-startup-status').textContent,/正在加载/);
 assert.match(h.nodes.get('iwb-startup-elapsed').textContent,/已等待/);
 h.setLang('en');assert.match(h.nodes.get('iwb-startup-status').textContent,/Loading workspace/);
 assert.equal(h.nodes.get('iwb-startup-retry').textContent,'Try again');
 assert.equal(h.nodes.get('iwb-startup-progress').attributes['aria-label'],'Startup stages');
 h.setLang('zh-CN');assert.match(h.nodes.get('iwb-startup-status').textContent,/正在加载/);
});
test('frontend timeout exposes an accessible retry and clicking it reloads',()=>{
 const h=harness();const timeout=[...h.timeouts.values()][0];assert.equal(timeout.delay,60000);timeout.fn();
 assert.equal(h.nodes.get('iwb-startup-retry').hidden,false);
 assert.equal(h.nodes.get('iwb-startup-panel').attributes['aria-busy'],'false');
 assert.match(h.nodes.get('iwb-startup-status').textContent,/did not finish loading/);
 h.nodes.get('iwb-startup-retry').listeners.click();assert.equal(h.reloads,1);
});
test('normal finish removes overlay and clears timers and locale observer',()=>{
 const h=harness();assert.equal(h.intervals.size,1);assert.equal(h.timeouts.size,1);
 h.window.__iwbStartup.finish();assert.equal(h.nodes.get('iwb-startup').removed,true);
 assert.equal(h.intervals.size,0);assert.equal(h.timeouts.size,0);assert.ok(h.observers.every(o=>o.disconnected));
});
test('startup injection refuses external origins',()=>{assert.equal(harness('https://example.com').window.__iwbStartup,undefined)});
test('native startup diagnostics are translated for English',()=>{const h=harness();h.window.__iwbStartup.update('error',20,'后台启动失败，请查看 desktop.log');assert.match(h.nodes.get('iwb-startup-status').textContent,/failed to start/)});
