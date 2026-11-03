import {t,useLocale} from './i18n';
import React,{useRef,useState} from 'react';
import {LoaderCircle,Trash2,X} from 'lucide-react';

type RemovalHost={id:string;target:string};
export function RemoveHostDialog({host,hosts,close,remove}:{host?:RemovalHost;hosts?:RemovalHost[];close:()=>void;remove:(host:RemovalHost)=>Promise<void>}){
  useLocale();
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  const [remaining,setRemaining]=useState(hosts??(host?[host]:[]));
  const working=useRef(false);
  const confirm=async()=>{
    if(working.current)return;
    working.current=true;setPending(true);setError('');
    try{
      const failed:RemovalHost[]=[],messages:string[]=[];
      for(const item of remaining){
        try{await remove(item)}
        catch(e){failed.push(item);messages.push(item.target+'：'+(e instanceof Error?e.message:t("移除失败，请重试","Removal failed. Try again")))}
      }
      setRemaining(failed);
      if(failed.length)setError(messages.join('；')+t("。可重试剩余 ",". Retry the remaining ")+failed.length+t(" 台机器。"," machines."));
      else close();
    }
    finally{working.current=false;setPending(false)}
  };
  return <div className="modal-shade"><section className="modal remove-host-modal" role="dialog" aria-modal="true" aria-labelledby="remove-host-title">
    <div className="modal-header"><div><div className="eyebrow">MACHINES / REMOVE</div><h2 id="remove-host-title">{t("移除机器","Remove machines")}</h2></div><button className="icon-button" aria-label={t("关闭移除机器确认","Close machine removal confirmation")} disabled={pending} onClick={close}><X size={20}/></button></div>
    <p>{t("确定从本软件移除 ","Remove ")}<strong>{remaining.length===1?remaining[0].target:t(`以下 ${remaining.length} 台机器`,`these ${remaining.length} machines`)}</strong> {t(" 吗？"," from this app?")}</p>
    {remaining.length>1&&<ul className="remove-host-list">{remaining.map(item=><li key={item.id}>{item.target}</li>)}</ul>}
    <p className="subtle remove-host-description">{t("会清除所选机器的监控规则、卡预约和已保存的 SSH / sudo 密码，并关闭它们在软件中的终端会话与文件窗口。远端文件和本机 SSH 配置保持不变。","This clears monitoring rules, device reservations, and saved SSH / sudo passwords for the selected machines, and closes their terminal sessions and file windows in this app. Remote files and local SSH configuration remain unchanged.")}</p>
    {error&&<div className="connection-error" role="alert">{error}</div>}
    <div className="modal-footer"><button className="secondary" aria-label={t("取消移除机器","Cancel machine removal")} disabled={pending} onClick={close}>{t("取消","Cancel")}</button><button className="secondary remove-host-button" aria-label={t("确认移除机器","Confirm machine removal")} disabled={pending} onClick={confirm}>{pending?<LoaderCircle size={15} className="spin"/>:<Trash2 size={15}/ >}{pending?t("正在移除…","Removing…"):t("确认移除","Confirm removal")}</button></div>
  </section></div>;
}
