import * as terminalImages from '../src/terminalImages.ts';
import * as terminalArchives from '../src/terminalArchives.ts';
import * as terminalHighlights from '../src/terminalHighlights.ts';
import * as terminalContext from '../src/terminalContext.ts';
import {i18nMock} from './i18n-mock.mjs';
import * as toolTranslations from '../src/toolI18n.ts';
import {workspaceMock} from './workspace-mock.mjs';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import headless from '@xterm/headless';

// Execute the real component's handlers. Only browser/PTY boundaries are replaced;
// actual rendering and pixel geometry are checked in the live browser as well.
function harness(t,{tabs=null,initialStates={}}={}){
  const effects=[],updates=[],phases=[],terminals=[],sockets=[],listeners=new Map(),observers=[];
  const dimensions={cols:100,rows:20};
  const cleanup=[];
  t.after(()=>cleanup.reverse().forEach(fn=>fn?.()));
  let stateIndex=0;
  const react={
    createElement:(type,props,...children)=>({type,props:{...props,children}}),
    forwardRef:fn=>fn,
    useRef:current=>({current}),
    useState:initial=>{const index=stateIndex++;return [index in initialStates?initialStates[index]:index===0&&tabs!==null?tabs:typeof initial==='function'?initial():initial,value=>updates.push({index,value})]},
    useEffect:fn=>effects.push(fn),
    useImperativeHandle:(ref,fn)=>{ref.current=fn()},
  };
  class Terminal {
    cols=80;rows=24;output=[];writes=[];bottomCalls=0;
    constructor(options){this.options=options;terminals.push(this)}
    buffer={active:{type:"normal",viewportY:0,baseY:0,cursorY:0,getLine:()=>undefined}};
    onRender(){return {dispose(){}}} onScroll(){return {dispose(){}}} onWriteParsed(){return {dispose(){}}}
    loadAddon(){} open(){} focus(){} clear(){} dispose(){}
    onData(fn){this.input=fn;return {dispose(){}}}
    onResize(fn){this.resized=fn;return {dispose(){}}}
    resize(cols,rows){this.cols=cols;this.rows=rows;this.resized?.({cols,rows})}
    attachCustomKeyEventHandler(handler){this.keyHandler=handler}
    registerLinkProvider(provider){this.links=provider;return {dispose(){}}}
    getSelection(){return this.selection||''}
    paste(text){const normalized=text.replace(/\r?\n/g,'\r');this.input(this.bracketedPaste&&!this.options.ignoreBracketedPasteMode?'\x1b[200~'+normalized+'\x1b[201~':normalized)}
    write(text,callback){this.output.push(text);this.writes.push(text);callback?.()}
    writeln(text){this.output.push(text);this.writes.push(text+'\r\n')}
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
    if(name==='./terminalImages')return terminalImages;
    if(name==='./terminalArchives'||name==='./terminalArchives.ts')return terminalArchives;
    if(name==='./SafeImageAddon')return {SafeImageAddon:class {dispose(){}}};
    if(name==='./TerminalImageSettings')return ()=>null;
    if(name==='./terminalContext')return terminalContext;
    if(name==='./toolI18n'||name==='./toolI18n.ts')return toolTranslations;
    const translation=i18nMock(name);if(translation)return translation;
    const mock=workspaceMock(name,react);if(mock)return mock;
    if(name==='react')return react;
    if(name==='./TerminalCommands'||name==='./TerminalHighlightSettings')return ()=>null;
    if(name==='./terminalHighlights')return terminalHighlights;
    if(name==='./AppConfirm')return {useAppConfirm:()=>({confirm:async()=>false,confirmation:null})};
    if(name==='@xterm/xterm')return {Terminal};
    if(name==='@xterm/addon-search')return {SearchAddon:class {onDidChangeResults(){return {dispose(){}}}clearDecorations(){}}};
    if(name==='@xterm/addon-fit')return {FitAddon:class {fit(){}proposeDimensions(){return dimensions}}};
    if(name==='./terminalPaths'||name==='./terminalSuggestions'||name==='./terminalWindow'||name==='./windowLayers'||name==='./terminalRenderer'||name==='./browserId'){
      const pathExports={};
      const source=fs.readFileSync(new URL('../src/'+name.slice(2)+'.ts',import.meta.url),'utf8');
      const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
      new Function('exports','require',compiled)(pathExports,require);
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
  find(tree,host.target+' SSH 交互终端').props.ref.current={clientWidth:800,clientHeight:400,classList:{contains:()=>true},addEventListener:(name,handler)=>clipboardListeners.set(name,handler),removeEventListener:name=>clipboardListeners.delete(name)};
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

test('Windows clipboard history synthetic Ctrl+V works without KeyboardEvent.code and pastes only once',async t=>{
  const {term,socket,clipboardListeners}=await view(t);term.bracketedPaste=true;
  for(const event of [{code:'',key:'v',keyCode:86},{code:'',key:'Unidentified',keyCode:86},{key:'V',keyCode:86}]){
    let prevented=false;
    assert.equal(term.keyHandler({...event,type:'keydown',ctrlKey:true,shiftKey:false,altKey:false,preventDefault(){prevented=true}}),false);
    assert.equal(prevented,false); // Keep Chromium's default paste action enabled.
  }
  assert.equal(socket.sent.filter(message=>message.type==='input').length,0);
  clipboardListeners.get('paste')({clipboardData:{getData:()=> 'IWB_HISTORY_SELECTED'},preventDefault(){},stopPropagation(){}});
  assert.deepEqual(socket.sent.filter(message=>message.type==='input').map(message=>message.data),['IWB_HISTORY_SELECTED']);
});

test('synthetic Ctrl+C still copies a selection and preserves shell interrupt when unselected',async t=>{
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator'),copied=[];
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>copied.push(text)}}});
  t.after(()=>{if(original)Object.defineProperty(globalThis,'navigator',original);else delete globalThis.navigator});
  const {term}=await view(t);const event={type:'keydown',ctrlKey:true,altKey:false,code:'',key:'Unidentified',keyCode:67,preventDefault(){}};
  term.selection='selected';assert.equal(term.keyHandler(event),false);assert.deepEqual(copied,['selected']);
  term.selection='';assert.equal(term.keyHandler(event),true);
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


test('history completion only fills a suffix at a confirmed prompt and never executes',async t=>{
  const {term,socket}=await view(t);
  socket.message({type:'workspace',settings:{history_enabled:true},history:[{command:'python train.py'}]});
  term.input('py');
  assert.equal(term.keyHandler({type:'keydown',key:'ArrowRight',preventDefault(){}}),true);
  socket.message({type:'shell',kind:'prompt',cwd:'/tmp',status:0});term.input('py');
  assert.equal(term.keyHandler({type:'keydown',key:'ArrowRight',preventDefault(){}}),false);
  assert.equal(socket.sent.at(-1).data,'thon train.py');
  assert.ok(!socket.sent.at(-1).data.includes('\r'));
  term.input('\r');assert.equal(term.keyHandler({type:'keydown',key:'ArrowRight',preventDefault(){}}),true);
});

test('Ctrl+F stays local and Alt+Enter only requests a server-approved sudo fill',async t=>{
  const {term,socket}=await view(t);const count=socket.sent.length;
  assert.equal(term.keyHandler({type:'keydown',key:'f',ctrlKey:true,preventDefault(){}}),false);
  assert.equal(term.keyHandler({type:'keydown',key:'Enter',altKey:true,preventDefault(){}}),false);
  assert.equal(socket.sent.length,count);
  socket.message({type:'sudo',available:true,waiting:true});
  term.keyHandler({type:'keydown',key:'Enter',altKey:true,preventDefault(){}});
  assert.deepEqual(socket.sent.at(-1),{type:'sudo'});
});

test('closing a persistent tab detaches without the ordinary-session termination confirmation',t=>{
  const tab={...liveTab,session:'persistent-test'};const h=harness(t,{tabs:[tab]});
  const tree=h.TerminalDock({request:null,hosts:[host]});find(tree,'关闭 '+host.target+' 终端').props.onClick();
  assert.ok(h.updates.some(u=>Array.isArray(u.value)&&u.value.length===0));
});

test('Escape closes local search without writing an escape byte to SSH',async t=>{
  const h=harness(t,{initialStates:{6:true}}),ref={current:null};
  const tree=h.TerminalView({tab:liveTab,active:true,font:13,onPhase(){}},ref);
  find(tree,host.target+' SSH 交互终端').props.ref.current={clientWidth:800,clientHeight:400,classList:{contains:()=>true},addEventListener(){},removeEventListener(){}};
  h.mount();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.terminals[0].options.allowProposedApi,true,'SearchAddon highlights require decoration API');
  let prevented=false;h.listeners.get('keydown')({key:'Escape',preventDefault(){prevented=true},stopPropagation(){}});
  assert.ok(prevented);assert.ok(h.updates.some(update=>update.index===6&&update.value===false));
  assert.ok(!h.sockets[0].sent.some(frame=>frame.type==='input'));
});

