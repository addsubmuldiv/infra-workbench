import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as layout from '../src/assistantLayout.ts';
import * as frames from '../src/fileWindow.ts';

function harness(t,{stored=null,viewport=1400}={}){
  const values=[],effects=[],deps=[],cleanups=[],disk=new Map(),listeners=new Map(),reserved=[];let slot=0,tree,open=true;
  if(stored)disk.set(layout.ASSISTANT_WINDOW_KEY,JSON.stringify(stored));
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in values))values[i]=typeof initial==='function'?initial():initial;return [values[i],value=>{values[i]=typeof value==='function'?value(values[i]):value}]},
    useRef:initial=>{const i=slot++;if(!(i in values))values[i]={current:initial};return values[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){deps[i]=next;effects.push(()=>{cleanups[i]?.();cleanups[i]=fn()})}}};
  const window={innerWidth:viewport,innerHeight:900,localStorage:{getItem:key=>disk.get(key)??null,setItem:(key,value)=>disk.set(key,value)},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)};
  const old=Object.getOwnPropertyDescriptor(globalThis,'window');Object.defineProperty(globalThis,'window',{configurable:true,value:window});
  t.after(()=>{cleanups.forEach(fn=>fn?.());if(old)Object.defineProperty(globalThis,'window',old);else delete globalThis.window});
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/AssistantWindow.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const Assistant=()=>null,exports={};
  new Function('require','exports',js)(name=>name==='react'?react:name==='./assistantLayout'?layout:name==='./fileWindow'?frames:name==='./InfraAssistantPage'?{InfraAssistant:Assistant}:name==='./windowLayers'?{activateFloatingWindow(){},registerFloatingWindow(){}}:{},exports);
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const onDockWidthChange=value=>reserved.push(value);
  const render=()=>{slot=0;tree=exports.AssistantWindow({open,onClose:()=>{open=false},onDockWidthChange,selectedHostIds:[],locate(){},openTerminal(){},openSettings(){}});effects.splice(0).forEach(fn=>fn());return tree};
  const find=predicate=>nodes(tree).find(predicate),button=label=>find(n=>n.type==='button'&&n.props['aria-label']===label);
  const event=(x=1100,y=25)=>({button:0,pointerId:1,clientX:x,clientY:y,preventDefault(){},target:{closest:()=>null},currentTarget:{setPointerCapture(){},hasPointerCapture(){return true},releasePointerCapture(){}}});
  return {render,find,button,event,disk,reserved,reopen(){open=true;return render()},resize(width,height=900){window.innerWidth=width;window.innerHeight=height;listeners.get('resize')?.();return render()},assistant:()=>find(n=>n.type===Assistant)};
}

test('docked assistant reserves workspace room; hiding and floating preserve the same assistant instance',t=>{
  const h=harness(t);let root=h.render();assert.ok(root.props.className.includes('docked'));assert.equal(h.reserved.at(-1),420);
  const child=h.assistant();h.button('悬浮 AI 助手').props.onClick();root=h.render();assert.ok(root.props.className.includes('floating'));assert.equal(h.reserved.at(-1),0);
  assert.equal(h.assistant().type,child.type);assert.equal(h.assistant().props.key,child.props.key);
  h.button('收起 AI 助手').props.onClick();root=h.render();assert.equal(root.props.hidden,true);assert.ok(h.assistant());
  h.reopen();h.button('停靠到右侧').props.onClick();h.render();assert.equal(h.reserved.at(-1),420);
});

test('dragging detaches only after movement; dropping at the right edge docks again',t=>{
  const h=harness(t);let root=h.render();const initial=[...h.disk.entries()];
  h.find(n=>n.props.className==='assistant-window-header').props.onPointerDown(h.event());
  root.props.onPointerMove(h.event(1102,26));root=h.render();assert.ok(root.props.className.includes('docked'));
  root.props.onPointerMove(h.event(700,160));root=h.render();assert.ok(root.props.className.includes('floating'));
  assert.deepEqual([...h.disk.entries()],initial,'pointer movement must not write storage');
  assert.ok(root.props.style.left>=8);assert.ok(root.props.style.top>=8);
  root.props.onPointerUp(h.event(700,160));h.render();assert.equal(JSON.parse(h.disk.get(layout.ASSISTANT_WINDOW_KEY)).mode,'floating');
  h.find(n=>n.props.className==='assistant-window-header').props.onPointerDown(h.event(700,160));
  root.props.onPointerMove(h.event(1390,180));root=h.render();assert.ok(root.props.className.includes('dock-preview'));
  root.props.onPointerUp(h.event(1390,180));root=h.render();assert.ok(root.props.className.includes('docked'));assert.equal(h.reserved.at(-1),420);
});

test('header controls never start dragging, dock resizing persists, and small viewports retain usable bounds',t=>{
  const h=harness(t);let root=h.render();const e=h.event();e.target.closest=()=>true;
  h.find(n=>n.props.className==='assistant-window-header').props.onPointerDown(e);root.props.onPointerMove(h.event(200,200));assert.ok(h.render().props.className.includes('docked'));
  h.find(n=>n.props['aria-label']==='调整助手侧栏宽度').props.onPointerDown(h.event());
  root.props.onPointerMove(h.event(1000,25));root=h.render();assert.equal(root.props.style.width,520);
  root.props.onPointerUp(h.event(1000,25));h.render();assert.equal(JSON.parse(h.disk.get(layout.ASSISTANT_WINDOW_KEY)).dockWidth,520);
  root=h.resize(390,700);assert.equal(h.reserved.at(-1),0);assert.ok(root.props.style.width<=374);
  h.button('悬浮 AI 助手').props.onClick();root=h.render();assert.ok(root.props.style.left+root.props.style.width<=382);assert.ok(root.props.style.top+root.props.style.height<=692);
});

test('corrupt saved layout falls back and restored layout cannot leave the screen',()=>{
  const viewport={width:1400,height:900};
  assert.equal(layout.loadAssistantLayout({getItem:()=>'{bad'},viewport).mode,'docked');
  const saved={mode:'floating',dockWidth:510,frame:{x:9999,y:9999,width:900,height:700}};
  const h=layout.loadAssistantLayout({getItem:()=>JSON.stringify(saved)},viewport);
  assert.equal(h.mode,'floating');assert.equal(h.dockWidth,510);
  assert.equal(layout.fitAssistantDockWidth(10000,390),374);
});

test('restoring off-screen floating geometry and shrinking a window keep its header and composer inside the viewport',t=>{
  const h=harness(t,{stored:{mode:'floating',dockWidth:420,frame:{x:9999,y:-500,width:800,height:200}}});
  let root=h.render();assert.ok(root.props.style.left>=8&&root.props.style.top>=8);
  assert.ok(root.props.style.height>=520);assert.ok(root.props.style.left+root.props.style.width<=1392);
  root=h.resize(390,480);assert.ok(root.props.style.left+root.props.style.width<=382);assert.ok(root.props.style.top+root.props.style.height<=472);
});
