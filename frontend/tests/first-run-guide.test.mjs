import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {i18nMock} from './i18n-mock.mjs';

function harness(t,{ready=true,hasHosts=false,completed=false,shared}={}){
  const storage=shared??new Map(completed?[['workspace:onboarding-completed:v1','true']]:[]);
  const listeners=new Map(),values=[],setters=[],effects=[],cleanups=[];let slot=0,dirty=false,tree,added=0;
  const workspaceStorage={getItem:key=>storage.get(key)??null,setItem(key,value){if(storage.get(key)===value)return;storage.set(key,value);listeners.get(key)?.forEach(fn=>fn())},subscribe(key,fn){if(!listeners.has(key))listeners.set(key,new Set());listeners.get(key).add(fn);return()=>listeners.get(key).delete(fn)}};
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState(initial){const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;setters[i]??=next=>{const v=typeof next==='function'?next(values[i]):next;if(v!==values[i]){values[i]=v;dirty=true}};return[values[i],setters[i]]},
    useRef(initial){const i=slot++;return values[i]??={current:initial}},
    useEffect(fn,deps){const i=slot++;if(!values[i]||deps.some((v,j)=>!Object.is(v,values[i][j]))){effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()});values[i]=deps}}};
  const window=new EventTarget(),document={body:{},activeElement:null};
  const compile=(file,require)=>{const exports={};const js=ts.transpileModule(fs.readFileSync(new URL(file,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;new Function('require','exports','window','document','HTMLElement',js)(require,exports,window,document,class{});return exports};
  const hooks=compile('../src/workspaceHooks.ts',name=>name==='react'?react:{workspaceStorage});
  const component=compile('../src/FirstRunGuide.tsx',name=>i18nMock(name)??(name==='react'?react:name==='react-dom'?{createPortal:node=>node}:name==='./workspaceHooks'?hooks:{}));
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children??[]).flat(Infinity).flatMap(nodes)];
  const text=n=>n==null||n===false?'':typeof n!=='object'?String(n):(n.props?.children??[]).flat(Infinity).map(text).join('');
  const render=()=>{let iterations=0;do{dirty=false;slot=0;tree=component.FirstRunGuide({ready,hasHosts,onAddMachine(){added++}});effects.splice(0).forEach(fn=>fn());assert.ok(++iterations<15,'render should settle')}while(dirty);return tree};
  t.after(()=>cleanups.forEach(fn=>fn?.()));
  return{render,storage,window,text:()=>text(tree),find:p=>nodes(tree).find(p),setReady(value){ready=value;render()},replay(){window.dispatchEvent(new Event('iwb:replay-getting-started'));render()},click(label){const button=nodes(tree).find(n=>n.type==='button'&&text(n)===label);assert.ok(button,label);button.props.onClick();render()},added:()=>added};
}

test('fresh workspace waits for loaded state, then shows the real getting-started guide',t=>{
  const h=harness(t,{ready:false});assert.equal(h.render(),null);h.setReady(true);
  assert.equal(h.find(n=>n.type==='dialog').props['aria-modal'],true);assert.match(h.text(),/连接第一台机器/);
});
test('skip is persisted and a later window does not automatically replay it',t=>{
  const h=harness(t);h.render();h.click('暂时跳过');assert.equal(h.render(),null);
  const next=harness(t,{shared:h.storage});assert.equal(next.render(),null);
});
test('existing workspaces are not interrupted and settings can still replay the guide',t=>{
  const h=harness(t,{hasHosts:true});assert.equal(h.render(),null);h.replay();assert.match(h.text(),/连接第一台机器/);
});
test('completing all steps records completion without connecting to any server',t=>{
  const h=harness(t);h.render();for(let i=0;i<5;i++)h.click('下一步');assert.match(h.text(),/随时回来/);h.click('完成引导');
  assert.equal(h.render(),null);assert.equal(h.storage.get('workspace:onboarding-completed:v1'),'true');assert.equal(h.added(),0);
});
test('adding a machine is an explicit user action after dismissing the guide',t=>{
  const h=harness(t);h.render();h.click('添加机器');assert.equal(h.added(),1);assert.equal(h.render(),null);
});
test('Escape skips and replay does not erase the saved completion state',t=>{
  const h=harness(t);h.render();h.find(n=>n.type==='dialog').props.onCancel({preventDefault(){}});h.render();h.replay();
  assert.ok(h.find(n=>n.type==='dialog'));assert.equal(h.storage.get('workspace:onboarding-completed:v1'),'true');
});
