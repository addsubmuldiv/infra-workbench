import React,{useEffect,useRef,useState} from 'react';
import {t} from './i18n';
import {localTerminalTargets,prepareTerminalInput,TERMINAL_INPUT_EVENT,TERMINAL_PICK_EVENT,type TerminalTarget} from './terminalInput';
import './terminalInsert.css';

let lastTarget='';
export function TerminalInsert(){
 const root=useRef<HTMLDivElement>(null);
 const [selection,setSelection]=useState(''),[point,setPoint]=useState({x:0,y:0});
 const [targets,setTargets]=useState<TerminalTarget[]|null>(null),[text,setText]=useState(''),[status,setStatus]=useState('');
 const params=new URLSearchParams(location.search),standalone=params.get('tool')==='assistant',channel=params.get('channel');
 const invoke=(window as any).__TAURI_INTERNALS__?.invoke;
 const send=async(target:TerminalTarget,value:string)=>{
  try{
   const input={terminal_id:target.terminal_id,text:prepareTerminalInput(value)};
   if(standalone&&invoke)await invoke('quick_window_action',{action:'send-terminal-input',input});
   else if(standalone){const port=new BroadcastChannel('iwb-terminal-input:'+channel);port.postMessage(input);port.close()}
   else {
    let result='目标终端已关闭或尚未连接';
    window.dispatchEvent(new CustomEvent(TERMINAL_INPUT_EVENT,{detail:{...input,reply:(error:string)=>{result=error}}}));
    if(result)throw Error(result);
   }
   lastTarget=target.terminal_id;setTargets(null);setSelection('');setStatus(t('已请求填入 '+target.label+' · '+target.number+'，请在终端检查后按回车执行','Insert requested; review in the terminal and press Enter'));
  }catch(error){setStatus(String(error))}
 };
 const choose=async(value:string)=>{
  try{
   const prepared=prepareTerminalInput(value);setText(prepared);setStatus('');
   let items:TerminalTarget[];
   if(!standalone)items=localTerminalTargets();
   else if(invoke)items=await invoke('quick_window_action',{action:'list-terminal-targets'});
   else items=await new Promise<TerminalTarget[]>((resolve,reject)=>{const port=new BroadcastChannel('iwb-terminal-input:'+channel);const timer=setTimeout(()=>{port.close();reject(Error('无法读取配对终端'))},2000);port.onmessage=event=>{if(event.data?.type==='targets'){clearTimeout(timer);port.close();resolve(event.data.items)}};port.postMessage({type:'list-targets'})});
   if(standalone&&items.length===1&&items[0].phase==='running'){await send(items[0],prepared);return}
   setTargets([...items].sort((a,b)=>Number(b.terminal_id===lastTarget)-Number(a.terminal_id===lastTarget)));
  }catch(error){setStatus(String(error))}
 };
 useEffect(()=>{
  const select=()=>{
   const selected=window.getSelection(),node=selected?.anchorNode,end=selected?.focusNode;
   const assistant=root.current?.closest('.infra-assistant');
   if(root.current?.contains(node??null))return;
   if(!node||!end||!assistant?.contains(node)||!assistant.contains(end)){setSelection('');return}
   const value=selected.toString();setSelection(value);
   if(value.trim()&&selected.rangeCount){const box=selected.getRangeAt(0).getBoundingClientRect();setPoint({x:Math.max(8,Math.min(box.left,innerWidth-170)),y:Math.max(8,Math.min(box.bottom+6,innerHeight-42))})}
  };
  const pick=(event:Event)=>{const detail=(event as CustomEvent).detail;if(root.current?.closest('.infra-assistant')?.contains(detail.element)){const box=detail.element.getBoundingClientRect();setPoint({x:Math.max(8,Math.min(box.left,innerWidth-340)),y:Math.max(8,Math.min(box.bottom+6,innerHeight-300))});void choose(detail.text)}};
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){setTargets(null);setSelection('')}};
  document.addEventListener('mouseup',select);document.addEventListener('keyup',select);window.addEventListener(TERMINAL_PICK_EVENT,pick);
  document.addEventListener('keydown',escape);
  return()=>{document.removeEventListener('mouseup',select);document.removeEventListener('keyup',select);document.removeEventListener('keydown',escape);window.removeEventListener(TERMINAL_PICK_EVENT,pick)};
 },[]);
 return <div ref={root} className="terminal-insert-ui">
  {selection.trim()&&targets===null&&<button className="terminal-insert-trigger" style={{left:point.x,top:point.y}} onMouseDown={event=>event.preventDefault()} onClick={()=>void choose(selection)}>{t('填入终端…','Insert into terminal…')}</button>}
  {targets!==null&&<div className="terminal-target-menu" role="dialog" aria-label={t('选择目标终端标签页','Choose terminal tab')} style={{left:Math.max(8,Math.min(point.x,innerWidth-340)),top:Math.max(8,Math.min(point.y,innerHeight-300))}}>
   <div><strong>{t('填入终端','Insert into terminal')}</strong><button onClick={()=>setTargets(null)} aria-label={t('关闭终端选择','Close terminal picker')}>×</button></div>
   <p>{t('选择标签页，仅填入，不自动执行','Choose a tab; insert without executing')}</p>
   {!targets.length&&<p>{t('请先打开终端','Open a terminal first')}</p>}
   {targets.map(target=><button key={target.terminal_id} disabled={target.phase!=='running'} onClick={()=>void send(target,text)}><strong>{target.label} · {target.number}{target.terminal_id===lastTarget?t(' · 上次选择',' · Last used'):''}</strong><small>{target.cwd||t('目录未知','Unknown directory')} · {target.phase==='running'?t('已连接','Connected'):t('未连接','Disconnected')}</small></button>)}
  </div>}
  {status&&<div className="terminal-insert-status" role="status">{status}<button onClick={()=>setStatus('')} aria-label={t('关闭提示','Dismiss')}>×</button></div>}
 </div>;
}
