export type ImportRow={row:number;target:string;user:string;port:number;status:string;reason:string;host_id:string|null;key_status:string;key_reason:string;password_status?:string;password_reason?:string};
export type ImportJob={id:string;status:string;total:number;processed:number;success:number;failed:number;skipped:number;valid:number;key_total:number;key_done:number;key_failed:number;password_saved?:number;password_failed?:number;rows:ImportRow[]};
export const importActive=(job:ImportJob)=>job.status==='running'||(job.status==='complete'&&job.key_done<job.key_total);
export const importPercent=(done:number,total:number)=>total>0?Math.min(100,Math.max(0,Math.round(done/total*100))):0;

export async function importRequest(path:string,options:RequestInit={}):Promise<any>{
  const headers=new Headers(options.headers);
  if(options.method&&options.method!=='GET')headers.set('X-IWB','1');
  const response=await fetch('/api/imports'+path,{...options,headers,cache:'no-store'});
  let data;try{data=await response.json()}catch{throw new Error('后台返回了无法识别的响应，请检查本地服务')}
  if(!response.ok)throw Object.assign(new Error(response.status===404?'批量导入接口尚未就绪或记录已过期，请重启软件后重新选择表格':typeof data.detail==='string'?data.detail:'操作失败，请重试'),{status:response.status});
  return data;
}

export function validateImportFile(file:Pick<File,'name'|'size'>){
  if(!file.name.toLowerCase().endsWith('.xlsx'))throw new Error('请选择 .xlsx 格式的 Excel 文件；旧版 .xls 请先另存为 .xlsx');
  if(!file.size||file.size>2*1024*1024)throw new Error('文件不能为空，且不能超过 2 MiB');
}
