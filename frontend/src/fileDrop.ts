// Drag-and-drop upload helpers. Pure logic so the drop rules stay testable outside React.
import {toolText as tt} from './toolI18n.ts';
import type {FolderHandle} from './folderUpload.ts';

type DragData={types?:ArrayLike<string>};

/** True only for drags that carry files; text, links and in-page drags keep their default handling. */
export function dragHasFiles(data:DragData|null|undefined):boolean{
  return Array.from(data?.types??[]).includes('Files');
}

/** Structural subset of the File and Directory Entries API, as exposed by dropped items. */
export type DropEntry={isFile:boolean;isDirectory:boolean;name:string;
  createReader?:()=>{readEntries(success:(entries:DropEntry[])=>void,error?:(error:unknown)=>void):void};
  file?:(success:(file:File)=>void,error?:(error:unknown)=>void)=>void};
export type DroppedItem={kind:'file';name:string;file:File}|{kind:'directory';name:string;entry:DropEntry};
type DropItem={kind:string;webkitGetAsEntry?:()=>DropEntry|null;getAsFile?:()=>File|null};

/** Call synchronously inside the drop event: items and files become unreadable once it returns. */
export function collectDrop(data:{items?:ArrayLike<DropItem>;files?:ArrayLike<File>}|null|undefined):DroppedItem[]{
  const items=data?.items??[],drop:DroppedItem[]=[];
  for(let index=0;index<items.length;index++){
    const item=items[index];if(item.kind!=='file')continue;
    const entry=item.webkitGetAsEntry?.();
    // A directory has no file behind it; uploading one would create a phantom empty file.
    if(entry?.isDirectory){drop.push({kind:'directory',name:entry.name,entry});continue}
    const file=item.getAsFile?.();
    if(!file)throw new Error(tt("无法读取拖入的项目，请重新拖放或使用上传按钮"));
    drop.push({kind:'file',name:file.name,file});
  }
  const files=data?.files;
  if(drop.length||!files?.length)return drop;
  // Browsers without item entries still expose plain files.
  return Array.from(files,file=>({kind:'file',name:file.name,file}));
}

type FileHandle={kind:'file';name:string;getFile:()=>Promise<File>};

/** Adapts a dropped directory entry to the handle readFolder() walks, so every existing limit and check still applies. */
export function droppedFolder(entry:DropEntry):FolderHandle{
  return {kind:'directory',name:entry.name,async *entries(){
    if(!entry.createReader)throw new Error(tt("当前浏览器无法读取拖入的文件夹"));
    const reader=entry.createReader();
    for(;;){
      // Chromium returns at most 100 entries per call, so keep reading until a batch comes back empty.
      const batch=await new Promise<DropEntry[]>((resolve,reject)=>reader.readEntries(resolve,reject));
      for(const child of batch){
        const handle:FolderHandle|FileHandle=child.isDirectory?droppedFolder(child):{kind:'file',name:child.name,
          getFile:()=>new Promise<File>((resolve,reject)=>{if(!child.file)reject(new Error(tt("文件传输失败")));else child.file(resolve,reject)})};
        yield [child.name,handle];
      }
      if(!batch.length)return;
    }
  }};
}

type DropSurface={addEventListener(type:string,listener:(event:DragEvent)=>void):void;removeEventListener(type:string,listener:(event:DragEvent)=>void):void};
// Layers floating above the file window must not count as the window. The context menu is rendered inside its DOM;
// the editor and dialogs are portaled to <body> today and stay listed so they remain excluded if that changes.
const FLOATING_LAYERS='.file-editor,.file-context,.file-confirm-shade';

/** True when the event lands on the file window itself rather than on a layer floating above it. */
export function overFileWindow(frame:{contains(node:Node|null):boolean}|null,target:unknown):boolean{
  if(!frame||!target||typeof (target as Element).closest!=='function')return false;
  return frame.contains(target as Node)&&!(target as Element).closest(FLOATING_LAYERS);
}

/** While the file window is open, a file dropped elsewhere on the page must not make the browser open it. */
export function watchFileDrop(surface:DropSurface,zone:{leave:()=>void}):()=>void{
  // The file window cancels the events it accepts, so an event that is already cancelled was handled there.
  const dragover=(event:DragEvent)=>{
    if(!dragHasFiles(event.dataTransfer)||event.defaultPrevented)return;
    event.preventDefault();event.dataTransfer!.dropEffect='none';zone.leave();
  };
  const drop=(event:DragEvent)=>{
    if(!dragHasFiles(event.dataTransfer))return;
    if(!event.defaultPrevented)event.preventDefault();
    zone.leave();
  };
  surface.addEventListener('dragover',dragover);surface.addEventListener('drop',drop);
  return ()=>{surface.removeEventListener('dragover',dragover);surface.removeEventListener('drop',drop)};
}
