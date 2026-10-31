import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Terminal as XTerminal} from '@xterm/xterm';
import {FitAddon} from '@xterm/addon-fit';
import TerminalCommands from './TerminalCommands';
import {SearchAddon} from '@xterm/addon-search';
import {ChevronsDown,ChevronDown,ChevronUp,Copy,CopyPlus,Maximize2,Minimize2,Plus,RefreshCw,ShieldCheck,Terminal,Trash2,X} from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import './terminal.css';
import {directoryLinkProvider} from './terminalPaths';
import {emptyCommandLine,editCommandLine,historySuggestion,type CommandLine,type HistoryCommand} from './terminalSuggestions';
import {TERMINAL_FRAME_KEY,fitTerminalFrame,loadTerminalFrame,moveTerminalFrame,resizeTerminalFrame,terminalFrameStyle,type TerminalFrame} from './terminalWindow';
import {activateFloatingWindow,registerFloatingWindow} from './windowLayers';

const terminalViewport=()=>({width:window.innerWidth||1200,height:window.innerHeight||900});
function terminalStorage(){try{return window.localStorage??null}catch{return null}}

type Host={id:string;target:string;user:string|null};
export type TerminalRequest={id:string;host:Host;cwd?:string};
type Phase='connecting'|'running'|'closed'|'error';
type Tab={id:string;host:Host;phase:Phase;generation:number;cwd?:string;session?:string};
type Handle={clear:()=>void;copy:()=>void;focus:()=>void;scrollToBottom:()=>void;search:()=>void;cwd:()=>string|undefined;reconnect:()=>void};
const labels:Record<Phase,string>={connecting:'正在连接',running:'会话运行中',closed:'连接已结束',error:'连接失败'};
// Windows clipboard-history injection can omit code on its synthetic Ctrl+V.
const clipboardKey=(event:KeyboardEvent,key:'c'|'v')=>event.code==='Key'+key.toUpperCase()||(!event.code&&(event.key?.toLowerCase()===key||event.keyCode===key.toUpperCase().charCodeAt(0)));
const validDirectory=(value:unknown):value is string=>typeof value==='string'&&value.startsWith('/')&&value.length<=4096&&!/[\x00-\x1f\x7f]/.test(value);
const reconnectKey=(event:KeyboardEvent)=>!event.repeat&&!event.isComposing&&event.keyCode!==229&&!!event.key&&!['Shift','Control','Alt','Meta','AltGraph','CapsLock','NumLock','ScrollLock','Process','Unidentified','Dead'].includes(event.key);

function palette(){
  const css=getComputedStyle(document.documentElement);
  const get=(name:string)=>css.getPropertyValue(name).trim();
  return {background:get('--term-bg'),foreground:get('--term-fg'),cursor:get('--accent'),selectionBackground:get('--term-selection'),
    black:'#334155',red:'#d26566',green:'#2e9d78',yellow:'#b68d46',blue:'#5d8fd4',magenta:'#a57ad2',cyan:'#439ca9',white:'#bac6d4',
    brightBlack:'#8090a4',brightRed:'#ef8c8c',brightGreen:'#7bcea7',brightYellow:'#e6c488',brightBlue:'#8bb5ef',brightMagenta:'#c5a3ea',brightCyan:'#89d3d6',brightWhite:'#f0f4fa'};
}

