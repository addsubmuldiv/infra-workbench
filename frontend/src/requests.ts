// All callers share the in-flight read, so a slow poll cannot queue more reads
// or let an older response overwrite a later response.
export function singleFlight<T>(read:()=>Promise<T>):()=>Promise<T>{
  let pending:Promise<T>|null=null;
  return ()=>{
    if(!pending)pending=Promise.resolve().then(read).finally(()=>{pending=null});
    return pending;
  };
}
