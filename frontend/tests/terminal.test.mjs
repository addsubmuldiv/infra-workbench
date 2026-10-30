import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

// Execute the real component's handlers. Only browser/PTY boundaries are replaced;
// actual rendering and pixel geometry are checked in the live browser as well.
function harness(t,{tabs=null}={}){
  const effects=[],updates=[],phases=[],terminals=[],sockets=[],listeners=new Map();
  const cleanup=[];
  t.after(()=>cleanup.reverse().forEach(fn=>fn?.()));
  let stateIndex=0;
  const react={
    createElement:(type,props,...children)=>({type,props:{...props,children}}),
    forwardRef:fn=>fn,
    useRef:current=>({current}),
    useState:initial=>{const index=stateIndex++;return [index===0&&tabs!==null?tabs:typeof initial==='function'?initial():initial,value=>updates.push({index,value})]},
    useEffect:fn=>effects.push(fn),
    useImperativeHandle:(ref,fn)=>{ref.current=fn()},
  };
  class Terminal {
    cols=80;rows=24;output=[];bottomCalls=0;
    constructor(options){this.options=options;terminals.push(this)}
    loadAddon(){} open(){} focus(){} clear(){} dispose(){}
    onData(fn){this.input=fn;return {dispose(){}}}
    onResize(fn){this.resized=fn;return {dispose(){}}}
    resize(cols,rows){this.cols=cols;this.rows=rows;this.resized?.({cols,rows})}
    attachCustomKeyEventHandler(){}
    write(text,callback){this.output.push(text);callback?.()}
    writeln(text){this.output.push(text)}
    scrollToBottom(){this.bottomCalls++}
  }
  class Socket {
    static OPEN=1;
    readyState=1;sent=[];
    constructor(){sockets.push(this)}
    send(data){this.sent.push(JSON.parse(data))}
    close(){}
    message(message){this.onmessage({data:JSON.stringify(message)})}
  }
  const globals={
    WebSocket:Socket,
    fetch:async()=>({ok:true,json:async()=>({ticket:'test-ticket'})}),
    location:{protocol:'http:',host:'localhost'},
    document:{documentElement:{style:{setProperty(){},removeProperty(){}}}},
    window:{confirm:()=>false,addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:type=>listeners.delete(type)},
    getComputedStyle:()=>({getPropertyValue:()=>''}),
    ResizeObserver:class {observe(){}disconnect(){}},
    MutationObserver:class {observe(){}disconnect(){}},
    requestAnimationFrame:fn=>{fn();return 1},cancelAnimationFrame:()=>{},
  };
  for(const [name,value] of Object.entries(globals)){
    const original=Object.getOwnPropertyDescriptor(globalThis,name);
    Object.defineProperty(globalThis,name,{configurable:true,writable:true,value});
    t.after(()=>{if(original)Object.defineProperty(globalThis,name,original);else delete globalThis[name]});
  }
  const source=fs.readFileSync(new URL('../src/TerminalDock.tsx',import.meta.url),'utf8')+'\nexport {TerminalView};';
  const js=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,esModuleInterop:true}}).outputText;
  const exports={};
  const require=name=>{
    if(name==='react')return react;
    if(name==='@xterm/xterm')return {Terminal};
    if(name==='@xterm/addon-fit')return {FitAddon:class {fit(){}proposeDimensions(){return {cols:100,rows:20}}}};
    if(name==='lucide-react'||name.endsWith('.css'))return {};
    throw new Error('Unexpected dependency '+name);
  };
  new Function('require','exports',js)(require,exports);
  const mount=()=>effects.splice(0).forEach(fn=>cleanup.push(fn()));
  const unmount=()=>cleanup.splice(0).reverse().forEach(fn=>fn?.());
  return {...exports,terminals,sockets,updates,phases,listeners,mount,unmount};
}

const host={id:'host',target:'synthetic-host',user:'tester'};
const liveTab={id:'tab',host,phase:'running',generation:0};
async function view(t){
  const h=harness(t),ref={current:null};
  const tree=h.TerminalView({tab:liveTab,active:true,font:13,onPhase:p=>h.phases.push(p)},ref);
  tree.props.ref.current={clientWidth:800,clientHeight:400,classList:{contains:()=>true}};
  h.mount();
  await new Promise(resolve=>setImmediate(resolve));
  h.sockets[0].onopen();h.sockets[0].message({type:'ready'});
  return {...h,ref,term:h.terminals[0],socket:h.sockets[0]};
}

test('long Unicode paste stays within frame limits and preserves all characters',async t=>{
  const {term,socket}=await view(t);
  const data='a'.repeat(8191)+'😀'+'中文'.repeat(14000)+'\r';
  term.input(data);
  const frames=socket.sent.filter(m=>m.type==='input');
  assert.ok(frames.length>1);
  assert.ok(frames.every(m=>m.data.length<=16384));
  assert.equal(frames.map(m=>m.data).join(''),data);
  assert.ok(frames.every(m=>!/[\uD800-\uDBFF]$/.test(m.data)&&! /^[\uDC00-\uDFFF]/.test(m.data)));
});

test('server errors remain visible as errors after exit and websocket close',async t=>{
  const {socket,phases}=await view(t);
  socket.message({type:'error',message:'connection failed'});
  socket.message({type:'exit'});
  socket.onclose({code:1000});
  assert.equal(phases.at(-1),'error');
});

test('recoverable warnings keep a working terminal usable',async t=>{
  const {socket,term,phases}=await view(t);
  socket.message({type:'warning',message:'input rejected'});
  term.input('echo still-connected\r');
  assert.equal(phases.at(-1),'running');
  assert.ok(term.output.some(text=>text.includes('input rejected')));
  assert.ok(socket.sent.some(m=>m.type==='input'&&m.data==='echo still-connected\r'));
});

function find(node,label){
  if(!node||typeof node!=='object')return;
  if(node.props?.['aria-label']===label)return node;
  return [node.props?.children].flat(Infinity).map(child=>find(child,label)).find(Boolean);
}

test('canceling single-tab close preserves an active session',t=>{
  const h=harness(t,{tabs:[liveTab]});
  const tree=h.TerminalDock({request:null,hosts:[host]});
  find(tree,'关闭 synthetic-host 终端').props.onClick();
  assert.equal(h.updates.length,0);
});

test('refresh is guarded while sessions are live and listener is removed on unmount',t=>{
  const h=harness(t,{tabs:[liveTab]});
  h.TerminalDock({request:null,hosts:[host]});h.mount();
  const event=new Event('beforeunload',{cancelable:true});
  h.listeners.get('beforeunload')?.(event);
  assert.ok(event.defaultPrevented);
  h.unmount();
  assert.equal(h.listeners.has('beforeunload'),false);
});

test('closed sessions do not prevent leaving the page',t=>{
  const h=harness(t,{tabs:[{...liveTab,phase:'closed'}]});
  h.TerminalDock({request:null,hosts:[host]});h.mount();
  assert.equal(h.listeners.has('beforeunload'),false);
});
