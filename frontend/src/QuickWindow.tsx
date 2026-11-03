import {TERMINAL_CONTEXT_EVENT} from './terminalContext';
import {AssistantChat} from './AssistantChat';
import {useLocale} from './i18n';
import {toolText as tt} from './toolI18n';
import React,{useEffect,useState} from 'react';
import {TerminalDock,type TerminalRequest} from './TerminalDock';
import {FileBrowser} from './FileBrowser';
import {TerminalBoundary} from './TerminalBoundary';
import {browserId} from './browserId';
import './quickWindow.css';
type Host={id:string;target:string;user:string|null};
const nativeInvoke=(window as any).__TAURI_INTERNALS__?.invoke;
const nativeAction=(action:string)=>{if(nativeInvoke)void nativeInvoke('quick_window_action',{action}).catch(console.error)};
export function QuickWindow(){
  const locale=useLocale();
 const [assistant,setAssistant]=useState(false),[configured,setConfigured]=useState(false);
 useEffect(()=>{const open=()=>{setAssistant(true);fetch('/api/assistant/status').then(r=>r.json()).then(v=>setConfigured(!!v.configured)).catch(()=>{})};window.addEventListener(TERMINAL_CONTEXT_EVENT,open);return()=>window.removeEventListener(TERMINAL_CONTEXT_EVENT,open)},[]);
 const params=new URLSearchParams(location.search),kind=params.get('tool'),hostId=params.get('host');
 const [hosts,setHosts]=useState<Host[]>([]),[error,setError]=useState(''),[ready,setReady]=useState(false);
 const [terminal,setTerminal]=useState<TerminalRequest|null>(null);
 const [files,setFiles]=useState<{host:Host;path?:string;requestId:string}|null>(null);
 useEffect(()=>{
  const controller=new AbortController();
  if(!['terminal','files'].includes(kind??'')||!hostId){setError(tt("窗口参数无效。"));return}
  fetch('/api/state',{signal:controller.signal}).then(async response=>{if(!response.ok)throw Error(tt("无法读取机器列表。"));return response.json()}).then(state=>{
   const host=state.hosts.find((h:Host)=>h.id===hostId);if(!host)throw Error(tt("这台机器已不在列表中。"));
   setHosts(state.hosts);document.title=host.target+' · '+(kind==='terminal'?tt("终端"):tt("文件"));
   if(kind==='terminal')setTerminal({host,id:browserId(),cwd:params.get('cwd')??undefined});else setFiles({host,path:params.get('cwd')??undefined,requestId:browserId()});setReady(true);
  }).catch(e=>{if(!controller.signal.aborted)setError(e.message)});
  return()=>controller.abort();
 },[]);
 useEffect(()=>{
  if(!nativeInvoke||!ready)return;
  let hadPane=false;
  const check=()=>{const hasPane=!!document.querySelector('.terminal-dock,.file-browser');if(hasPane)hadPane=true;else if(hadPane)nativeAction('close')};
  const observer=new MutationObserver(check);observer.observe(document.getElementById('root')!,{childList:true,subtree:true});check();
  return()=>observer.disconnect();
 },[ready]);
 useEffect(()=>{const host=hosts.find(h=>h.id===hostId);if(host)document.title=host.target+' · '+(kind==='terminal'?tt("终端"):tt("文件"))},[locale,hosts,hostId,kind]);
 const openTool=(tool:'terminal'|'files',host:string,path?:string)=>{
  if(nativeInvoke){void nativeInvoke('open_quick_tool',{tool,host,path:path??null}).catch((e:unknown)=>setError(tt("无法打开独立窗口：")+String(e)));return}
  const query=new URLSearchParams({tool,host});if(path)query.set('cwd',path);
  window.open('/?'+query.toString(),'_blank','popup,width=760,height=480');
 };
 const directory=(id:string,path:string)=>openTool('files',id,path);
 const clickControl=(event:React.MouseEvent)=>{
  if(!nativeInvoke)return;
  const button=(event.target as HTMLElement).closest('button');
  const action=button?.dataset.windowAction;
  if(action){event.preventDefault();event.stopPropagation();nativeAction(action)}
 };
 const drag=(event:React.PointerEvent)=>{
  if(!nativeInvoke||event.button!==0)return;
  const target=event.target as HTMLElement;
  if(target.closest('.terminal-topbar,.file-header')&&!target.closest('button,select,input,a')){
   event.preventDefault();event.stopPropagation();nativeAction('drag');
  }
 };
 return <main className="quick-window" onClickCapture={clickControl} onPointerDownCapture={drag} onDoubleClickCapture={event=>{
  if(nativeInvoke&&(event.target as HTMLElement).closest('.terminal-topbar,.file-header')&&!(event.target as HTMLElement).closest('button,select,input')){event.stopPropagation();nativeAction('maximize')}
 }}>
  {error?<p role="alert">{error}<button onClick={()=>location.reload()}>{tt("重试")}</button></p>:!ready?<p role="status">{tt("正在打开机器窗口…")}</p>:null}
  {ready&&<button className="quick-reopen" onClick={()=>{const host=hosts.find(h=>h.id===hostId)!;if(kind==='terminal')setTerminal({host,id:browserId()});else setFiles({host,requestId:browserId()})}}>{tt("重新打开")}{kind==='terminal'?tt("终端"):tt("文件")}</button>}
  <TerminalBoundary close={()=>setTerminal(null)}>{terminal&&<TerminalDock request={terminal} hosts={hosts} onDirectory={directory}/>}</TerminalBoundary>
  {assistant&&<div style={{position:"fixed",inset:"12px 12px 12px auto",width:"min(500px,95vw)",zIndex:10000,background:"var(--bg)",overflow:"auto"}}><button onClick={()=>setAssistant(false)}>{tt('收起 AI 助手')}</button><AssistantChat configured={configured} selectedHostIds={hostId?[hostId]:[]}/></div>}
  {files&&<FileBrowser host={files.host} hosts={hosts} initialPath={files.path} requestId={files.requestId} close={()=>setFiles(null)} onTerminal={(id,cwd)=>openTool('terminal',id,cwd)}/>}
 </main>;
}