test('a disconnected terminal reconnects on one key, keeps output and never forwards that key',async t=>{
  const {term,socket,sockets,phases,ref}=await view(t);const cwd='/data/中文 ; $(literal)';
  socket.message({type:'shell',kind:'prompt',cwd,status:0});socket.message({type:'output',data:'OLD-OUTPUT'});
  socket.message({type:'exit'});socket.onclose({code:1000});
  assert.equal(term.output.filter(text=>text.includes('按任意键重新连接')).length,1);
  assert.equal(term.keyHandler({type:'keydown',key:'Shift',preventDefault(){}}),true);
  assert.equal(sockets.length,1);
  assert.equal(term.keyHandler({type:'keydown',key:'a',preventDefault(){}}),false);
  term.input('a');ref.current.reconnect(); // Repeated input while opening cannot start another connection.
  await new Promise(resolve=>setImmediate(resolve));assert.equal(sockets.length,2);
  const next=sockets[1];next.onopen();next.message({type:'ready'});
  assert.equal(next.sent[0].cwd,cwd);assert.equal(next.sent.filter(frame=>frame.type==='input').length,0);
  socket.onclose({code:1006});assert.equal(phases.at(-1),'running');
  term.input('pwd\r');assert.deepEqual(next.sent.filter(frame=>frame.type==='input').map(frame=>frame.data),['pwd\r']);
  assert.ok(term.output.includes('OLD-OUTPUT'));assert.ok(term.output.includes('\x1b[?1049l\x1b[!p'));
  next.message({type:'ready',windowsPty:{backend:'conpty',buildNumber:26100}});next.message({type:'ready'});assert.equal(term.options.windowsPty,undefined);
});