const TerminalView=forwardRef<Handle,{tab:Tab;active:boolean;font:number;onPhase:(phase:Phase)=>void;onDirectory?:(hostId:string,path:string)=>void}>(function TerminalView({tab,active,font,onPhase,onDirectory},ref){
  const [suggestion,setSuggestion]=useState(''),[shellStatus,setShellStatus]=useState('正在检测增强功能');
  const [workspace,setWorkspace]=useState<any>(null),[tools,setTools]=useState(false);
  const [lastResult,setLastResult]=useState('');
  const [sudoAvailable,setSudoAvailable]=useState(false),sudoRef=useRef(false);
  const [searchOpen,setSearchOpen]=useState(false),[query,setQuery]=useState(''),[caseSensitive,setCaseSensitive]=useState(false),[regex,setRegex]=useState(false),[searchResult,setSearchResult]=useState('0 / 0');
  const searchRef=useRef<SearchAddon|null>(null),searchInput=useRef<HTMLInputElement>(null);
  const commandLine=useRef<CommandLine>(emptyCommandLine()),atPrompt=useRef(false),history=useRef<HistoryCommand[]>([]),suggestionRef=useRef('');
  const updateSuggestion=()=>{const value=atPrompt.current?historySuggestion(commandLine.current,history.current):'';suggestionRef.current=value;setSuggestion(value)};
  const element=useRef<HTMLDivElement>(null),terminal=useRef<XTerminal|null>(null),resizeRef=useRef<(()=>void)|null>(null);
  const socketRef=useRef<WebSocket|null>(null),pasteRef=useRef<((text:string)=>void)|null>(null);
  const cwdRef=useRef<string|undefined>(tab.cwd),reconnectRef=useRef<(()=>void)|null>(null);
  const directoryRef=useRef(onDirectory);directoryRef.current=onDirectory;
  useImperativeHandle(ref,()=>({cwd:()=>cwdRef.current,reconnect:()=>reconnectRef.current?.(),search:()=>setSearchOpen(true),clear:()=>terminal.current?.clear(),focus:()=>terminal.current?.focus(),scrollToBottom:()=>terminal.current?.scrollToBottom(),copy:()=>{
    const text=terminal.current?.getSelection();if(text)navigator.clipboard.writeText(text).catch(()=>{});
  }}),[]);
  useEffect(()=>{
    let disposed=false,connected=false,failed=false,connecting=false,retryArmed=false,announced=false,attempt=0;
    let remoteSize:{cols:number;rows:number}|null=null;
    const phase=(next:Phase)=>{if(next==='error')failed=true;onPhase(next==='closed'&&failed?'error':next)};
    const term=new XTerminal({cursorBlink:true,cursorStyle:'bar',fontFamily:'"Cascadia Code","Cascadia Mono",Consolas,"Microsoft YaHei",monospace',fontSize:font,
      // The official SearchAddon uses registerDecoration for match highlights.
      lineHeight:1.28,letterSpacing:.2,scrollback:5000,theme:palette(),allowProposedApi:true,convertEol:false});
    const fit=new FitAddon();term.loadAddon(fit);term.open(element.current!);terminal.current=term;
    const search=new SearchAddon({highlightLimit:1000});term.loadAddon(search);searchRef.current=search;
    const searchResults=search.onDidChangeResults(result=>setSearchResult(result.resultIndex<0&&result.resultCount?'超过 1000 个匹配':`${result.resultIndex+1} / ${result.resultCount}`));
    const pathLinks=directoryLinkProvider(term,path=>directoryRef.current?.(tab.host.id,path),window);
    const registeredLinks=term.registerLinkProvider(pathLinks);
    const links={dispose(){pathLinks.dispose();registeredLinks.dispose()}};
    const send=(message:unknown)=>{if(socketRef.current?.readyState===WebSocket.OPEN)socketRef.current.send(JSON.stringify(message))};
    const resize=()=>{
      if(!element.current||element.current.clientWidth<=10||element.current.clientHeight<=10)return;
      const dimensions=fit.proposeDimensions();
      if(dimensions)term.resize(Math.min(500,Math.max(2,dimensions.cols)),Math.min(200,Math.max(2,dimensions.rows)));
      // ConPTY may repaint and reposition its cursor even for a repeated size.
      if(connected&&(remoteSize?.cols!==term.cols||remoteSize?.rows!==term.rows)){
        remoteSize={cols:term.cols,rows:term.rows};send({type:'resize',...remoteSize});
      }
    };
    resizeRef.current=resize;
    const observer=new ResizeObserver(resize);observer.observe(element.current!);
    const themeObserver=new MutationObserver(()=>{term.options.theme=palette()});themeObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
    const input=term.onData(data=>{
      if(!connected)return;
      if(atPrompt.current){commandLine.current=editCommandLine(commandLine.current,data);updateSuggestion();if(/[\r\n\x03]/.test(data))atPrompt.current=false}
      // Bound each frame and never split a UTF-16 surrogate pair (emoji, etc.).
      for(let start=0;start<data.length;){
        let end=Math.min(start+8192,data.length);
        if(end<data.length&&data.charCodeAt(end-1)>=0xd800&&data.charCodeAt(end-1)<=0xdbff&&data.charCodeAt(end)>=0xdc00&&data.charCodeAt(end)<=0xdfff)end--;
        send({type:'input',data:data.slice(start,end)});start=end;
      }
    });
    const paste=(text:string)=>{
      // Single-line commands need no delimiters; keep negotiated bracketed
      // paste for multiline text and leave keyboard escapes untouched.
      const previous=term.options.ignoreBracketedPasteMode;
      if(!/[\r\n]/.test(text))term.options.ignoreBracketedPasteMode=true;
      try{term.paste(text)}finally{term.options.ignoreBracketedPasteMode=previous}
    };
    pasteRef.current=paste;
    const clipboardPaste=(event:ClipboardEvent)=>{
      if(!event.clipboardData)return;
      event.preventDefault();event.stopPropagation();paste(event.clipboardData.getData('text/plain'));
    };
    const container=element.current!;
    container.addEventListener('paste',clipboardPaste,true);
    term.attachCustomKeyEventHandler(event=>{
      if(event.type==='keydown'&&(event.ctrlKey||event.metaKey)&&!event.altKey&&event.key?.toLowerCase()==='f'){event.preventDefault();setSearchOpen(true);return false}
      if(event.type==='keydown'&&(event.ctrlKey||event.metaKey)&&!event.altKey&&clipboardKey(event,'c')&&term.getSelection()){
        event.preventDefault();navigator.clipboard.writeText(term.getSelection()).catch(()=>{});return false;
      }
      if(event.type==='keydown'&&event.metaKey&&!event.altKey&&clipboardKey(event,'c'))return false;
      if(event.type==='keydown'&&retryArmed&&reconnectKey(event)){event.preventDefault();void start();return false}
      if(event.type==='keydown'&&event.key==='Enter'&&event.altKey&&!event.ctrlKey){event.preventDefault();if(sudoRef.current)send({type:'sudo'});return false}
      if(event.type==='keydown'&&event.key==='ArrowRight'&&!event.ctrlKey&&!event.altKey&&!event.metaKey&&suggestionRef.current&&atPrompt.current){event.preventDefault();paste(suggestionRef.current);return false}
      if(event.type==='keydown'&&event.ctrlKey&&!event.altKey&&clipboardKey(event,'c')){
        const selected=term.getSelection();
        if(selected||event.shiftKey){event.preventDefault();if(selected)navigator.clipboard.writeText(selected).catch(()=>{});return false}
      }
      if(event.type==='keydown'&&(event.ctrlKey||event.metaKey)&&!event.altKey&&clipboardKey(event,'v')){
        if(!event.shiftKey)return false; // Let the browser paste event feed xterm; do not send the shell's Ctrl+V byte.
        event.preventDefault();navigator.clipboard.readText().then(text=>{if(!disposed)paste(text)}).catch(()=>{});return false;
      }
      return true;
    });
    const disconnected=(next:Phase)=>{
      connected=false;connecting=false;retryArmed=true;phase(next);
      atPrompt.current=false;sudoRef.current=false;setSudoAvailable(false);updateSuggestion();
      setShellStatus('连接已断开 · 按任意键重新连接');
      if(!announced){announced=true;term.writeln('\r\n\x1b[90m── SSH 会话已结束 ──\r\n按任意键重新连接\x1b[0m')}
    };
    async function start(){
      if(disposed||connecting)return;
      const previous=socketRef.current;
      const retry=retryArmed||connected;
      const currentAttempt=++attempt;
      connecting=true;retryArmed=false;connected=false;failed=false;announced=false;remoteSize=null;
      socketRef.current=null;previous?.close();
      atPrompt.current=false;commandLine.current=emptyCommandLine();sudoRef.current=false;setSudoAvailable(false);updateSuggestion();
      setShellStatus(retry?'正在重新连接…':'正在连接…');
      if(retry){
        // Leave a disconnected full-screen app and reset its input modes.
        term.write('\x1b[?1049l\x1b[!p');
        term.writeln('\r\n\x1b[90m正在重新连接…\x1b[0m');
        // Archive the whole old viewport, including lines below its cursor.
        // A new ConPTY starts at (0,0): retaining the old cursor/screen lets
        // its absolute cursor updates overwrite the previous login output.
        term.write(`\x1b[${term.rows};1H`+'\r\n'.repeat(term.rows)+'\x1b[H\x1b[2J');
        term.scrollToBottom();
      }
      phase('connecting');resize();
      try{
        const response=await fetch('/api/hosts/'+tab.host.id+'/terminal-ticket',{method:'POST',headers:{'X-IWB':'1'}});
        const data=await response.json();if(!response.ok)throw new Error(data.detail||'无法创建终端会话');
        if(disposed||currentAttempt!==attempt)return;
        const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/terminal/'+tab.host.id,['iwb-terminal',data.ticket]);
        socketRef.current=ws;
        ws.onopen=()=>{if(disposed||currentAttempt!==attempt)return;resize();remoteSize={cols:term.cols,rows:term.rows};send({type:'resize',...remoteSize,...(cwdRef.current?{cwd:cwdRef.current}:{}),...(data.workspace?{enhanced:true,...(tab.session?{session:tab.session}:{})}:{})});if(!data.workspace)setShellStatus('普通终端 · 更新后台后可启用增强功能')};
        ws.onmessage=event=>{
          if(disposed||currentAttempt!==attempt)return;
          const message=JSON.parse(event.data);
          if(message.type==='completion'){setLastResult(`上次命令 ${message.seconds} 秒 · 退出码 ${message.status}`);return}
          if(message.type==='sudo'){sudoRef.current=!!message.available;setSudoAvailable(!!message.available);return}
          if(message.type==='workspace'){setWorkspace(message);history.current=message.settings?.history_enabled===false?[]:message.history||[];updateSuggestion();return}
          if(message.type==='shell'){
            if(['prompt','start'].includes(message.kind)&&validDirectory(message.cwd))cwdRef.current=message.cwd;
            if(message.kind==='unsupported')cwdRef.current=undefined;
            if(message.result)setLastResult(`上次命令 ${message.result.seconds} 秒 · 退出码 ${message.result.status}`);
            atPrompt.current=message.kind==='prompt';commandLine.current=emptyCommandLine();updateSuggestion();
            setShellStatus(message.kind==='unsupported'?'普通终端 · 增强功能需要远端 Python 3 和 Bash 4.4+':message.kind==='prompt'?'命令行就绪 · '+message.cwd:'命令执行中');return;
          }
          if(message.type==='ready'){
            // Set native Windows compatibility before parsing login output.
            // AsyncSSH sessions use the default xterm behavior instead.
            term.options.windowsPty=message.windowsPty?.backend==='conpty'?message.windowsPty:undefined;
            connected=true;connecting=false;retryArmed=false;phase('running');if(tab.session)setShellStatus('持久会话已接入 · 回到空命令行按回车后启用提示');resize();if(element.current?.classList.contains('active'))term.focus();
          }
          else if(message.type==='output')term.write(message.data,()=>{if(currentAttempt===attempt)send({type:'ack'})});
          else if(message.type==='warning'){term.writeln('\r\n\x1b[33m'+message.message+'\x1b[0m')}
          else if(message.type==='error'){term.writeln('\r\n\x1b[31m'+message.message+'\x1b[0m');phase('error')}
          else if(message.type==='exit')disconnected('closed');
        };
        ws.onerror=()=>{if(!disposed&&currentAttempt===attempt){term.writeln('\r\n连接失败，请检查本地服务或网络。');disconnected('error')}};
        ws.onclose=event=>{if(!disposed&&currentAttempt===attempt){if(event.code===1013)term.writeln('\r\n会话数量已达上限，请先关闭其他终端。');else if(event.code===1008)term.writeln('\r\n连接验证已失效，请重新连接。');else if(event.code!==1000)term.writeln('\r\nSSH 连接意外断开，请检查网络或本地服务。');disconnected(event.code!==1000?'error':'closed')}};
      }catch(error){if(!disposed&&currentAttempt===attempt){term.writeln('\r\n'+(error instanceof Error?error.message:'连接失败'));disconnected('error')}}
    }
    reconnectRef.current=()=>{void start()};
    start();
    return()=>{disposed=true;connected=false;reconnectRef.current=null;container.removeEventListener('paste',clipboardPaste,true);observer.disconnect();themeObserver.disconnect();input.dispose();links.dispose();searchResults.dispose();searchRef.current=null;socketRef.current?.close();socketRef.current=null;term.dispose();terminal.current=null;resizeRef.current=null};
  },[tab.id,tab.generation]);
  useEffect(()=>{if(terminal.current){terminal.current.options.fontSize=font;if(active)resizeRef.current?.()}},[font]);
  useEffect(()=>{if(active){const frame=requestAnimationFrame(()=>{resizeRef.current?.();terminal.current?.focus()});return()=>cancelAnimationFrame(frame)}},[active]);
  const searchOutput=(previous=false,incremental=false)=>{
    if(!query){searchRef.current?.clearDecorations();setSearchResult('0 / 0');return}
    try{if(regex)new RegExp(query)}catch{searchRef.current?.clearDecorations();setSearchResult('正则表达式无效');return}
    try{const options={caseSensitive,regex,incremental,decorations:{matchBackground:'#6b5730',activeMatchBackground:'#a47724',matchOverviewRuler:'#d8a33c',activeMatchColorOverviewRuler:'#f2c65a'}};searchRef.current?.[previous?'findPrevious':'findNext'](query,options)}catch{setSearchResult('查找暂不可用')}
  };
  useEffect(()=>{if(searchOpen&&active){searchInput.current?.focus();searchOutput(false,true)}else searchRef.current?.clearDecorations()},[searchOpen,query,caseSensitive,regex,active]);
  useEffect(()=>{
    if(!searchOpen||!active)return;
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setSearchOpen(false);terminal.current?.focus()}};
    window.addEventListener('keydown',escape,true);return()=>window.removeEventListener('keydown',escape,true);
  },[searchOpen,active]);
  const workspaceAction=(message:object)=>{if(socketRef.current?.readyState===WebSocket.OPEN)socketRef.current.send(JSON.stringify({type:'workspace',...message}))};
  return <><div ref={element} className={'terminal-screen '+(active?'active':'')} aria-label={tab.host.target+' SSH 交互终端'}/>{active&&<>{searchOpen&&<div className="terminal-search" onKeyDown={event=>{if(event.key==="Escape"){event.preventDefault();setSearchOpen(false);terminal.current?.focus()}if(event.key==="Enter"){event.preventDefault();searchOutput(event.shiftKey)}}}><input ref={searchInput} aria-label="查找终端输出" placeholder="查找终端输出" value={query} onChange={event=>setQuery(event.target.value)}/><label><input type="checkbox" checked={caseSensitive} onChange={event=>setCaseSensitive(event.target.checked)}/>Aa</label><label><input type="checkbox" checked={regex} onChange={event=>setRegex(event.target.checked)}/>.*</label><span>{searchResult}</span><button onClick={()=>searchOutput(true)}>上一个</button><button onClick={()=>searchOutput()}>下一个</button><button onClick={()=>{setSearchOpen(false);terminal.current?.focus()}}>关闭</button></div>}<div className="terminal-assist"><span>{suggestion?<><b>→ 补全</b> <code>{suggestion}</code></>:shellStatus}{lastResult&&<small> · {lastResult}</small>}</span>{sudoAvailable&&<button onClick={()=>socketRef.current?.send(JSON.stringify({type:"sudo"}))}>填入 sudo 密码 · Alt+Enter</button>}{workspace&&<button onClick={()=>setTools(!tools)}>命令与设置</button>}</div>{tools&&workspace&&<TerminalCommands host={tab.host.target} workspace={workspace} action={workspaceAction} close={()=>setTools(false)} insert={text=>{
    if(!atPrompt.current||!commandLine.current.valid||commandLine.current.text){setShellStatus('请先回到空命令行，再填入命令');return false}
    pasteRef.current?.(text);terminal.current?.focus();return true;
  }}/> }</>}</>;
});

