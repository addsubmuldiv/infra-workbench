import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import * as frames from '../src/terminalWindow.ts';

function harness(t){
  const state=[],effects=[],deps=[],cleanups=[],disk=new Map();let slot=0,tree;
  const host={id:'fixture',target:'training-node',user:'fixture'};
  const tabs=[{id:'tab',host,phase:'running',generation:0}];
  const react={createElement:(type,props,...children)=>({type,props:{...props,children}}),forwardRef:fn=>fn,
    useState:initial=>{const i=slot++;if(!(i in state))state[i]=i===0?tabs:i===1?'tab':typeof initial==='function'?initial():initial;return [state[i],v=>{state[i]=typeof v==='function'?v(state[i]):v}]},
    useRef:current=>{const i=slot++;if(!(i in state))state[i]={current};return state[i]},
    useEffect:(fn,next)=>{const i=slot++;if(!deps[i]||next.some((v,j)=>v!==deps[i][j])){deps[i]=next;effects.push(fn)}}};
  const globals={window:{innerWidth:1400,innerHeight:900,localStorage:{getItem:key=>disk.get(key)??null,setItem:(key,value)=>disk.set(key,value)},addEventListener(){},removeEventListener(){},confirm:()=>false},
    document:{documentElement:{style:{setProperty(){},removeProperty(){}}}},requestAnimationFrame:fn=>{fn();return 1}};
  t.after(()=>cleanups.forEach(fn=>fn?.()));
  for(const [key,value] of Object.entries(globals)){const original=Object.getOwnPropertyDescriptor(globalThis,key);Object.defineProperty(globalThis,key,{configurable:true,value,writable:true});t.after(()=>{if(original)Object.defineProperty(globalThis,key,original);else delete globalThis[key]})}
  const js=ts.transpileModule(fs.readFileSync(new URL('../src/TerminalDock.tsx',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};new Function('require','exports',js)(name=>name==='react'?react:name==='./AppConfirm'?{useAppConfirm:()=>({confirm:async()=>false,confirmation:null})}:name==='./terminalWindow'?frames:{},exports);
  const nodes=n=>!n||typeof n!=='object'?[]:[n,...(n.props?.children||[]).flat(Infinity).flatMap(nodes)];
  const render=()=>{slot=0;tree=exports.TerminalDock({request:null,hosts:[host]});effects.splice(0).forEach(fn=>cleanups.push(fn()));return tree};
  const find=predicate=>nodes(tree).find(predicate);
  const button=name=>find(n=>n.type==='button'&&n.props['aria-label']===name);
  const event=(x=100,y=100)=>({button:0,pointerId:9,clientX:x,clientY:y,target:{closest:()=>false},currentTarget:{setPointerCapture(){},hasPointerCapture(){return true},releasePointerCapture(){}},preventDefault(){}});
  return {render,find,button,event,disk};
}

test('the terminal floats, moves and resizes without replacing mounted session views',t=>{
  const h=harness(t);let root=h.render();const original={...root.props.style};
  const session=h.find(n=>n.props?.tab?.id==='tab');
  h.find(n=>n.props?.className==='terminal-topbar').props.onPointerDown(h.event());
  root.props.onPointerMove(h.event(40,40));root=h.render();
  assert.equal(root.props.style.left,original.left-60);assert.equal(root.props.style.top,original.top-60);root.props.onPointerUp(h.event(40,40));
  h.find(n=>n.props?.['aria-label']==='调整终端大小').props.onPointerDown(h.event());
  root.props.onPointerMove(h.event(140,140));root=h.render();
  assert.equal(root.props.style.width,original.width+40);assert.equal(root.props.style.height,original.height+40);
  assert.equal(h.find(n=>n.props?.tab?.id==='tab').type,session.type);
  assert.equal(h.find(n=>n.props?.tab?.id==='tab').props.key,'tab');
});

test('minimizing keeps the session mounted and restores the exact floating frame',t=>{
  const h=harness(t);let root=h.render();const original={...root.props.style};
  h.button('最小化终端').props.onClick();root=h.render();
  assert.equal(root.props.style.width,264);assert.equal(root.props.style.right,16);assert.equal(root.props.style.bottom,16);
  assert.ok(h.button('恢复 SSH 终端'));
  assert.ok(h.find(n=>n.props?.tab?.id==='tab'),'minimize must keep the terminal view mounted');
  assert.equal(h.find(n=>n.props?.className==='terminal-body').props.style.display,'none');
  h.button('恢复 SSH 终端').props.onClick();root=h.render();assert.deepEqual(root.props.style,original);
});

test('maximize and restore preserve the normal frame and title buttons do not start a move',t=>{
  const h=harness(t);let root=h.render();const original={...root.props.style};
  h.button('最大化终端').props.onClick();root=h.render();assert.equal(root.props.style.width,1376);assert.equal(root.props.style.height,876);
  h.button('还原终端').props.onClick();root=h.render();assert.deepEqual(root.props.style,original);
  const e=h.event();e.target.closest=()=>true;
  h.find(n=>n.props?.className==='terminal-topbar').props.onPointerDown(e);
  root.props.onPointerMove(h.event(700,700));assert.deepEqual(h.render().props.style,original);
});

test('all resize edges preserve viewport bounds and corrupt saved frames fall back safely',()=>{
  const viewport={width:1200,height:800},frame={x:200,y:200,width:800,height:450};
  for(const edge of ['n','s','e','w','ne','nw','se','sw']){
    const next=frames.resizeTerminalFrame(frame,edge,-5000,5000,viewport);
    assert.ok(next.x>=12&&next.y>=12&&next.width>=520&&next.height>=280);
    assert.ok(next.x+next.width<=1188&&next.y+next.height<=788);
  }
  const fallback=frames.loadTerminalFrame({getItem:()=>'{broken'},viewport);
  assert.ok(Number.isFinite(fallback.x)&&fallback.x>=12);
});

test('dragging does not write geometry to storage until release, including cancellation',t=>{
  const h=harness(t);let root=h.render();const initial=[...h.disk.values()];
  h.find(n=>n.props?.className==='terminal-topbar').props.onPointerDown(h.event());h.render();
  root.props.onPointerMove(h.event(200,160));root=h.render();
  assert.deepEqual([...h.disk.values()],initial,'do not synchronously save every pointer update');
  const finalFrame={...root.props.style};root.props.onPointerCancel(h.event());h.render();
  assert.notDeepEqual([...h.disk.values()],initial);
  assert.equal(JSON.parse([...h.disk.values()][0]).x,finalFrame.left);
});