test('copying selected output and searching remain local while disconnected; paste does not reconnect',async t=>{
  const {term,socket,sockets,clipboardListeners}=await view(t);socket.onclose({code:1006});
  let copied='';const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:async text=>{copied=text}}}});t.after(()=>{if(original)Object.defineProperty(globalThis,'navigator',original);else delete globalThis.navigator});
  term.selection='old output';term.keyHandler({type:'keydown',key:'c',code:'KeyC',ctrlKey:true,preventDefault(){}});assert.equal(copied,'old output');
  term.keyHandler({type:'keydown',key:'f',ctrlKey:true,preventDefault(){}});
  clipboardListeners.get('paste')({clipboardData:{getData:()=> 'must-not-run\r'},preventDefault(){},stopPropagation(){}});
  assert.equal(sockets.length,1);
});

for(const alternate of [false,true])test(`reconnect gives a new PTY a clean origin and preserves normal scrollback (alternate=${alternate})`,async t=>{
  const {term,socket,sockets,ref}=await view(t);
  const old='OLD-IP: 192.168.122.1\r\nOLD-PROMPT$ \x1b[15;1HOLD-BELOW-CURSOR\x1b[2;1H';
  socket.message({type:'output',data:old+(alternate?'\x1b[?1049hFULLSCREEN\x1b[4;10r\x1b[?6h':'')});
  socket.onclose({code:1006});ref.current.reconnect();
  await new Promise(resolve=>setImmediate(resolve));
  // Replay the component's actual escape sequences through xterm's parser and
  // buffer, rather than checking that a particular reset string was emitted.
  const display=new headless.Terminal({cols:term.cols,rows:term.rows,allowProposedApi:true,windowsPty:{backend:'conpty',buildNumber:26100}});
  t.after(()=>display.dispose());
  const write=data=>new Promise(resolve=>display.write(data,resolve));
  await write(term.writes.join(''));
  const buffer=display.buffer.active;
  assert.deepEqual([buffer.cursorX,buffer.cursorY],[0,0],'new PTY coordinates start at the top left');
  const lines=(start,count)=>Array.from({length:count},(_,i)=>buffer.getLine(start+i)?.translateToString(true)||'');
  assert.ok(lines(0,buffer.baseY).join('\n').includes('OLD-IP: 192.168.122.1'),'old screen remains in scrollback');
  assert.ok(lines(0,buffer.baseY).join('\n').includes('OLD-BELOW-CURSOR'),'old content below the cursor is preserved too');
  assert.ok(lines(buffer.baseY,term.rows).every(line=>!line),'the new viewport is empty');
  const offset=term.writes.length,next=sockets[1];next.onopen();next.message({type:'ready'});
  next.message({type:'output',data:'NEW-LOGIN\r\n\x1b[2;1HREADY$ '});
  socket.message({type:'output',data:'STALE-OUTPUT'});socket.onclose({code:1006});
  await write(term.writes.slice(offset).join(''));
  assert.deepEqual(lines(buffer.baseY,2),['NEW-LOGIN','READY$ ']);
  assert.deepEqual([buffer.cursorX,buffer.cursorY],[7,1]);
  assert.ok(!lines(buffer.baseY,term.rows).join('\n').includes('STALE-OUTPUT'));
});

