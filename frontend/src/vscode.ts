type Tunnel={id:string;name:string;status:string;error?:string};
type Request=(path:string,method?:string,body?:unknown)=>Promise<any>;
export type VSCodePhase='preparing'|'connecting'|'opening';
export class VSCodeError extends Error{
  code:string;canSkip:boolean;
  constructor(code:string,message:string,canSkip=false){super(message);this.name='VSCodeError';this.code=code;this.canSkip=canSkip}
}
function check(signal?:AbortSignal){signal?.throwIfAborted()}
function delay(ms:number,signal?:AbortSignal){
  return new Promise<void>((resolve,reject)=>{
    check(signal);
    const abort=()=>{clearTimeout(timer);reject(signal?.reason??new DOMException('Cancelled','AbortError'))};
    const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve()},ms);
    signal?.addEventListener('abort',abort,{once:true});
  });
}

export async function openVSCode({request,skip=false,expectedAuthority,prepared=()=>{},signal,phase=()=>{},timeoutMs=60000,now=Date.now,wait=delay}:{request:Request;skip?:boolean;expectedAuthority?:string;prepared?:(authority:string)=>void;signal?:AbortSignal;phase?:(value:VSCodePhase)=>void;timeoutMs?:number;now?:()=>number;wait?:(ms:number,signal?:AbortSignal)=>Promise<void>}){
  check(signal);
  let expected=expectedAuthority;
  if(skip&&!expected)throw new VSCodeError('VSCODE_TARGET_CHANGED','Prepare the connection again before skipping tunnels');
  if(!skip){
    phase('preparing');
    const result=await request('/vscode/prepare','POST');
    check(signal);expected=result.authority;prepared(result.authority);
    const selected=result.tunnels as Pick<Tunnel,'id'|'name'>[];
    if(selected.length){
      phase('connecting');const deadline=now()+timeoutMs;
      while(true){
        check(signal);
        const rules=await request('/tunnels') as Tunnel[];
        check(signal);
        const needed=selected.map(item=>rules.find(rule=>rule.id===item.id));
        const failed=needed.find(rule=>rule?.status==='error'||rule?.status==='stopped');
        if(needed.some(rule=>!rule)||failed)throw new VSCodeError('TUNNEL_FAILED',failed?`${failed.name}: ${failed.error||failed.status}`:'Tunnel configuration changed',true);
        if(now()>=deadline)throw new VSCodeError('TUNNEL_TIMEOUT','Timed out waiting for SSH tunnels',true);
        if(needed.every(rule=>rule?.status==='connected'))break;
        await wait(Math.min(500,deadline-now()),signal);
      }
    }
  }
  check(signal);phase('opening');
  return request('/vscode/open','POST',{skip_tunnels:skip,expected_authority:expected});
}
