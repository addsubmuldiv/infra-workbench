export type ChangeEvent={id:number;created:number;host_id:string;alias:string;kind:string;description:string};
export type ChangeHistory={events:ChangeEvent[];event_count:number;truncated:boolean;recording_started_at:number;last_observed_at:number|null;requested_since:number;until:number;error:string;limitations:string[]};
export type AssistantStatus={model:string;configured:boolean;credential_error:string;host_count:number;history:ChangeHistory};
export type SearchRow={type:'process'|'resource'|'session'|'host';host_id:string;alias:string;device_ids:string[];collected_at:number|null;pid?:number;user?:string;name?:string;command?:string;cwd?:string;kind?:string;attached?:number;status?:string;fresh?:boolean;devices?:{id:string;name:string;memory_free:number|null;card_id?:string;chip_id?:string}[]};
export type SearchResult={query:string;plan:{scope:string;keywords:string[];host:string;owner:string;kind:string;model:string;count:number;min_free_gib:number;idle:boolean};items:SearchRow[];total:number;truncated:boolean;coverage:{searched_hosts:number;unavailable:{alias:string;status:string}[];unknown:string[];self_unknown:string[];limitations:string[]};model:string;elapsed_ms:number;generated_at:number};
export type ResourceSummary={groups:{text:string;event_ids:number[]}[];history:ChangeHistory;model:string|null;message:string;generated_at:number;elapsed_ms:number};
export async function assistantRequest<T>(path:string,method='GET',body?:unknown,signal?:AbortSignal,request:typeof fetch=fetch):Promise<T>{
  const response=await request('/api/assistant'+path,{method,cache:'no-store',signal,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  let value;
  try{value=await response.json()}catch{throw new Error('无法读取 AI 助手接口，请确认已启动新版后台。')}
  if(!response.ok)throw new Error(response.status===404?'当前后台尚未加载 AI 助手，请从托盘正常退出后重新打开软件。':typeof value?.detail==='string'?value.detail:'AI 请求失败，请检查后台和模型配置。');
  return value as T;
}
export function rowTitle(row:SearchRow):string{
  if(row.type==='process')return `PID ${row.pid} · ${row.user||'用户未知'}`;
  if(row.type==='resource')return `${row.kind} · ${row.device_ids.length} 个设备`;
  if(row.type==='session')return `tmux · ${row.name||'未命名会话'}`;
  return row.fresh?'机器在线':'机器状态待确认';
}