function terminalNode(node,component){
  if(!node||typeof node!=='object')return;
  if(node.type===component)return node;
  return (node.props?.children||[]).flat(Infinity).map(child=>terminalNode(child,component)).find(Boolean);
}
function updatedTabs(h,initial){let tabs=initial;for(const update of h.updates.filter(value=>value.index===0))tabs=typeof update.value==='function'?update.value(tabs):update.value;return tabs}

test('duplicate opens an independent tab in the latest confirmed cwd and keeps the source alive',t=>{
  const original={...liveTab,cwd:'/original'};const h=harness(t,{tabs:[original],initialStates:{1:'tab'}});
  const tree=h.TerminalDock({request:null,hosts:[host]});terminalNode(tree,h.TerminalView).props.ref({cwd:()=>'/current/中文 ; $(literal)'});
  find(tree,'复制当前终端').props.onClick();const tabs=updatedTabs(h,[original]);
  assert.equal(tabs.length,2);assert.equal(tabs[0],original);assert.equal(tabs[1].host.id,host.id);assert.equal(tabs[1].cwd,'/current/中文 ; $(literal)');assert.equal(tabs[1].session,undefined);assert.notEqual(tabs[1].id,original.id);
});

test('duplicate never guesses a home directory when the shell cwd is unavailable',t=>{
  const h=harness(t,{tabs:[liveTab],initialStates:{1:'tab'}});const tree=h.TerminalDock({request:null,hosts:[host]});terminalNode(tree,h.TerminalView).props.ref({cwd:()=>undefined});
  find(tree,'复制当前终端').props.onClick();assert.equal(updatedTabs(h,[liveTab]).length,1);assert.ok(h.updates.some(value=>value.index===7&&value.value.includes('目录')));
});

test('duplicating tmux creates a separate persistent session in the same cwd',async t=>{
  const original={...liveTab,session:'source-session'};const h=harness(t,{tabs:[original],initialStates:{1:'tab'}});const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({id:'new-session'})}};
  const tree=h.TerminalDock({request:null,hosts:[host]});terminalNode(tree,h.TerminalView).props.ref({cwd:()=>'/data/training'});find(tree,'复制当前终端').props.onClick();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(JSON.parse(calls[0].options.body).cwd,'/data/training');const tabs=updatedTabs(h,[original]);assert.equal(tabs.length,2);assert.equal(tabs[1].session,'new-session');assert.equal(tabs[0].session,'source-session');assert.equal(tabs[1].cwd,'/data/training');
});

