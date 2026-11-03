import {ImageAddon} from '@xterm/addon-image';
import type {Terminal} from '@xterm/xterm';
import {createImageDecodeGuard} from './terminalImages';
// Version-pinned compatibility adapter: 0.9.0 registers streaming handlers
// internally, so public registerOscHandler cannot protect its async decoder.
export class SafeImageAddon extends ImageAddon{
 private decodeGuard?:ReturnType<typeof createImageDecodeGuard>;
 activate(term:Terminal){super.activate(term);
  type Storage={addImage:(image:{close?:()=>void})=>void};
  type Handler={end?:(success:boolean)=>boolean|Promise<boolean>;unhook?:(success:boolean)=>boolean|Promise<boolean>;_storage:Storage};
  const internals=this as unknown as {_handlers:Map<string,Handler>;_storage:Storage};
  if(!(internals._handlers instanceof Map)||!internals._storage?.addImage){this.dispose();throw Error('Unsupported image addon internals')}
  const store=internals._storage;
  this.decodeGuard=createImageDecodeGuard(image=>store.addImage(image));
  for(const handler of internals._handlers.values()){
   const key=typeof handler.end==='function'?'end':'unhook',original=handler[key];
   if(typeof original!=='function'){this.dispose();throw Error('Unsupported image handler')}
   handler[key]=(success:boolean)=>this.decodeGuard!.run(accept=>{
    // The asynchronous closure captures this isolated context. A later decode
    // cannot replace the storage capability captured by an earlier callback.
    const context=Object.create(handler);context._storage=Object.create(store);context._storage.addImage=accept;
    return original.call(context,success);
   });
  }
 }
 dispose(){this.decodeGuard?.dispose();super.dispose()}
}
