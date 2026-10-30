export async function downloadOriginalLog(location:{host_id:string;path:string},fetcher:typeof fetch=fetch):Promise<{blob:Blob;filename:string}>{
  const response=await fetcher('/api/logs/download',{method:'POST',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify(location)});
  if(!response.ok){
    let message='日志下载失败，请检查连接和文件路径';
    try{const data=await response.json();if(typeof data.detail==='string')message=data.detail}catch{}
    throw new Error(message);
  }
  let filename=location.path.split('/').pop()||'training.log';
  const encoded=response.headers.get('Content-Disposition')?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if(encoded){try{filename=decodeURIComponent(encoded)}catch{}}
  filename=filename.replace(/[\x00-\x1f\x7f<>:"/\\|?*]/g,'_').replace(/[ .]+$/,'').slice(0,180)||'training.log';
  return {blob:await response.blob(),filename};
}
