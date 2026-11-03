import {toolText as tt} from './toolI18n.ts';
export type TransferProgress={stage:'preparing'|'packing'|'receiving'|'sending'|'verifying'|'done'|'download_remote'|'download_browser';loaded:number;total:number|null};
type UploadStatus={id:string;status:string;total:number;received:number;sent:number;error?:string;path?:string};
const aborted=()=>new DOMException(tt("传输已取消"),'AbortError');
async function jsonRequest(url:string,options:RequestInit={},fetcher:typeof fetch=fetch){
  const response=await fetcher(url,{...options,headers:{'Content-Type':'application/json','X-IWB':'1',...options.headers}});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:tt("文件传输失败"));
  return value;
}
function pause(signal:AbortSignal,ms=400){return new Promise<void>((resolve,reject)=>{
  if(signal.aborted){reject(aborted());return}
  const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(aborted())};
  const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve()},ms);
  signal.addEventListener('abort',abort,{once:true});
})}

export function sendUpload(url:string,file:Blob,signal:AbortSignal,progress:(loaded:number)=>void,xhrFactory=()=>new XMLHttpRequest()):Promise<void>{
  return new Promise((resolve,reject)=>{
    if(signal.aborted){reject(aborted());return}
    const xhr=xhrFactory();
    const abort=()=>xhr.abort();
    const finish=(error?:Error)=>{signal.removeEventListener('abort',abort);if(error)reject(error);else resolve()};
    xhr.open('PUT',url);xhr.setRequestHeader('X-IWB','1');xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.responseType='json';xhr.timeout=600000;
    xhr.upload.onprogress=event=>progress(event.loaded);
    xhr.onload=()=>finish(xhr.status>=200&&xhr.status<300?undefined:new Error(xhr.response?.detail||tt("上传到本地服务失败")));
    xhr.onerror=()=>finish(new Error(tt("上传连接中断")));xhr.ontimeout=()=>finish(new Error(tt("上传超时")));xhr.onabort=()=>finish(aborted());
    signal.addEventListener('abort',abort,{once:true});xhr.send(file);
  });
}

export async function uploadFile(host:string,directory:string,file:File,signal:AbortSignal,progress:(value:TransferProgress)=>void,fetcher:typeof fetch=fetch,sender=sendUpload):Promise<string>{
  return uploadPayload(host,directory,file.name,file,'file',signal,progress,fetcher,sender);
}
export async function uploadPayload(host:string,directory:string,name:string,body:Blob,kind:'file'|'folder',signal:AbortSignal,progress:(value:TransferProgress)=>void,fetcher:typeof fetch=fetch,sender=sendUpload):Promise<string>{
  if(signal.aborted)throw aborted();
  if(body.size>512*1024*1024)throw new Error(tt("上传内容不能超过 512 MiB"));
  const job:UploadStatus=await jsonRequest('/api/files/uploads',{method:'POST',body:JSON.stringify({host_id:host,path:directory,name,size:body.size,...(kind==='folder'?{kind}:{})}),signal},fetcher);
  const url='/api/files/uploads/'+job.id;
  try{
    progress({stage:'receiving',loaded:0,total:body.size});
    await sender(url,body,signal,loaded=>progress({stage:'receiving',loaded,total:body.size}));
    while(true){
      const state:UploadStatus=await jsonRequest(url,{signal},fetcher);
      if(state.status==='done'){progress({stage:'done',loaded:body.size,total:body.size});return state.path!}
      if(['error','cancelled'].includes(state.status))throw new Error(state.error||tt("上传未完成"));
      progress({stage:state.status==='verifying'?'verifying':'sending',loaded:state.sent,total:state.total});
      await pause(signal);
    }
  }catch(error){
    void jsonRequest(url,{method:'DELETE'},fetcher).catch(()=>{});
    throw error;
  }
}

export async function watchDownload(id:string,signal:AbortSignal,progress:(value:TransferProgress)=>void,fetcher:typeof fetch=fetch){
  while(!signal.aborted){
    try{
      const state=await jsonRequest('/api/files/downloads/'+id,{signal},fetcher);
      if(['error','cancelled'].includes(state.status))return;
      progress({stage:'download_remote',loaded:state.received,total:state.total});
      if(state.status==='remote_done')return;
    }catch{if(signal.aborted)return}
    await pause(signal);
  }
}
