export const RELEASES_URL='https://github.com/addsubmuldiv/infra-workbench/releases';
export type UpdateStatus={supported:boolean;current_version:string;phase:'idle'|'checking'|'available'|'downloading'|'downloaded'|'installing'|'error';available_version:string|null;notes:string|null;downloaded_bytes:number;total_bytes:number|null;last_checked:number|null;error:string|null};
export type UpdateBridge=(command:string)=>Promise<UpdateStatus>;
export function nativeUpdateBridge(target:unknown,demo=false):UpdateBridge|null{
  if(demo)return null;
  const internals=(target as {__TAURI_INTERNALS__?:{invoke?:UpdateBridge}}|null)?.__TAURI_INTERNALS__;
  return typeof internals?.invoke==='function'?command=>internals.invoke!(command):null;
}
export function canRestartForUpdate(target:Window,hasUnsaved:()=>boolean){
  const event=new Event('beforeunload',{cancelable:true});
  const accepted=target.dispatchEvent(event);
  return accepted&&!event.defaultPrevented&&!hasUnsaved();
}
export function createDesktopUpdater(bridge:UpdateBridge|null,guard:()=>boolean=()=>true){
  let status:UpdateStatus={supported:!!bridge,current_version:'',phase:'idle',available_version:null,notes:null,downloaded_bytes:0,total_bytes:null,last_checked:null,error:null};
  let pending:Promise<void>|null=null,statusPending:Promise<void>|null=null,started=false,capability:boolean|undefined;
  const listeners=new Set<()=>void>();
  const publish=(next:UpdateStatus)=>{status=next;listeners.forEach(listener=>listener())};
  const fail=(error:unknown)=>{
    const message=error instanceof Error?error.message:String(error);
    if(/unknown.?command|command.*not.?found|not.?found.*command|unsupported|not supported|only supported|仅支持|不支持/i.test(message)){
      capability=false;publish({...status,supported:false,phase:'idle',available_version:null,error:null});
    }else publish({...status,phase:'error',error:message});
  };
  const readStatus=():Promise<void>=>{
    if(!bridge||capability===false)return Promise.resolve();
    if(statusPending)return statusPending;
    statusPending=Promise.resolve().then(()=>bridge('desktop_update_status')).then(value=>{capability=value.supported;publish(value)}).catch(fail).finally(()=>{statusPending=null});
    return statusPending;
  };
  const run=(action:'status'|'check'|'download'|'install'):Promise<void>=>{
    if(!bridge||capability===false)return Promise.resolve();
    if(action==='status')return readStatus();
    if(pending)return pending;
    pending=Promise.resolve().then(async()=>{
      if(capability===undefined)await readStatus();
      if(capability!==true)return;
      if(action==='install'&&!guard()){publish({...status,error:'restart_blocked'});return}
      publish({...status,error:null,phase:action==='check'?'checking':action==='download'?'downloading':'installing'});
      publish(await bridge('desktop_update_'+action));
    }).catch(fail).finally(()=>{pending=null});
    return pending;
  };
  return {getSnapshot:()=>status,subscribe:(listener:()=>void)=>{listeners.add(listener);return()=>{listeners.delete(listener)}},run,start:()=>{if(started||!bridge)return;started=true;void run('check')}};
}
