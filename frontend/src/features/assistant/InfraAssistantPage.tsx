import {isDemo} from '../onboarding/demoBootstrap';
import {DemoAssistant} from '../onboarding/DemoPanels';
import {ui} from './assistantLocale';
import React,{useEffect,useState} from 'react';
import {Sparkles} from 'lucide-react';
import {assistantRequest,type AssistantStatus} from './infraAssistant';
import './infraAssistant.css';
import {AssistantChat} from './AssistantChat';
import {TerminalInsert} from '../terminal/TerminalInsert';

type AssistantProps={compact?:boolean;openSettings:()=>void;selectedHostIds?:string[]};
export function InfraAssistant(props:AssistantProps){return isDemo?<DemoAssistant/>:<LiveInfraAssistant {...props}/>}
function LiveInfraAssistant({openSettings,selectedHostIds=[],compact=false}:{compact?:boolean;openSettings:()=>void;selectedHostIds?:string[]}){
  const [status,setStatus]=useState<AssistantStatus|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let request:AbortController;
    const refresh=()=>{
      request?.abort();const next=new AbortController();request=next;
      assistantRequest<AssistantStatus>('/status','GET',undefined,next.signal).then(value=>{if(!next.signal.aborted){setStatus(value);setError('')}}).catch(e=>{if(!next.signal.aborted)setError(e.message)});
    };
    refresh();window.addEventListener('infra-workbench:agent-settings-changed',refresh);window.addEventListener('focus',refresh);
    return()=>{request.abort();window.removeEventListener('infra-workbench:agent-settings-changed',refresh);window.removeEventListener('focus',refresh)};
  },[]);

  return <section className={'infra-assistant'+(compact?' compact':'')} aria-label={ui("AI 资源助手")}>
    {!compact&&<div className="assistant-intro"><span className="assistant-mark"><Sparkles size={23}/></span><div><h2>{ui("用 AI 操作工作台")}</h2><p>{ui("描述目标，查看执行过程和结果。")}</p></div></div>}
    <div className="assistant-tab-content assistant-chat-tab"><AssistantChat status={status} statusError={error} selectedHostIds={selectedHostIds} openSettings={openSettings}/></div>
    <TerminalInsert/>
  </section>;
}
