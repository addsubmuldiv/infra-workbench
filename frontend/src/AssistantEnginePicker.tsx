import React,{useEffect,useState} from 'react';
import {t} from './i18n';
import {assistantRequest} from './infraAssistant';

export type AssistantEngine='deepagents'|'codex';
export function AssistantEnginePicker({value,onChange,disabled}:{value:AssistantEngine;onChange:(value:AssistantEngine)=>void;disabled:boolean}){
  const [status,setStatus]=useState<{available:boolean;message:string}|null>(null);
  const load=()=>{void assistantRequest<{codex:{available:boolean;message:string}}>('/engines').then(result=>setStatus(result.codex)).catch(()=>setStatus({available:false,message:t('无法检测 Codex，请确认后台已更新。','Cannot detect Codex. Check the backend version.')}))};
  useEffect(load,[]);
  return <div className="assistant-engine-picker"><label>{t('执行引擎','Agent engine')} <select value={value} disabled={disabled} onChange={event=>onChange(event.target.value as AssistantEngine)}><option value="deepagents">{t('内置助手 · 模型接口','Built-in · Model API')}</option><option value="codex">Codex · {t('本机 CLI','Local CLI')}</option></select></label>{value==='codex'&&<div role="status"><small>{status?.message||t('正在检测本机 Codex…','Detecting local Codex…')}</small><button type="button" onClick={load}>{t('重新检测','Refresh')}</button></div>}</div>;
}
