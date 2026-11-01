type Snapshot={revision:number;values:Record<string,string>};
type Requester=(values?:Record<string,string|null>,onlyMissing?:boolean)=>Promise<Snapshot>;
export const legacyKeys=['infra-workbench:preferences:v1','infra-workbench:assistant-window:v1','infra-workbench:assistant-open:v1','infra-workbench:sidebar-width:v1','infra-workbench:terminal-frame:v1','infra-workbench:notifications:read:v1','infra-workbench:reservation-wait-minutes','iwb-assistant-chat','iwb.precision.draft.v1','iwb-terminal-command-window'];
async function request(values?:Record<string,string|null>,only_missing=false):Promise<Snapshot>{
 const response=await fetch('/api/workspace-state',{method:values?'PUT':'GET',cache:'no-store',headers:{'Content-Type':'application/json','X-IWB':'1'},body:values?JSON.stringify({values,only_missing}):undefined,keepalive:!!values&&JSON.stringify(values).length<30000,signal:AbortSignal.timeout(8000)});
 if(!response.ok)throw new Error('无法保存或读取工作空间状态');
 return response.json();
}
export function createWorkspaceStorage(send:Requester=request,onError:(failed:boolean)=>void=()=>{}){
 let values:Record<string,string>={},revision=-1,inflight=false,saving=false,timer:ReturnType<typeof setTimeout>|undefined;
 const pending=new Map<string,string|null>(),listeners=new Map<string,Set<()=>void>>();
 const emit=(key:string)=>listeners.get(key)?.forEach(fn=>fn());
 const apply=(snapshot:Snapshot)=>{
  if(snapshot.revision<revision)return;revision=snapshot.revision;
  const previous=values;values={...snapshot.values};
  for(const [key,value] of pending){if(value===null)delete values[key];else values[key]=value}
  for(const key of new Set([...Object.keys(previous),...Object.keys(values)]))if(previous[key]!==values[key])emit(key);
 };
 const flush=async()=>{
  if(inflight||!pending.size)return;inflight=true;saving=true;
  const batch=Object.fromEntries(pending);pending.clear();let failed=false;
  try{apply(await send(batch));onError(false)}catch{
   for(const [key,value] of Object.entries(batch))if(!pending.has(key))pending.set(key,value);
   failed=true;onError(true);
  }finally{inflight=false;saving=false}
  if(pending.size)schedule(failed?2000:250);
 };
 const schedule=(delay=250)=>{if(timer)clearTimeout(timer);timer=setTimeout(()=>{timer=undefined;void flush()},delay)};
 return {
  getItem:(key:string)=>values[key]??null,
  setItem:(key:string,value:string)=>{if(values[key]===value)return;values[key]=value;pending.set(key,value);emit(key);schedule()},
  removeItem:(key:string)=>{if(!(key in values))return;delete values[key];pending.set(key,null);emit(key);schedule()},
  subscribe:(key:string,fn:()=>void)=>{let group=listeners.get(key);if(!group)listeners.set(key,group=new Set());group.add(fn);return()=>{group!.delete(fn)}},
  initialize:async(legacy?:Pick<Storage,'getItem'>)=>{
   let snapshot=await send();const missing:Record<string,string>={};
   if(legacy)for(const key of legacyKeys){try{const value=legacy.getItem(key);if(value!==null&&new TextEncoder().encode(value).length<=65536&&!(key in snapshot.values))missing[key]=value}catch{}}
   if(Object.keys(missing).length)snapshot=await send(missing,true);
   apply(snapshot);onError(false);
  },
  refresh:async()=>{if(inflight)return;if(pending.size){await flush();return}inflight=true;try{apply(await send());onError(false)}catch{onError(true)}finally{inflight=false}},
  flush,
  hasUnsaved:()=>saving||pending.size>0,
  dispose:()=>{if(timer)clearTimeout(timer)},
 };
}
export const workspaceStorage=createWorkspaceStorage(request,failed=>{if(typeof window!=='undefined')window.dispatchEvent(new CustomEvent('workspace-save-status',{detail:failed}))});
export async function initializeWorkspace(){
 // One-time import only. All subsequent reads/writes use the backend.
 let legacy:Storage|undefined;try{legacy=window.localStorage}catch{}
 await workspaceStorage.initialize(legacy);
 // Remove obsolete copies only after the backend acknowledged migration.
 if(legacy)for(const key of legacyKeys){try{legacy.removeItem(key)}catch{}}
 window.setInterval(()=>{void workspaceStorage.refresh()},1500);
 window.addEventListener('focus',()=>{void workspaceStorage.refresh()});
 window.addEventListener('pagehide',()=>{void workspaceStorage.flush()});
 window.addEventListener('beforeunload',event=>{if(workspaceStorage.hasUnsaved()){event.preventDefault();event.returnValue=''}});
}
