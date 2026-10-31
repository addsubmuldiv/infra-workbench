import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as layout from '../src/sidebarLayout.ts';

function harness(t,{stored=null,viewport=1400,storageFails=false}={}){
  const state=[],effects=[],deps=[],listeners=new Map(),disk=new Map();let slot=0,tree;
  if(stored!==null)disk.set(layout.SIDEBAR_KEY,JSON.stringify(stored));
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),
    useState:initial=>{const i=slot++;if(!(i in state))state[i]=typeof initial==='function'?initial():initial;return [state[i],value=>{state[i]=typeof value==='function'?value(state[i]):value}]},
    useRef:current=>{const i=slot++;if(!(i in state))state[i]={current};return state[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){deps[i]=next;effects.push(fn)}}};
  const window={innerWidth:viewport,localStorage:{getItem:key=>disk.get(key)??null,setItem:(key,value)=>{if(storageFails)throw Error('quota');disk.set(key,value)}},
    addEventListener:(type,listener)=>listeners.set(type,listener),removeEventListener:type=>listeners.delete(type)};
  const original=Object.getOwnPropertyDescriptor(globalThis,'window');Object.defineProperty(globalThis,'window',{value:window,writable:true,configurable:true});
  const cleanups=[];t.after(()=>{cleanups.forEach(fn=>fn?.());if(original)Object.defineProperty(globalThis,'window',original);else delete globalThis.window});
  const source=fs.readFileSync(new URL('../src/WorkspaceLayout.tsx',import.meta.url),'utf8');
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./sidebarLayout'?layout:{},exports);
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const render=()=>{slot=0;tree=exports.WorkspaceLayout({children:'workspace'});effects.splice(0).forEach(fn=>cleanups.push(fn()));return tree};
  const divider=()=>nodes(tree).find(n=>n.props?.role==='separator');
  const target={setPointerCapture(){},hasPointerCapture(){return true},releasePointerCapture(){}};
  const event=(x,id=1)=>({button:0,pointerId:id,clientX:x,currentTarget:target,preventDefault(){}});
  return {render,divider,event,disk,resize(width){window.innerWidth=width;listeners.get('resize')?.();render()},get width(){return parseFloat(tree.props.style['--sidebar-width'])},get wide(){return tree.props['data-sidebar-wide']}};
}

test('dragging the separator updates both layout width and persistent preference, then restores it',t=>{
  const h=harness(t);h.render();assert.equal(h.width,258);
  h.divider().props.onPointerDown(h.event(258));h.render();
  h.divider().props.onPointerMove(h.event(550));h.render();assert.equal(h.width,550);assert.equal(h.wide,true);
  h.divider().props.onPointerUp(h.event(550));h.render();
  assert.equal(JSON.parse(h.disk.get(layout.SIDEBAR_KEY)),550);
  assert.equal(h.divider().props['aria-valuenow'],550);
  assert.equal(layout.loadSidebarWidth({getItem:key=>h.disk.get(key)}),550);
});

test('viewport shrink preserves the preferred width while keeping usable room for the main panel',t=>{
  const h=harness(t,{stored:650});h.render();assert.equal(h.width,650);
  h.resize(1000);assert.equal(h.width,520);assert.equal(h.disk.get(layout.SIDEBAR_KEY),'650');
  h.resize(760);assert.equal(h.width,65);
  h.resize(1600);assert.equal(h.width,650);
});

test('keyboard and double click adjust or reset the sidebar; cancelled capture releases drag styling',t=>{
  const h=harness(t);h.render();
  h.divider().props.onKeyDown({key:'ArrowRight',preventDefault(){}});h.render();assert.equal(h.width,278);
  h.divider().props.onKeyDown({key:'End',preventDefault(){}});h.render();assert.equal(h.width,720);
  h.divider().props.onDoubleClick();h.render();assert.equal(h.width,258);
  h.divider().props.onPointerDown(h.event(258));h.render();
  h.divider().props.onPointerMove(h.event(490));h.render();
  h.divider().props.onPointerCancel(h.event(490));
  assert.ok(!h.render().props.className.includes('resizing-sidebar'));
});

test('invalid storage and blocked writes do not break resizing; pointer motion is bounded',t=>{
  assert.equal(layout.loadSidebarWidth({getItem:()=>'{bad'}),258);
  assert.equal(layout.loadSidebarWidth({getItem:()=>'-1'}),258);
  const h=harness(t,{storageFails:true});h.render();
  h.divider().props.onPointerDown(h.event(258));h.render();
  h.divider().props.onPointerMove(h.event(9000));h.render();assert.equal(h.width,720);
  h.divider().props.onPointerUp(h.event(9000));h.render();
  h.divider().props.onPointerDown(h.event(720));h.render();
  h.divider().props.onPointerMove(h.event(-9000));h.render();assert.equal(h.width,220);
});
