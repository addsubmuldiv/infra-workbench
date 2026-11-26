import type {Terminal,ITerminalAddon} from '@xterm/xterm';
import type {IImageAddonOptions} from '@xterm/addon-image';
export const IMAGES_KEY='infra-workbench:terminal-images:v1';
export const IMAGE_OPTIONS:Readonly<IImageAddonOptions>=Object.freeze({enableSizeReports:false,pixelLimit:2097152,storageLimit:16,sixelSizeLimit:8388608,iipSizeLimit:8388608,sixelSupport:true,iipSupport:true,showPlaceholder:true});
export function readImagesEnabled(storage:Pick<Storage,'getItem'>){try{return storage.getItem(IMAGES_KEY)==='true'}catch{return false}}
// Each decode owns a storage capability which expires before parser continuation.
// Late browser bitmap results must be closed, never inserted at a newer cursor.
export function createImageDecodeGuard(store:(image:{close?:()=>void})=>void,timeout=2000){
 let disposed=false;const pending=new Set<()=>void>();
 return {run(operation:(accept:(image:{close?:()=>void})=>void)=>boolean|Promise<boolean>):boolean|Promise<boolean>{
  if(disposed)return true;
  let active=true,timer:ReturnType<typeof setTimeout>|undefined,finish:()=>void=()=>{active=false};
  const accept=(image:{close?:()=>void})=>{if(active&&!disposed)store(image);else image.close?.()};
  try{const result=operation(accept);if(typeof result==='boolean'){active=false;return result}
   return new Promise<boolean>(resolve=>{
    finish=()=>{active=false;if(timer)clearTimeout(timer);pending.delete(finish);resolve(true)};
    pending.add(finish);timer=setTimeout(finish,timeout);
    Promise.resolve(result).then(finish,finish);
   });
  }catch{active=false;return true}
 },dispose(){disposed=true;for(const finish of [...pending])finish()}};
}
export function createTerminalImages(term:Pick<Terminal,'loadAddon'|'write'>,factory:(options:IImageAddonOptions)=>ITerminalAddon,onFailure:()=>void){
 let addon:ITerminalAddon|undefined,disposed=false,desired=false,generation=0;
 return {setEnabled(enabled:boolean){if(disposed||desired===enabled)return;desired=enabled;const current=++generation;
  // Wait for any asynchronous image parse before disposing its storage.
  term.write('',()=>{if(disposed||current!==generation)return;if(!enabled){addon?.dispose();addon=undefined;return}
   try{addon=factory({...IMAGE_OPTIONS});term.loadAddon(addon)}catch{try{addon?.dispose()}catch{}addon=undefined;desired=false;onFailure()}
  });
 },dispose(){if(disposed)return;disposed=true;generation++;addon?.dispose();addon=undefined}};
}
