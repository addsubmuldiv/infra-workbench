export type AgentProtocol='auto'|'responses'|'chat_completions';
export type AgentConfig={base_url:string;protocol:AgentProtocol;model:string;timeout_seconds:number};
export type AgentTest={ok:boolean;message:string;protocol?:AgentProtocol;model?:string;preview?:string;elapsed_ms?:number;updated:number};
export type AgentView=AgentConfig&{has_api_key:boolean;api_key_saved:boolean;can_remember:boolean;credential_error:string;last_test:AgentTest|null};
export const defaultAgentConfig:AgentConfig={base_url:'https://api.openai.com/v1',protocol:'auto',model:'',timeout_seconds:45};
export const protocolNames:Record<AgentProtocol,string>={auto:'自动兼容',responses:'Responses',chat_completions:'Chat Completions'};

export function agentPayload(form:AgentConfig,key:string,remember:boolean){
  return {...form,base_url:form.base_url.trim(),model:form.model.trim(),api_key:key.trim()||null,remember};
}
export function agentDirty(form:AgentConfig,saved:AgentView|null,key:string,remember:boolean):boolean{
  if(!saved)return true;
  return form.base_url.trim()!==saved.base_url||form.model.trim()!==saved.model||form.protocol!==saved.protocol||
    form.timeout_seconds!==saved.timeout_seconds||!!key.trim()||(saved.has_api_key&&remember!==saved.api_key_saved);
}
export async function agentRequest<T>(path='',method='GET',body?:unknown,request:typeof fetch=fetch):Promise<T>{
  const response=await request('/api/settings/agent'+path,{method,cache:'no-store',
    headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  let value;
  try{value=await response.json()}catch{throw new Error('无法读取 Agent 接口，请确认已启动新版后台。')}
  if(!response.ok)throw new Error(typeof value?.detail==='string'?value.detail:'Agent 设置操作失败，请检查输入和后台版本。');
  return value as T;
}
