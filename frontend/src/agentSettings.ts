import {t} from './i18n.ts';
export type ContextCapacity={tokens:number;source:'provider'|'manual'|'fallback';trigger_tokens:number};
export type AgentProtocol='auto'|'responses'|'chat_completions';
export type AgentConfig={profile_id?:string;base_url:string;protocol:AgentProtocol;model:string;timeout_seconds:number;context_window?:number|null};
export type AgentTest={ok:boolean;message:string;protocol?:AgentProtocol;model?:string;preview?:string;elapsed_ms?:number;updated:number};
export type AgentProfile={id:string;name:string;model:string};
export type AgentView=AgentConfig&{active_id:string;default_id:string;profiles:AgentProfile[];has_api_key:boolean;api_key_saved:boolean;can_remember:boolean;credential_error:string;last_test:AgentTest|null};
export const defaultAgentConfig:AgentConfig={base_url:'https://api.openai.com/v1',protocol:'auto',model:'',timeout_seconds:45};
export const protocolNames:Record<AgentProtocol,string>={get auto(){return t('自动兼容','Automatic')},responses:'Responses',chat_completions:'Chat Completions'};

export function agentPayload(form:AgentConfig,key:string,remember:boolean){
  return {...form,base_url:form.base_url.trim(),model:form.model.trim(),api_key:key.trim()||null,remember};
}
export function agentDirty(form:AgentConfig,saved:AgentView|null,key:string,remember:boolean):boolean{
  if(!saved)return true;
  return form.base_url.trim()!==saved.base_url||form.model.trim()!==saved.model||form.protocol!==saved.protocol||
    form.timeout_seconds!==saved.timeout_seconds||(form.context_window||null)!==(saved.context_window||null)||!!key.trim()||(saved.has_api_key&&remember!==saved.api_key_saved);
}
export async function agentRequest<T>(path='',method='GET',body?:unknown,request:typeof fetch=fetch):Promise<T>{
  const response=await request('/api/settings/agent'+path,{method,cache:'no-store',
    headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  let value;
  try{value=await response.json()}catch{throw new Error(t('无法读取 Agent 接口，请确认已启动新版后台。','Unable to read Agent settings. Check that the updated backend is running.'))}
  if(!response.ok)throw new Error(typeof value?.detail==='string'?value.detail:t('Agent 设置操作失败，请检查输入和后台版本。','Agent settings operation failed. Check your input and backend version.'));
  return value as T;
}
