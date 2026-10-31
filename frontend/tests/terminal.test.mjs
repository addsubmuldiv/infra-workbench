import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';

// Execute the real component's handlers. Only browser/PTY boundaries are replaced;
// actual rendering and pixel geometry are checked in the live browser as well.
function harness(t,{tabs=null}={}){
  const effects=[],updates=[],phases=[],terminals=[],sockets=[],listeners=new Map(),observers=[];
  const dimensions={cols:100,rows:20};
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
    attachCustomKeyEventHandler(handler){this.keyHandler=handler}
    registerLinkProvider(provider){this.links=provider;return {dispose(){}}}
    getSelection(){return this.selection||''}
    paste(text){const normalized=text.replace(/\r?\n/g,'\r');this.input(this.bracketedPaste&&!this.options.ignoreBracketedPasteMode?'\x1b[200~'+normalized+'\x1b[201~':normalized)}
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
    ResizeObserver:class {constructor(fn){observers.push(fn)}observe(){}disconnect(){}},
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
    if(name==='@xterm/addon-fit')return {FitAddon:class {fit(){}proposeDimensions(){return dimensions}}};
    if(name==='./terminalPaths'){
      const pathExports={};
      const source=fs.readFileSync(new URL('../src/terminalPaths.ts',import.meta.url),'utf8');
      const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
      new Function('exports',compiled)(pathExports);
      return pathExports;
    }
    if(name==='lucide-react'||name.endsWith('.css'))return {};
    throw new Error('Unexpected dependency '+name);
  };
  new Function('require','exports',js)(require,exports);
  const mount=()=>effects.splice(0).forEach(fn=>cleanup.push(fn()));
  const unmount=()=>cleanup.splice(0).reverse().forEach(fn=>fn?.());
  return {...exports,terminals,sockets,updates,phases,listeners,mount,unmount,observers,dimensions};
}

const host={id:'host',target:'synthetic-host',user:'tester'};
const liveTab={id:'tab',host,phase:'running',generation:0};
async function view(t,onDirectory,cwd){
  const h=harness(t),ref={current:null},clipboardListeners=new Map();
  const tree=h.TerminalView({tab:{...liveTab,cwd},active:true,font:13,onPhase:p=>h.phases.push(p),onDirectory},ref);
  tree.props.ref.current={clientWidth:800,clientHeight:400,classList:{contains:()=>true},addEventListener:(name,handler)=>clipboardListeners.set(name,handler),removeEventListener:name=>clipboardListeners.delete(name)};
  h.mount();
  await new Promise(resolve=>setImmediate(resolve));
  h.sockets[0].onopen();h.sockets[0].message({type:'ready'});
  return {...h,ref,clipboardListeners,term:h.terminals[0],socket:h.sockets[0]};
}

const downloadCommand='nohup modelscope download --model Qwen/Qwen3-Omni-30B-A3B-Thinking README.md --local_dir ./dir > qwen3-omni-download.log 2>&1 < /dev/null &';
test('native browser paste preserves single-line shell syntax without paste delimiters',async t=>{
  const {term,socket,clipboardListeners,unmount}=await view(t);term.bracketedPaste=true;
  let prevented=0,stopped=0;
  clipboardListeners.get('paste')({clipboardData:{getData:()=>downloadCommand},preventDefault:()=>prevented++,stopPropagation:()=>stopped++});
  assert.deepEqual(socket.sent.filter(message=>message.type==='input').map(message=>message.data),[downloadCommand]);
  assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(term.options.ignoreBracketedPasteMode,undefined);
  term.input('\x1b[A');assert.equal(socket.sent.at(-1).data,'\x1b[A');
  unmount();assert.equal(clipboardListeners.has('paste'),false);
});

test('Ctrl+Shift+V uses the same single-line compatibility paste exactly once',async t=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{readText:async()=>downloadCommand}}});
  t.after(()=>{if(original)Object.defineProperty(globalThis,'navigator',original);else delete globalThis.navigator});
  const {term,socket}=await view(t);term.bracketedPaste=true;
  assert.equal(term.keyHandler({type:'keydown',ctrlKey:true,shiftKey:true,altKey:false,code:'KeyV',preventDefault(){}}),false);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(socket.sent.filter(message=>message.type==='input').map(message=>message.data),[downloadCommand]);
});

