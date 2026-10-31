import React,{forwardRef,useEffect,useImperativeHandle,useRef,useState} from 'react';
import {Terminal as XTerminal} from '@xterm/xterm';
import {FitAddon} from '@xterm/addon-fit';
import {ArrowDownToLine,ChevronDown,ChevronUp,Copy,Maximize2,Minimize2,Plus,RefreshCw,ShieldCheck,Terminal,Trash2,X} from 'lucide-react';
import '@xterm/xterm/css/xterm.css';
import './terminal.css';
import {directoryLinkProvider} from './terminalPaths';

type Host={id:string;target:string;user:string|null};
export type TerminalRequest={id:string;host:Host;cwd?:string};
type Phase='connecting'|'running'|'closed'|'error';
type Tab={id:string;host:Host;phase:Phase;generation:number;cwd?:string};
type Handle={clear:()=>void;copy:()=>void;focus:()=>void;scrollToBottom:()=>void};
const labels:Record<Phase,string>={connecting:'正在连接',running:'会话运行中',closed:'连接已结束',error:'连接失败'};
// Windows clipboard-history injection can omit code on its synthetic Ctrl+V.
const clipboardKey=(event:KeyboardEvent,key:'c'|'v')=>event.code==='Key'+key.toUpperCase()||(!event.code&&(event.key?.toLowerCase()===key||event.keyCode===key.toUpperCase().charCodeAt(0)));

function palette(){
  const css=getComputedStyle(document.documentElement);
  const get=(name:string)=>css.getPropertyValue(name).trim();
  return {background:get('--term-bg'),foreground:get('--term-fg'),cursor:get('--accent'),selectionBackground:get('--term-selection'),
    black:'#334155',red:'#d26566',green:'#2e9d78',yellow:'#b68d46',blue:'#5d8fd4',magenta:'#a57ad2',cyan:'#439ca9',white:'#bac6d4',
    brightBlack:'#8090a4',brightRed:'#ef8c8c',brightGreen:'#7bcea7',brightYellow:'#e6c488',brightBlue:'#8bb5ef',brightMagenta:'#c5a3ea',brightCyan:'#89d3d6',brightWhite:'#f0f4fa'};
}

