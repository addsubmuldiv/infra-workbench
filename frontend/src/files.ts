import {toolText as tt} from './toolI18n.ts';
export type RemoteEntry={name:string;path:string;relative?:string;kind:'file'|'directory'|'other';symlink:boolean;size:number|null;modified:number|null;accessible:boolean};
export type DirectoryPage={path:string;parent:string;entries:RemoteEntry[];total:number;next_offset:number|null;scanned?:number;truncated?:boolean;skipped?:number;engine?:string;indexed?:boolean;locate_available?:boolean};
export type TextDocument={path:string;content:string;revision:string;bytes:number;newline:string};
export type FileCommand={op:'read'|'save'|'copy'|'move'|'mkdir'|'create';path:string;destination?:string;content?:string;revision?:string};
export async function fileOperation<T= {path:string}>(host:string,command:FileCommand,fetcher:typeof fetch=fetch):Promise<T>{
  const response=await fetcher('/api/files/operation',{method:'POST',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify({host_id:host,...command})});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:tt("文件操作失败"));
  return data;
}
export async function listDirectory(host:string,path:string,offset=0,fetcher:typeof fetch=fetch):Promise<DirectoryPage>{
  const response=await fetcher('/api/files/browse',{method:'POST',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify({host_id:host,path,offset})});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:tt("读取目录失败"));
  if(typeof data.path!=='string'||!Array.isArray(data.entries))throw new Error(tt("服务器返回的目录信息无效"));
  return data;
}
export async function searchFiles(host:string,path:string,query:string,recursive:boolean,realtime=false,fetcher:typeof fetch=fetch):Promise<DirectoryPage>{
  const response=await fetcher('/api/files/search',{method:'POST',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify({host_id:host,path,query,recursive,realtime})});
  const data=await response.json();
  if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:tt("文件搜索失败"));
  return data;
}
