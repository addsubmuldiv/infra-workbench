export async function downloadOriginalLog(location:{host_id:string;path:string;transfer_id?:string},fetcher:typeof fetch=fetch,endpoint='/api/logs/download',signal?:AbortSignal,onProgress?:(received:number,total:number|null)=>void):Promise<{blob:Blob;filename:string}>{
  const response=await fetcher(endpoint,{method:'POST',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify(location),signal});
  if(!response.ok){
    let message='日志下载失败，请检查连接和文件路径';
    try{const data=await response.json();if(typeof data.detail==='string')message=data.detail}catch{}
    throw new Error(message);
  }
  let filename=location.path.split('/').pop()||'training.log';
  const encoded=response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if(encoded){try{filename=decodeURIComponent(encoded)}catch{}}
  filename=filename.replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g,'_').replace(/[ .]+$/,'').slice(0,180)||'training.log';
  if(!onProgress||!response.body)return {blob:await response.blob(),filename};
  const totalHeader=response.headers.get('Content-Length'),total=totalHeader===null?null:Number(totalHeader);
  const reader=response.body.getReader(),parts:BlobPart[]=[];let received=0;
  const abort=()=>{void reader.cancel().catch(()=>{})};
  signal?.addEventListener('abort',abort,{once:true});
  try{
    onProgress(0,total);
    while(true){
      if(signal?.aborted)throw new DOMException('下载已取消','AbortError');
      const {done,value}=await reader.read();if(done)break;
      parts.push(value as Uint8Array<ArrayBuffer>);received+=value.byteLength;onProgress(received,total);
    }
    if(signal?.aborted)throw new DOMException('下载已取消','AbortError');
    if(total!==null&&received!==total)throw new Error('下载长度不完整，请重新下载');
    return {blob:new Blob(parts),filename};
  }finally{signal?.removeEventListener('abort',abort);reader.releaseLock()}
}
