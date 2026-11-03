import React,{useEffect,useState} from 'react';
import {t} from './i18n';
import {assistantRequest} from './infraAssistant';

export type AssistantEngine='deepagents'|'codex'|'claude'|'opencode';
type EngineStatus={available:boolean;message:string;steering?:boolean};
export function AssistantEnginePicker({value,onChange,disabled}:{value:AssistantEngine;onChange:(value:AssistantEngine)=>void;disabled:boolean}){
  const [statuses,setStatuses]=useState<Partial<Record<AssistantEngine,EngineStatus>>|null>(null);
  const load=()=>{void assistantRequest<Partial<Record<AssistantEngine,EngineStatus>>>('/engines').then(setStatuses).catch(()=>setStatuses({}))};
  useEffect(load,[]);
  const name=value==='claude'?'Claude Code':value==='opencode'?'OpenCode':'Codex';
  const message=statuses===null?t(`正在检测本机 ${name}…`,`Detecting local ${name}…`):statuses[value]?.message||t(`无法检测 ${name}，请确认后台已更新。`,`Cannot detect ${name}. Check the backend version.`);
  return <div className="assistant-engine-picker"><label>{t('执行引擎','Agent engine')} <select value={value} disabled={disabled} onChange={event=>onChange(event.target.value as AssistantEngine)}><option value="deepagents">{t('内置助手 · 模型接口','Built-in · Model API')}</option><option value="codex">Codex · {t('本机 CLI','Local CLI')}</option><option value="claude">Claude Code · {t('本机 CLI','Local CLI')}</option><option value="opencode">OpenCode · {t('本机 CLI','Local CLI')}</option></select></label>{value!=='deepagents'&&<div role="status"><small>{message}</small><button type="button" onClick={load}>{t('重新检测','Refresh')}</button></div>}</div>;
}
