import React,{useEffect,useState} from 'react';
import {t} from '../../shared/i18n';
import {assistantRequest} from './infraAssistant';
import {assistantEngineNames,assistantEngineName,type AssistantEngine} from './agentChat';

export type {AssistantEngine} from './agentChat';
type EngineStatus={available:boolean;message?:string;steering?:boolean;setup?:'antigravity_login'};

export function AssistantEnginePicker({value,onChange,disabled}:{value:AssistantEngine;onChange:(value:AssistantEngine)=>void;disabled:boolean}){
  const [statuses,setStatuses]=useState<Partial<Record<AssistantEngine,EngineStatus>>|null>(null);
  const [loginCommand,setLoginCommand]=useState('');
  const [loginLoading,setLoginLoading]=useState(false);
  const [loginError,setLoginError]=useState(false);
  const load=()=>{void assistantRequest<Partial<Record<AssistantEngine,EngineStatus>>>('/engines').then(setStatuses).catch(()=>setStatuses({}))};
  useEffect(load,[]);
  const name=assistantEngineName(value);
  const status=statuses?.[value];
  const antigravitySetup=value==='antigravity'&&status?.setup==='antigravity_login';
  let message=statuses===null
    ?t(`正在检测本机 ${name}…`,`Detecting local ${name}…`)
    :status?.message||t(`无法检测 ${name}，请确认后台已更新。`,`Cannot detect ${name}. Check the backend version.`);
  if(antigravitySetup){
    message=t('已找到本机 agy。首次使用需为工作台单独登录 Google。','Local agy found. Sign in to Google once for this workbench.');
  }else if(value==='antigravity'&&status?.available===false){
    message=t('未找到可用的 agy。请安装官方 CLI，或设置 IWB_ANTIGRAVITY_PATH。','No usable agy executable found. Install the official CLI or set IWB_ANTIGRAVITY_PATH.');
  }else if(value==='dsh'&&status){
    message=status.available
      ?t('已找到本机 dsh。使用 DeepSeek Harness 中已登录的账号或 API Key。','Local dsh found. Uses your DeepSeek Harness account or API key.')
      :t('未找到可用的 dsh。请安装官方 CLI，或设置 IWB_DSH_PATH。','No usable dsh executable found. Install the official CLI or set IWB_DSH_PATH.');
  }
  async function prepareLogin(){
    setLoginLoading(true);setLoginError(false);
    try{
      const setup=await assistantRequest<{command:string}>('/engines/antigravity/login-command','POST');
      setLoginCommand(setup.command);
    }catch{
      setLoginError(true);
    }finally{
      setLoginLoading(false);
    }
  }
  return <div className="assistant-engine-picker">
    <label>{t('执行引擎','Agent engine')} <select value={value} disabled={disabled} onChange={event=>onChange(event.target.value as AssistantEngine)}>
      <option value="deepagents">{t('内置助手 · 模型接口','Built-in · Model API')}</option>
      {(['codex','claude','opencode','antigravity','dsh'] as const).map(engine=>
        <option key={engine} value={engine}>{assistantEngineNames[engine]} · {t('本机 CLI','Local CLI')}</option>)}
    </select></label>
    {value!=='deepagents'&&<div role="status"><small>{message}</small><button type="button" className="secondary" onClick={load}>{t('重新检测','Refresh')}</button></div>}
    {antigravitySetup&&<>
      <button type="button" className="secondary" disabled={disabled||loginLoading} onClick={()=>void prepareLogin()}>
        {loginLoading?t('正在准备…','Preparing…'):t('显示登录命令','Show sign-in command')}
      </button>
      {loginError&&<small role="alert">{t('无法准备登录命令，请检查 CLI 和数据目录权限。','Could not prepare sign-in. Check the CLI and data directory permissions.')}</small>}
      {loginCommand&&<label>
        {t('在本机终端运行以下命令，按官方 CLI 提示完成登录。','Run this command in a local terminal and follow the official CLI sign-in prompts.')}
        <textarea rows={4} readOnly value={loginCommand} onFocus={event=>event.currentTarget.select()}/>
      </label>}
    </>}
  </div>;
}
