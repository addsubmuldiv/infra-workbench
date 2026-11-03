import React,{useEffect,useState} from 'react';
import {Sparkles,X} from 'lucide-react';
import {InfraAssistant} from './InfraAssistantPage';
import {handoffTerminalContext} from './terminalContext';
import {receiveTerminalContext} from './terminalAssistantBridge';
import {t,useLocale} from './i18n';
import './assistantWindow.css';
import './standaloneAssistant.css';


export function StandaloneAssistant(){
 useLocale();
 const params=new URLSearchParams(location.search),channel=params.get('channel');
 const [host,setHost]=useState(params.get('host')||'');
 const invoke=(window as any).__TAURI_INTERNALS__?.invoke;
 useEffect(()=>{
  document.title=t('AI 助手','AI assistant');
  if(!channel||!/^[a-zA-Z0-9-]{16,80}$/.test(channel))return;
  const receive=(items:import('./terminalContext').TerminalAttachment[])=>{
   if(items.length)setHost(items[items.length-1].host_id);
   items.forEach(handoffTerminalContext);
  };
  if(invoke){
   let alive=true,busy=false;
   const poll=async()=>{if(busy)return;busy=true;try{const items=await invoke('quick_window_action',{action:'take-terminal-context'});if(alive&&Array.isArray(items))receive(items)}catch(error){console.error(error)}finally{busy=false}};
   void poll();const timer=setInterval(()=>void poll(),500);
   return()=>{alive=false;clearInterval(timer)};
  }
  if(typeof BroadcastChannel==='undefined')return;
  const receiver=receiveTerminalContext(new BroadcastChannel('iwb-terminal-assistant:'+channel),receive);
  receiver.ready();const timer=setInterval(()=>receiver.ready(),1000);
  return()=>{clearInterval(timer);receiver.close()};
 },[channel]);
 const action=(action:string)=>{if(invoke)void invoke('quick_window_action',{action}).catch(console.error);else window.close()};
 return <main className="standalone-assistant">
  <header onPointerDown={event=>{if(invoke&&event.button===0&&!(event.target as HTMLElement).closest('button'))action('drag')}}><Sparkles size={17}/><strong>{t('AI 助手','AI assistant')}</strong><span>{t('独立窗口','Separate window')}</span><button aria-label={t('关闭 AI 助手窗口','Close AI assistant window')} title={t('关闭窗口，保留对话','Close window and keep conversation')} onClick={()=>action('close')}><X size={17}/></button></header>
  <InfraAssistant compact selectedHostIds={host?[host]:[]} openSettings={()=>window.open('/#settings','_blank','noopener')}/>
 </main>;
}
