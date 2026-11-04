import {useState} from 'react';
import {createPortal} from 'react-dom';
import {t} from './i18n';

export function HostAliasDialog({host,close,saved}:{host:{id:string;target:string;alias?:string};close:()=>void;saved:()=>void}){
 const [alias,setAlias]=useState(host.alias??''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const save=async()=>{
  setBusy(true);setError('');
  try{
   const response=await fetch('/api/hosts/'+encodeURIComponent(host.id)+'/alias',{method:'PUT',headers:{'Content-Type':'application/json','X-IWB':'1'},body:JSON.stringify({alias})});
   const data=await response.json();
   if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:t('别名保存失败，请检查输入。','Could not save alias. Check your input.'));
   saved();close();
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}
 };
 return createPortal(<div className="modal-shade"><form className="modal" role="dialog" aria-modal="true" aria-labelledby="host-alias-title" onSubmit={e=>{e.preventDefault();void save()}}><h2 id="host-alias-title">{t('机器别名','Machine alias')}</h2><p>{host.target}</p><label className="form-label">{t('别名','Alias')}<input autoFocus maxLength={80} value={alias} onChange={e=>setAlias(e.target.value)} placeholder={t('例如：训练机 A3','For example: Training A3')}/></label><p className="subtle">{t('可在机器列表和 AI 助手中使用。留空可恢复显示连接地址。','Use this name in the machine list and AI assistant. Leave blank to display the connection target.')}</p>{error&&<p role="alert" className="connection-error">{error}</p>}<div className="modal-footer"><button type="button" disabled={busy} onClick={close}>{t('取消','Cancel')}</button><button className="primary" disabled={busy}>{t('保存','Save')}</button></div></form></div>,document.body);
}