export function TerminalDock({request,hosts,onDirectory}:{request:TerminalRequest|null;hosts:Host[];onDirectory?:(hostId:string,path:string)=>void}){
  const [tabs,setTabs]=useState<Tab[]>([]),[active,setActive]=useState(''),[collapsed,setCollapsed]=useState(false),[maximized,setMaximized]=useState(false);
  const [frame,setFrame]=useState(()=>loadTerminalFrame(terminalStorage(),terminalViewport())),[font,setFont]=useState(13),[picker,setPicker]=useState(false),[hint,setHint]=useState('');
  const [savedSessions,setSavedSessions]=useState<Record<string,{id:string;created:number}[]>>({}),[sessionBusy,setSessionBusy]=useState(false);
  const [dragging,setDragging]=useState(false);
  const gesture=useRef<{id:number;edge:string;x:number;y:number;frame:TerminalFrame}|null>(null);
  const handles=useRef<Record<string,Handle|null>>({}),dock=useRef<HTMLElement>(null);
  const bindDock=useRef((element:HTMLElement|null)=>{dock.current=element;registerFloatingWindow(element)});
  const current=tabs.find(tab=>tab.id===active);
  const hasLiveSessions=tabs.some(tab=>!tab.session&&(tab.phase==='connecting'||tab.phase==='running'));
  const add=(host:Host,cwd?:string,session?:string)=>{if(session){const existing=tabs.find(t=>t.host.id===host.id&&t.session===session);if(existing){if(['closed','error'].includes(existing.phase))setTabs(old=>old.map(t=>t.id===existing.id?{...t,generation:t.generation+1,phase:'connecting'}:t));setActive(existing.id);setCollapsed(false);setPicker(false);return}}if(tabs.length>=12){setHint('最多同时打开 12 个终端');return}const id=crypto.randomUUID();setTabs(old=>[...old,{id,host,phase:'connecting',generation:0,cwd,session}]);setActive(id);setCollapsed(false);setPicker(false)};
  useEffect(()=>{if(request){const existing=request.cwd===undefined?tabs.find(tab=>tab.host.id===request.host.id):undefined;if(existing){setActive(existing.id);setCollapsed(false)}else add(request.host,request.cwd)}},[request]);
  useEffect(()=>{setTabs(old=>old.filter(tab=>hosts.some(host=>host.id===tab.host.id)))},[hosts.map(host=>host.id).join(',')]);
  useEffect(()=>{if(tabs.length&&!tabs.some(tab=>tab.id===active))setActive(tabs.at(-1)!.id)},[tabs,active]);
  useEffect(()=>{
    const resize=()=>{setFrame(old=>fitTerminalFrame(old,terminalViewport()));gesture.current=null;setDragging(false)};
    window.addEventListener('resize',resize);return()=>window.removeEventListener('resize',resize);
  },[]);
  useEffect(()=>{try{terminalStorage()?.setItem(TERMINAL_FRAME_KEY,JSON.stringify(frame))}catch{}},[frame]);
  useEffect(()=>{if(!hint)return;const timer=setTimeout(()=>setHint(''),12000);return()=>clearTimeout(timer)},[hint]);
  useEffect(()=>{
    if(!hasLiveSessions)return;
    const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[hasLiveSessions]);
  useEffect(()=>{
    if(!picker)return;let cancelled=false;
    Promise.all(hosts.map(async host=>{try{const response=await fetch('/api/hosts/'+host.id+'/terminal-workspace');if(response.ok)return [host.id,(await response.json()).sessions||[]] as const}catch{}return [host.id,[]] as const})).then(items=>{if(!cancelled)setSavedSessions(Object.fromEntries(items))});
    return()=>{cancelled=true};
  },[picker]);
  const persistent=async(host:Host,cwd?:string)=>{
    if(sessionBusy)return;setSessionBusy(true);
    try{const response=await fetch('/api/hosts/'+host.id+'/terminal-sessions',{method:'POST',headers:{'X-IWB':'1','Content-Type':'application/json'},body:JSON.stringify(cwd?{cwd}:{})});const value=await response.json();if(!response.ok)throw new Error(value.detail||'无法创建持久会话');add(host,cwd,value.id)}catch(error){setHint(error instanceof Error?error.message:'无法创建持久会话')}finally{setSessionBusy(false)}
  };
  const duplicate=()=>{
    if(!current)return;
    if(tabs.length>=12){setHint('最多同时打开 12 个终端');return}
    const cwd=handles.current[active]?.cwd();
    if(!validDirectory(cwd)){setHint('当前 Shell 尚未提供目录信息。请回到空命令行按一次回车后重试');return}
    if(current.session)void persistent(current.host,cwd);else add(current.host,cwd);
  };
  const endPersistent=async()=>{
    if(!current?.session||!window.confirm('结束此持久会话？会话中的任务也会停止，此操作无法撤销。'))return;
    try{const response=await fetch('/api/hosts/'+current.host.id+'/terminal-sessions/'+current.session,{method:'DELETE',headers:{'X-IWB':'1'}});const value=await response.json();if(!response.ok)throw new Error(value.detail||'无法结束会话');setTabs(old=>old.filter(t=>t.id!==current.id))}catch(error){setHint(error instanceof Error?error.message:'无法结束会话')}
  };
  const close=(id:string)=>{
    const tab=tabs.find(tab=>tab.id===id);
    if(tab&&!tab.session&&(tab.phase==='connecting'||tab.phase==='running')&&!window.confirm('关闭此 SSH 会话？前台任务可能随连接结束，建议先用 tmux 保留任务。'))return;
    const remaining=tabs.filter(tab=>tab.id!==id);setTabs(remaining);if(id===active)setActive(remaining.at(-1)?.id||'');
  };
  const startGesture=(event:React.PointerEvent,edge='move')=>{
    if(event.button!==0||maximized||collapsed||gesture.current)return;
    if(edge==='move'&&(event.target as HTMLElement).closest('button,input,select,textarea,a'))return;
    event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current={id:event.pointerId,edge,x:event.clientX,y:event.clientY,frame};setDragging(true);
  };
  const moveGesture=(event:React.PointerEvent)=>{
    const start=gesture.current;if(!start||event.pointerId!==start.id)return;
    const dx=event.clientX-start.x,dy=event.clientY-start.y;
    setFrame(start.edge==='move'?moveTerminalFrame(start.frame,dx,dy,terminalViewport()):resizeTerminalFrame(start.frame,start.edge,dx,dy,terminalViewport()));
  };
  const endGesture=()=>{gesture.current=null;setDragging(false)};
  const restore=()=>{setCollapsed(false);requestAnimationFrame(()=>handles.current[active]?.focus())};
  const running=tabs.filter(tab=>tab.phase==='running').length,disconnected=tabs.filter(tab=>['error','closed'].includes(tab.phase)).length;
  if(!tabs.length)return null;
  return <section ref={bindDock.current} data-floating-window="terminal" onPointerDownCapture={activateFloatingWindow} onFocusCapture={activateFloatingWindow} className={'terminal-dock floating '+(collapsed?'collapsed ':'')+(maximized&&!collapsed?'maximized ':'')+(dragging?'dragging':'')} style={terminalFrameStyle(frame,terminalViewport(),collapsed,maximized)} aria-label="SSH 终端面板" onPointerMove={moveGesture} onPointerUp={endGesture} onPointerCancel={endGesture} onLostPointerCapture={endGesture}>
    {collapsed&&<button className="terminal-minimized-launcher" aria-label="恢复 SSH 终端" title={'恢复终端 · '+(current?.host.target||'SSH 会话')} onClick={restore}><span className="terminal-launcher-icon"><Terminal size={21}/><i className={'session-dot '+(disconnected?'error':running?'running':'connecting')}/></span><span className="terminal-launcher-text"><strong>SSH 终端 <b>{tabs.length}</b><ChevronUp size={14}/></strong><small>{running} 个运行中{disconnected>0?` · ${disconnected} 个已断开`:' · 点击恢复'}</small></span></button>}
    {!collapsed&&!maximized&&['n','s','e','w','ne','nw','se','sw'].map(edge=><div key={edge} className={'terminal-resize-handle edge-'+edge} onPointerDown={event=>startGesture(event,edge)} role={edge==='se'?'separator':undefined} aria-label={edge==='se'?'调整终端大小':undefined} tabIndex={edge==='se'?0:undefined} onKeyDown={event=>{
      const offsets:Record<string,[number,number]>={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};const offset=offsets[event.key];if(!offset)return;
      event.preventDefault();setFrame(old=>resizeTerminalFrame(old,'se',...offset,terminalViewport()));
    }}/ >)}
    <div className="terminal-topbar" style={{display:collapsed?'none':undefined}} onPointerDown={event=>startGesture(event)} onDoubleClick={event=>{if(!(event.target as HTMLElement).closest('button'))setMaximized(!maximized)}}><div className="terminal-brand"><span><Terminal size={16}/></span><strong>终端</strong><small>拖动移动 · 边缘缩放</small><b>{tabs.length}</b></div>
      <div className="terminal-window-actions"><button aria-label="最小化终端" title="收到右下角，保持所有连接" onClick={()=>{setCollapsed(true);setPicker(false)}}><ChevronDown size={16}/></button><button aria-label={maximized?'还原终端':'最大化终端'} onClick={()=>{setMaximized(!maximized);setCollapsed(false)}}>{maximized?<Minimize2 size={15}/>:<Maximize2 size={15}/>}</button><button aria-label="关闭所有终端" title="关闭所有终端连接" onClick={()=>{if(!hasLiveSessions||window.confirm('关闭所有 SSH 会话？普通会话的前台任务可能结束；持久会话只断开显示连接。'))setTabs([])}}><X size={17}/></button></div>
    </div>
    <div className="terminal-body" style={{display:collapsed?'none':undefined}}>
      <div className="terminal-tabbar" role="tablist" aria-label="SSH 会话"><div className="terminal-tabs">{tabs.map((tab,index)=><div key={tab.id} className={'terminal-tab '+(tab.id===active?'selected':'')}><button role="tab" aria-selected={tab.id===active} onClick={()=>setActive(tab.id)}><i className={'session-dot '+tab.phase}/><span>{tab.host.target}</span><small>{tab.session?'持久 '+tab.session.slice(0,4):String(index+1).padStart(2,'0')}</small></button><button className="terminal-tab-close" aria-label={'关闭 '+tab.host.target+' 终端'} onClick={()=>close(tab.id)}><X size={12}/></button></div>)}</div><div className="terminal-add"><button aria-label="新建 SSH 终端" title="新建会话" onClick={()=>setPicker(!picker)}><Plus size={17}/></button>{picker&&<div className="terminal-picker"><strong>连接到机器</strong>{hosts.map(host=><div key={host.id} className="terminal-picker-host"><button onClick={()=>add(host)}><Terminal size={14}/><span>{host.target}<small>{host.user||'使用 SSH 配置账号'}</small></span><Plus size={14}/></button><button disabled={sessionBusy} onClick={()=>persistent(host)}>新建持久会话</button>{(savedSessions[host.id]||[]).map(session=><div key={session.id} className="terminal-saved-session"><button onClick={()=>add(host,undefined,session.id)}>恢复 {session.id.slice(0,6)} · {new Date(session.created*1000).toLocaleString()}</button><button title="结束远端任务并移除记录" onClick={async()=>{if(!window.confirm('结束此持久会话及其中的任务？'))return;try{const response=await fetch('/api/hosts/'+host.id+'/terminal-sessions/'+session.id,{method:'DELETE',headers:{'X-IWB':'1'}});const value=await response.json();if(!response.ok)throw new Error(value.detail);setSavedSessions(old=>({...old,[host.id]:(old[host.id]||[]).filter(s=>s.id!==session.id)}))}catch(error){setHint(String(error))}}}>结束</button></div>)}</div>)}</div>}</div></div>
      <div className="terminal-toolbar"><div><span className="terminal-path">{current?.host.user||'SSH'}<b>@</b>{current?.host.target}</span><span className={'terminal-phase '+current?.phase}><i className={'session-dot '+current?.phase}/>{current&&labels[current.phase]}</span></div><div>{current?.session&&<button onClick={endPersistent} title="结束此持久会话及其中的任务">结束会话</button>}<button aria-label="减小终端字号" onClick={()=>setFont(f=>Math.max(10,f-1))}>A−</button><span className="terminal-font-size">{font}</span><button aria-label="增大终端字号" onClick={()=>setFont(f=>Math.min(22,f+1))}>A+</button><span className="terminal-divider"/><button className="terminal-duplicate" aria-label="复制当前终端" title="在同一目录新建独立会话，沿用命令历史" disabled={!current||current.phase==='connecting'||sessionBusy} onClick={duplicate}><CopyPlus size={14}/>复制终端</button><button aria-label="复制终端所选内容" title="复制所选内容 · Ctrl/⌘+C" onClick={()=>{handles.current[active]?.copy();setHint('选中文字后 Ctrl/⌘+C 复制；Ctrl/⌘+V 粘贴')}}><Copy size={14}/></button><button title="查找输出 · Ctrl/⌘+F" aria-label="查找终端输出" onClick={()=>handles.current[active]?.search()}>查找</button><button aria-label="清空终端显示" title="仅清空显示，不中断命令" onClick={()=>handles.current[active]?.clear()}><Trash2 size={14}/></button><button aria-label="回到底部" title="回到底部 · 查看最新输出" onClick={()=>{handles.current[active]?.scrollToBottom()}}><ChevronsDown size={16}/></button><button aria-label="重新连接当前终端" title={current?.session?"重新接入持久会话":"结束当前会话并重新连接"} onClick={()=>{if(current&&(current.session||['closed','error'].includes(current.phase)||window.confirm('重新连接将结束当前 SSH 会话，是否继续？')))handles.current[active]?.reconnect()}}><RefreshCw size={14}/></button></div></div>
      <div className="terminal-viewport">{tabs.map(tab=><TerminalView key={tab.id} ref={handle=>{handles.current[tab.id]=handle}} tab={tab} active={tab.id===active} font={font} onDirectory={onDirectory} onPhase={phase=>setTabs(old=>old.map(item=>item.id===tab.id?{...item,phase}:item))}/>)}</div>
      <div className="terminal-statusbar"><span><ShieldCheck size={12}/>{current?.session?'tmux 持久会话 · 关闭标签仅断开显示':'本机 SSH · 独立交互会话'}</span><span>{hint||'Ctrl/⌘+C 复制选中 · Ctrl/⌘+V 粘贴 · Ctrl/⌘+点击 pwd 路径打开目录'}</span><span>UTF-8 <i/>xterm-256color</span></div>
    </div>
  </section>;
}