test('unsupported shell metadata cannot replace cwd with the fallback placeholder',async t=>{
  const {socket,ref}=await view(t);socket.message({type:'shell',kind:'prompt',cwd:'/real/path',status:0});assert.equal(ref.current.cwd(),'/real/path');socket.message({type:'shell',kind:'unsupported',cwd:'/',status:0});assert.equal(ref.current.cwd(),undefined);
});

test('Command copy, paste and find stay local while Control+C remains a shell interrupt',async t=>{
  const {term,socket,clipboardListeners}=await view(t);let copied='';
  const original=Object.getOwnPropertyDescriptor(globalThis,'navigator');Object.defineProperty(globalThis,'navigator',{configurable:true,value:{platform:'MacIntel',clipboard:{writeText:async text=>{copied=text}}}});t.after(()=>{if(original)Object.defineProperty(globalThis,'navigator',original);else delete globalThis.navigator});
  term.selection='中文 output';
  assert.equal(term.keyHandler({type:'keydown',key:'c',code:'KeyC',metaKey:true,ctrlKey:false,preventDefault(){}}),false);
  assert.equal(copied,'中文 output');term.selection='';
  assert.equal(term.keyHandler({type:'keydown',key:'c',code:'KeyC',metaKey:true,ctrlKey:false,preventDefault(){}}),false);
  assert.equal(term.keyHandler({type:'keydown',key:'c',code:'KeyC',ctrlKey:true,metaKey:false,preventDefault(){}}),true);
  assert.equal(term.keyHandler({type:'keydown',key:'v',code:'KeyV',metaKey:true,ctrlKey:false,preventDefault(){}}),false);
  clipboardListeners.get('paste')({clipboardData:{getData:()=> '中文 paste'},preventDefault(){},stopPropagation(){}});
  assert.equal(term.keyHandler({type:'keydown',key:'f',metaKey:true,ctrlKey:false,preventDefault(){}}),false);
  assert.deepEqual(socket.sent.filter(frame=>frame.type==='input').map(frame=>frame.data),['中文 paste']);
});
test('archive click fills one quoted command only at an empty confirmed prompt',async t=>{
 const opened=[],{term,socket}=await view(t,(id,path)=>opened.push(path));
 const printed='/data/训练 a\'b;.tar.gz';
 const source=new headless.Terminal({cols:8,rows:20,allowProposedApi:true});t.after(()=>source.dispose());
 await new Promise(resolve=>source.write(printed,resolve));term.cols=8;term.buffer=source.buffer;
 const click=()=>{let links;term.links.provideLinks(2,value=>links=value);links[0].activate({metaKey:true,button:0,preventDefault(){}})};
 click();assert.equal(socket.sent.filter(m=>m.type==='input').length,0);
 socket.message({type:'shell',kind:'prompt',cwd:'/data',status:0});click();
 const inputs=socket.sent.filter(m=>m.type==='input');assert.equal(inputs.length,1);assert.equal(inputs[0].data,"tar -xf '/data/训练 a'\\''b;.tar.gz' -C '/data' --keep-old-files");assert.ok(!/[\r\n]/.test(inputs[0].data));assert.deepEqual(opened,[]);
 click();assert.equal(socket.sent.filter(m=>m.type==='input').length,1);
 socket.message({type:'shell',kind:'start',cwd:'/data'});click();assert.equal(socket.sent.filter(m=>m.type==='input').length,1);
});
test('relative archives need a confirmed cwd and preserve an existing command',async t=>{
 const {term,socket}=await view(t);
 const text='./data.zip',line={isWrapped:false,length:text.length,translateToString:()=>text,getCell:index=>({getChars:()=>text[index],getWidth:()=>1})};term.buffer={active:{type:'normal',getLine:index=>index===0?line:undefined}};
 const click=()=>{let links;term.links.provideLinks(1,value=>links=value);links[0].activate({ctrlKey:true,button:0,preventDefault(){}})};
 socket.message({type:'shell',kind:'prompt',status:0});click();assert.equal(socket.sent.filter(m=>m.type==='input').length,0);
 socket.message({type:'shell',kind:'prompt',cwd:'/data',status:0});term.input('keep my command');click();assert.deepEqual(socket.sent.filter(m=>m.type==='input').map(m=>m.data),['keep my command']);
});
