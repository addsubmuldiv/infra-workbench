import {isDemo} from './demoBootstrap';
import {DemoAssistant} from './DemoPanels';
import {ui} from './assistantLocale';
import {t} from './i18n';
import React,{useEffect,useState} from 'react';
import {Sparkles} from 'lucide-react';
import {assistantRequest,type AssistantStatus} from './infraAssistant';
import './infraAssistant.css';
import {AssistantChat} from './AssistantChat';

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
    {error&&<div className="assistant-error" role="alert">{error}</div>}
    {status&&!status.configured&&<div className="assistant-note">{t('内置助手需要配置模型接口；本机 Codex 可在下方执行引擎中选择。','Configure a model API for the built-in assistant, or select local Codex below.')}</div>}
    {status?.credential_error&&<div className="assistant-error">{status.credential_error}</div>}
    <div className="assistant-tab-content assistant-chat-tab"><AssistantChat configured={!!status?.configured} selectedHostIds={selectedHostIds} model={status?.model} openSettings={openSettings}/></div>
  </section>;
}