const TerminalView=forwardRef<Handle,{tab:Tab;active:boolean;font:number;onPhase:(phase:Phase)=>void;onDirectory?:(hostId:string,path:string)=>void}>(function TerminalView({tab,active,font,onPhase,onDirectory},ref){
  const element=useRef<HTMLDivElement>(null),terminal=useRef<XTerminal|null>(null),resizeRef=useRef<(()=>void)|null>(null);
  const socketRef=useRef<WebSocket|null>(null);
  const directoryRef=useRef(onDirectory);directoryRef.current=onDirectory;
  useImperativeHandle(ref,()=>({clear:()=>terminal.current?.clear(),focus:()=>terminal.current?.focus(),scrollToBottom:()=>terminal.current?.scrollToBottom(),copy:()=>{
    const text=terminal.current?.getSelection();if(text)navigator.clipboard.writeText(text).catch(()=>{});
  }}),[]);
  useEffect(()=>{
    let disposed=false,connected=false,failed=false;
    let remoteSize:{cols:number;rows:number}|null=null;
    const phase=(next:Phase)=>{if(next==='error')failed=true;onPhase(next==='closed'&&failed?'error':next)};
    const term=new XTerminal({cursorBlink:true,cursorStyle:'bar',fontFamily:'"Cascadia Code","Cascadia Mono",Consolas,"Microsoft YaHei",monospace',fontSize:font,
      lineHeight:1.28,letterSpacing:.2,scrollback:5000,theme:palette(),allowProposedApi:false,convertEol:false});
    const fit=new FitAddon();term.loadAddon(fit);term.open(element.current!);terminal.current=term;
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
    const clipboardPaste=(event:ClipboardEvent)=>{
      if(!event.clipboardData)return;
      event.preventDefault();event.stopPropagation();paste(event.clipboardData.getData('text/plain'));
    };
    const container=element.current!;
    container.addEventListener('paste',clipboardPaste,true);
    term.attachCustomKeyEventHandler(event=>{
      if(event.type==='keydown'&&event.ctrlKey&&!event.altKey&&clipboardKey(event,'c')){
        const selected=term.getSelection();
        if(selected||event.shiftKey){event.preventDefault();if(selected)navigator.clipboard.writeText(selected).catch(()=>{});return false}
      }
      if(event.type==='keydown'&&event.ctrlKey&&!event.altKey&&clipboardKey(event,'v')){
        if(!event.shiftKey)return false; // Let the browser paste event feed xterm; do not send the shell's Ctrl+V byte.
        event.preventDefault();navigator.clipboard.readText().then(text=>{if(!disposed)paste(text)}).catch(()=>{});return false;
      }
      return true;
    });
    const start=async()=>{
      phase('connecting');resize();
      try{
        const response=await fetch('/api/hosts/'+tab.host.id+'/terminal-ticket',{method:'POST',headers:{'X-IWB':'1'}});
        const data=await response.json();if(!response.ok)throw new Error(data.detail||'无法创建终端会话');
        if(disposed)return;
        const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/terminal/'+tab.host.id,['iwb-terminal',data.ticket]);
        socketRef.current=ws;
        ws.onopen=()=>{resize();remoteSize={cols:term.cols,rows:term.rows};send({type:'resize',...remoteSize,...(tab.cwd?{cwd:tab.cwd}:{})})};
        ws.onmessage=event=>{
          if(disposed)return;
          const message=JSON.parse(event.data);
          if(message.type==='ready'){
            // Set native Windows compatibility before parsing login output.
            // AsyncSSH sessions use the default xterm behavior instead.
            if(message.windowsPty?.backend==='conpty')term.options.windowsPty=message.windowsPty;
            connected=true;phase('running');resize();if(element.current?.classList.contains('active'))term.focus();
          }
          else if(message.type==='output')term.write(message.data,()=>send({type:'ack'}));
          else if(message.type==='warning'){term.writeln('\r\n\x1b[33m'+message.message+'\x1b[0m')}
          else if(message.type==='error'){term.writeln('\r\n\x1b[31m'+message.message+'\x1b[0m');phase('error')}
          else if(message.type==='exit'){connected=false;phase('closed');term.writeln('\r\n\x1b[90m── SSH 会话已结束 · 可点击右上角重新连接 ──\x1b[0m')}
        };
        ws.onerror=()=>{if(!disposed){phase('error');term.writeln('\r\n连接失败，请确认本地服务已更新并重试。')}};
        ws.onclose=event=>{connected=false;if(!disposed){phase(event.code!==1000?'error':'closed');if(event.code===1013)term.writeln('\r\n会话数量已达上限，请先关闭其他终端。');else if(event.code===1008)term.writeln('\r\n连接验证已失效，请重新连接。');else if(event.code!==1000)term.writeln('\r\nSSH 连接意外断开，请检查网络或本地服务后重新连接。')}};
      }catch(error){if(!disposed){phase('error');term.writeln('\r\n'+(error instanceof Error?error.message:'连接失败'))}}
    };
    start();
    return()=>{disposed=true;connected=false;container.removeEventListener('paste',clipboardPaste,true);observer.disconnect();themeObserver.disconnect();input.dispose();links.dispose();socketRef.current?.close();socketRef.current=null;term.dispose();terminal.current=null;resizeRef.current=null};
  },[tab.id,tab.generation]);
  useEffect(()=>{if(terminal.current){terminal.current.options.fontSize=font;if(active)resizeRef.current?.()}},[font]);
  useEffect(()=>{if(active){const frame=requestAnimationFrame(()=>{resizeRef.current?.();terminal.current?.focus()});return()=>cancelAnimationFrame(frame)}},[active]);
  return <div ref={element} className={'terminal-screen '+(active?'active':'')} aria-label={tab.host.target+' SSH 交互终端'}/>;
});

