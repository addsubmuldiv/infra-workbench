import type {Terminal} from '@xterm/xterm';
import type {WebglAddon} from '@xterm/addon-webgl';

type AddonModule={WebglAddon:new()=>WebglAddon};
export function terminalRenderer(term:Pick<Terminal,'loadAddon'>,onMode:(mode:'dom'|'webgl')=>void,load:()=>Promise<AddonModule>=()=>import('@xterm/addon-webgl')){
  let addon:WebglAddon|null=null,loss:{dispose():void}|null=null;
  let active=false,disposed=false,failed=false,generation=0;
  const release=()=>{
    generation++;loss?.dispose();loss=null;
    const old=addon;addon=null;
    try{old?.dispose()}catch{/* Keep the terminal session alive if GPU teardown fails. */}
    onMode('dom');
  };
  return {
    setActive(next:boolean){
      if(disposed||active===next)return;active=next;
      if(!active){release();return}
      if(failed)return;
      const attempt=++generation;
      void load().then(module=>{
        if(disposed||!active||attempt!==generation)return;
        try{
          addon=new module.WebglAddon();
          loss=addon.onContextLoss(()=>{failed=true;release()});
          term.loadAddon(addon);onMode('webgl');
        }catch{failed=true;release()}
      }).catch(()=>{if(attempt===generation){failed=true;release()}});
    },
    dispose(){disposed=true;active=false;release()},
  };
}
