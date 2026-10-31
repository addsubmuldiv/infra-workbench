import React,{useState} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';
import type {RemoteEntry} from './files';
export type FileAction={op:'create'|'mkdir'|'rename'|'copy'|'move';directory:string;source?:RemoteEntry};
export const joinPath=(directory:string,name:string)=>directory.replace(/\/$/,'')+'/'+name;
export function FileActionDialog({action,close,submit}:{action:FileAction;close:()=>void;submit:(destination:string)=>Promise<void>}){
  const fullPath=action.op==='copy'||action.op==='move';
  const [value,setValue]=useState(action.op==='rename'?action.source!.name:fullPath?joinPath(action.directory,action.source!.name):'');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const title={create:'新建文本文件',mkdir:'新建文件夹',rename:'重命名',copy:'复制到',move:'移动到'}[action.op];
  return createPortal(<div className="file-confirm-shade"><form className="file-confirm" role="dialog" aria-modal="true" aria-label={title} onSubmit={async event=>{event.preventDefault();setBusy(true);setError('');try{
    if(!value.trim()||(!fullPath&&(value.includes('/')||value==='.'||value==='..')))throw new Error('请输入有效的名称，不含斜杠');
    await submit(fullPath?value:joinPath(action.directory,value));close();
  }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}}><div className="file-confirm-heading"><h3>{title}</h3><button className="icon-button" type="button" disabled={busy} aria-label="关闭文件操作" onClick={close}><X size={18}/></button></div>
    {action.source&&<p>源：{action.source.path}</p>}<label>{fullPath?'目标完整路径':'名称'}<input aria-label={fullPath?'目标完整路径':'文件或文件夹名称'} required autoFocus value={value} disabled={busy} onChange={event=>setValue(event.target.value)}/></label><p>目标存在时会提示错误，不会覆盖。</p>{error&&<p className="file-error" role="alert">{error}</p>}<div><button className="secondary" type="button" disabled={busy} onClick={close}>取消</button><button className="primary" disabled={busy}>{busy?'处理中…':'确定'}</button></div>
  </form></div>,document.body);
}
