// All callers share the in-flight read, so a slow poll cannot queue more reads
// or let an older response overwrite a later response.
export function singleFlight<T>(read:()=>Promise<T>):()=>Promise<T>{
  let pending:Promise<T>|null=null;
  return ()=>{
    if(!pending)pending=Promise.resolve().then(read).finally(()=>{pending=null});
    return pending;
  };
}

// State responses contain JSON only. Share equal subtrees without serializing
// the whole inventory again, so unchanged polls do not repaint the application.
function reuseJson(previous:unknown,next:unknown):unknown{
  if(Object.is(previous,next))return previous;
  if(!previous||!next||typeof previous!=='object'||typeof next!=='object'||Array.isArray(previous)!==Array.isArray(next))return next;
  const old=previous as Record<string,unknown>,value=next as Record<string,unknown>;
  const keys=Object.keys(value);
  let same=keys.length===Object.keys(old).length;
  const result:Record<string,unknown>=Array.isArray(next)?[] as unknown as Record<string,unknown>:{};
  for(const key of keys){
    const shared=reuseJson(old[key],value[key]);result[key]=shared;
    if(!Object.prototype.hasOwnProperty.call(old,key)||shared!==old[key])same=false;
  }
  return same?previous:result;
}

export function reuseStateSnapshot<T extends {server_time:number}>(previous:T,next:T):T{
  // server_time is only a readiness flag in the UI, not a displayed clock.
  // Keep receiving every poll for freshness transitions and notifications.
  const shared=reuseJson(previous,{...next,server_time:previous.server_time||next.server_time}) as T;
  return shared===previous?previous:{...shared,server_time:next.server_time};
}