export function TerminalDock({request,hosts,onDirectory}:{request:TerminalRequest|null;hosts:Host[];onDirectory?:(hostId:string,path:string)=>void}){
  const [tabs,setTabs]=useState<Tab[]>([]),[active,setActive]=useState(''),[collapsed,setCollapsed]=useState(false),[maximized,setMaximized]=useState(false);
  const [height,setHeight]=useState(370),[font,setFont]=useState(13),[picker,setPicker]=useState(false),[hint,setHint]=useState('');
  const handles=useRef<Record<string,Handle|null>>({}),dock=useRef<HTMLElement>(null);
  const current=tabs.find(tab=>tab.id===active);
  const hasLiveSessions=tabs.some(tab=>tab.phase==='connecting'||tab.phase==='running');
  const add=(host:Host,cwd?:string)=>{if(tabs.length>=12){setHint('最多同时打开 12 个终端');return}const id=crypto.randomUUID();setTabs(old=>[...old,{id,host,phase:'connecting',generation:0,cwd}]);setActive(id);setCollapsed(false);setPicker(false)};
  useEffect(()=>{if(request){const existing=request.cwd===undefined?tabs.find(tab=>tab.host.id===request.host.id):undefined;if(existing){setActive(existing.id);setCollapsed(false)}else add(request.host,request.cwd)}},[request]);
  useEffect(()=>{setTabs(old=>old.filter(tab=>hosts.some(host=>host.id===tab.host.id)))},[hosts.map(host=>host.id).join(',')]);
  useEffect(()=>{if(tabs.length&&!tabs.some(tab=>tab.id===active))setActive(tabs.at(-1)!.id)},[tabs,active]);
  useEffect(()=>{document.documentElement.style.setProperty('--terminal-space',tabs.length?(collapsed?'64px':(maximized?'calc(100vh - 130px)':height+24+'px')):'0px');return()=>{document.documentElement.style.removeProperty('--terminal-space')}},[tabs.length,collapsed,maximized,height]);
  useEffect(()=>{if(!hint)return;const timer=setTimeout(()=>setHint(''),3500);return()=>clearTimeout(timer)},[hint]);
  useEffect(()=>{
    if(!hasLiveSessions)return;
    const warn=(event:BeforeUnloadEvent)=>{event.preventDefault();event.returnValue=''};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[hasLiveSessions]);
  const close=(id:string)=>{
    const tab=tabs.find(tab=>tab.id===id);
    if(tab&&(tab.phase==='connecting'||tab.phase==='running')&&!window.confirm('关闭此 SSH 会话？前台任务可能随连接结束，建议先用 tmux 保留任务。'))return;
    const remaining=tabs.filter(tab=>tab.id!==id);setTabs(remaining);if(id===active)setActive(remaining.at(-1)?.id||'');
  };
  const resize=(event:React.PointerEvent)=>{
    if(maximized||collapsed)return;
    event.preventDefault();const start=event.clientY,initial=height;event.currentTarget.setPointerCapture(event.pointerId);
    const move=(moveEvent:PointerEvent)=>setHeight(Math.max(240,Math.min(window.innerHeight-110,initial+start-moveEvent.clientY)));
    const end=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end);window.removeEventListener('pointercancel',end)};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',end,{once:true});window.addEventListener('pointercancel',end,{once:true});
  };
  if(!tabs.length)return null;
  return <section ref={dock} className={'terminal-dock '+(collapsed?'collapsed ':'')+(maximized&&!collapsed?'maximized':'')} style={{height:collapsed?48:maximized?'calc(100dvh - 100px)':height}} aria-label="SSH 终端面板">
    <div className="terminal-resize" onPointerDown={resize} role="separator" aria-label="拖动调整终端高度" aria-orientation="horizontal" tabIndex={0} onKeyDown={event=>{if(event.key==='ArrowUp')setHeight(h=>Math.min(innerHeight-110,h+30));if(event.key==='ArrowDown')setHeight(h=>Math.max(240,h-30))}}><i/></div>
    <div className="terminal-topbar"><div className="terminal-brand"><span><Terminal size={16}/></span><strong>终端</strong><small>SSH WORKSPACE</small><b>{tabs.length}</b></div>
      <div className="terminal-window-actions"><button aria-label="折叠终端" title="折叠后保持连接" onClick={()=>setCollapsed(!collapsed)}>{collapsed?<ChevronUp size={16}/>:<ChevronDown size={16}/>}</button><button aria-label={maximized?'还原终端':'最大化终端'} onClick={()=>{setMaximized(!maximized);setCollapsed(false)}}>{maximized?<Minimize2 size={15}/>:<Maximize2 size={15}/>}</button><button aria-label="关闭所有终端" title="关闭所有终端连接" onClick={()=>{if(window.confirm('关闭所有 SSH 会话？前台任务可能随连接结束，后台监控不受影响。'))setTabs([])}}><X size={17}/></button></div>
    </div>
    <div className="terminal-body" style={{display:collapsed?'none':undefined}}>
      <div className="terminal-tabbar" role="tablist" aria-label="SSH 会话"><div className="terminal-tabs">{tabs.map((tab,index)=><div key={tab.id} className={'terminal-tab '+(tab.id===active?'selected':'')}><button role="tab" aria-selected={tab.id===active} onClick={()=>setActive(tab.id)}><i className={'session-dot '+tab.phase}/><span>{tab.host.target}</span><small>{String(index+1).padStart(2,'0')}</small></button><button className="terminal-tab-close" aria-label={'关闭 '+tab.host.target+' 终端'} onClick={()=>close(tab.id)}><X size={12}/></button></div>)}</div><div className="terminal-add"><button aria-label="新建 SSH 终端" title="新建会话" onClick={()=>setPicker(!picker)}><Plus size={17}/></button>{picker&&<div className="terminal-picker"><strong>连接到机器</strong>{hosts.map(host=><button key={host.id} onClick={()=>add(host)}><Terminal size={14}/><span>{host.target}<small>{host.user||'使用 SSH 配置账号'}</small></span><Plus size={14}/></button>)}</div>}</div></div>
      <div className="terminal-toolbar"><div><span className="terminal-path">{current?.host.user||'SSH'}<b>@</b>{current?.host.target}</span><span className={'terminal-phase '+current?.phase}><i className={'session-dot '+current?.phase}/>{current&&labels[current.phase]}</span></div><div><button aria-label="减小终端字号" onClick={()=>setFont(f=>Math.max(10,f-1))}>A−</button><span className="terminal-font-size">{font}</span><button aria-label="增大终端字号" onClick={()=>setFont(f=>Math.min(22,f+1))}>A+</button><span className="terminal-divider"/><button aria-label="复制终端所选内容" title="复制所选内容 · Ctrl+C" onClick={()=>{handles.current[active]?.copy();setHint('选中文字后 Ctrl+C 复制；Ctrl+V 粘贴')}}><Copy size={14}/></button><button aria-label="清空终端显示" title="仅清空显示，不中断命令" onClick={()=>handles.current[active]?.clear()}><Trash2 size={14}/></button><button aria-label="滚动到终端底部" onClick={()=>{handles.current[active]?.scrollToBottom()}}><ArrowDownToLine size={14}/></button><button aria-label="重新连接当前终端" title="结束当前会话并重新连接" onClick={()=>{if(current&&(['closed','error'].includes(current.phase)||window.confirm('重新连接将结束当前 SSH 会话，是否继续？')))setTabs(old=>old.map(tab=>tab.id===active?{...tab,generation:tab.generation+1,phase:'connecting'}:tab))}}><RefreshCw size={14}/></button></div></div>
      <div className="terminal-viewport">{tabs.map(tab=><TerminalView key={tab.id} ref={handle=>{handles.current[tab.id]=handle}} tab={tab} active={tab.id===active} font={font} onDirectory={onDirectory} onPhase={phase=>setTabs(old=>old.map(item=>item.id===tab.id?{...item,phase}:item))}/>)}</div>
      <div className="terminal-statusbar"><span><ShieldCheck size={12}/>本机 SSH · 独立交互会话</span><span>{hint||'Ctrl+C 复制选中 · Ctrl+V 粘贴 · Ctrl+点击 pwd 路径打开目录'}</span><span>UTF-8 <i/>xterm-256color</span></div>
    </div>
  </section>;
}
