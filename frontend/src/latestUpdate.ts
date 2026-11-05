import {UI_RENDER_COALESCE_MS} from './internalDefaults.ts';
// Throttle, rather than debounce: continuous streams still repaint regularly.
export function latestUpdate<T>(render:(value:T)=>void,{schedule=(fn:()=>void)=>setTimeout(fn,UI_RENDER_COALESCE_MS),cancel=clearTimeout}:{schedule?:(fn:()=>void)=>ReturnType<typeof setTimeout>;cancel?:(id:ReturnType<typeof setTimeout>)=>void}={}){
  let timer:ReturnType<typeof setTimeout>|undefined,latest:T,disposed=false;
  return {
    push(value:T,immediate=false){
      if(disposed)return;
      latest=value;
      if(immediate){if(timer!==undefined)cancel(timer);timer=undefined;render(latest)}
      else if(timer===undefined)timer=schedule(()=>{timer=undefined;if(!disposed)render(latest)});
    },
    dispose(){disposed=true;if(timer!==undefined)cancel(timer);timer=undefined},
  };
}