test('multiline paste retains negotiated delimiters and normalizes line endings',async t=>{
  const {term,socket,clipboardListeners}=await view(t);term.bracketedPaste=true;
  clipboardListeners.get('paste')({clipboardData:{getData:()=>"echo '中文'\r\necho done"},preventDefault(){},stopPropagation(){}});
  assert.equal(socket.sent.at(-1).data,"\x1b[200~echo '中文'\recho done\x1b[201~");
  assert.equal(term.options.ignoreBracketedPasteMode,undefined);
});

test('initial connection and unchanged layout do not resize the remote PTY again',async t=>{
  const {socket,observers,dimensions}=await view(t);
  for(const notify of observers)notify();
  assert.equal(socket.sent.filter(m=>m.type==='resize').length,1);
  dimensions.rows=23;
  for(const notify of observers)notify();
  assert.deepEqual(socket.sent.filter(m=>m.type==='resize'),[
    {type:'resize',cols:100,rows:20},{type:'resize',cols:100,rows:23},
  ]);
  for(const notify of observers)notify();
  assert.equal(socket.sent.filter(m=>m.type==='resize').length,2);
});

test('ConPTY compatibility is set before processing login output, only for native sessions',async t=>{
  const {socket,term}=await view(t);
  assert.equal(term.options.windowsPty,undefined);
  const windowsPty={backend:'conpty',buildNumber:26100};
  socket.message({type:'ready',windowsPty});
  assert.deepEqual(term.options.windowsPty,windowsPty);
  socket.message({type:'output',data:'login banner\r\nprompt$ '});
  assert.equal(term.output.at(-1),'login banner\r\nprompt$ ');
});

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

test('Ctrl+C copies a selection, but still reaches the shell when nothing is selected',async t=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');
  const copied=[];
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>copied.push(text)}}});
  t.after(()=>{if(original)Object.defineProperty(globalThis,'navigator',original);else delete globalThis.navigator});
  const {term,socket}=await view(t);let prevented=0;
  const event={type:'keydown',ctrlKey:true,shiftKey:false,altKey:false,code:'KeyC',preventDefault:()=>prevented++};
  term.selection='selected output';
  assert.equal(term.keyHandler(event),false);assert.deepEqual(copied,['selected output']);
  assert.equal(prevented,1);assert.equal(socket.sent.filter(message=>message.type==='input').length,0);
  term.selection='';assert.equal(term.keyHandler(event),true);assert.equal(prevented,1);
});

test('Ctrl+V allows native browser paste without emitting the shell literal-input control byte',async t=>{
  const {term,socket}=await view(t);let prevented=false;
  assert.equal(term.keyHandler({type:'keydown',ctrlKey:true,shiftKey:false,altKey:false,code:'KeyV',preventDefault:()=>{prevented=true}}),false);
  assert.equal(prevented,false);assert.equal(socket.sent.filter(message=>message.type==='input').length,0);
  // xterm's standard paste event processes the clipboard text via onData.
  term.paste('ordinary clipboard text');assert.equal(socket.sent.at(-1).data,'ordinary clipboard text');
});

test('directory clicks carry the terminal host identity instead of the currently selected machine',async t=>{
  const opened=[],{term}=await view(t,(id,path)=>opened.push({id,path}));
  const text='/tmp',line={isWrapped:false,length:4,translateToString:()=>text,getCell:index=>({getChars:()=>text[index],getWidth:()=>1})};
  term.buffer={active:{type:'normal',getLine:index=>index===0?line:undefined}};
  let links;term.links.provideLinks(1,value=>links=value);
  links[0].activate({ctrlKey:true,button:0,preventDefault(){}});
  assert.deepEqual(opened,[{id:'host',path:'/tmp'}]);
});

test('a directory terminal sends its starting path only in the initial handshake',async t=>{
  const {socket}=await view(t,undefined,"/data/中文 ; $(not-a-command)");
  const first=socket.sent.find(message=>message.type==='resize');
  assert.equal(first.cwd,"/data/中文 ; $(not-a-command)");
  assert.equal(socket.sent.filter(message=>message.cwd).length,1);
});

test('opening a terminal in a directory creates a new tab and preserves existing sessions',t=>{
  const h=harness(t,{tabs:[liveTab]});
  h.TerminalDock({request:{id:'request',host,cwd:'/data'},hosts:[host]});h.mount();
  let tabs=[liveTab];for(const update of h.updates.filter(value=>value.index===0))tabs=typeof update.value==='function'?update.value(tabs):update.value;
  assert.equal(tabs.length,2);assert.equal(tabs[0],liveTab);assert.equal(tabs[1].cwd,'/data');
});
