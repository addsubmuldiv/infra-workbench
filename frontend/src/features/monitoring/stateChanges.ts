// Long-poll a tiny cursor, then read authoritative state. Periodic state reads
// remain responsible for freshness expiry and compatibility with old backends.
export async function watchStateChanges({signal,onChange,request=fetch,retryMs=3000,coalesceMs=100}:{signal:AbortSignal;onChange:()=>unknown;request?:typeof fetch;retryMs?:number;coalesceMs?:number}):Promise<void>{
  const pause=(ms:number)=>new Promise<void>(resolve=>{
    if(signal.aborted){resolve();return}
    const finish=()=>{clearTimeout(timer);signal.removeEventListener('abort',finish);resolve()};
    const timer=setTimeout(finish,ms);signal.addEventListener('abort',finish,{once:true});
  });
  let instance='',revision=-1;
  while(!signal.aborted){
    try{
      const response=await request(`/api/state/changes?${new URLSearchParams({instance,revision:String(revision)})}`,{signal,cache:'no-store',headers:{'X-IWB':'1'}});
      if(signal.aborted)return;
      if(response.status===404)return; // Original periodic polling keeps working.
      if(!response.ok)throw Error('State notification unavailable');
      const next=await response.json();
      if(signal.aborted)return;
      if(typeof next.instance!=='string'||!Number.isSafeInteger(next.revision)||next.revision<0)throw Error('Invalid state cursor');
      if(next.instance!==instance||next.revision!==revision){
        // A fleet often finishes several probes together. Read them as a group.
        if(coalesceMs>0)await pause(coalesceMs);
        if(signal.aborted)return;
        // Finish the read before advancing the cursor. Failed reads retry it.
        await onChange();
        if(signal.aborted)return;
        instance=next.instance;revision=next.revision;
      }
    }catch{
      if(signal.aborted)return;
      await pause(retryMs);
    }
  }
}
