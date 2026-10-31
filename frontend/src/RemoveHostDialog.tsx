import React,{useRef,useState} from 'react';
import {LoaderCircle,Trash2,X} from 'lucide-react';

export function RemoveHostDialog({host,close,remove}:{host:{id:string;target:string};close:()=>void;remove:()=>Promise<void>}){
  const [pending,setPending]=useState(false),[error,setError]=useState('');
  const working=useRef(false);
  const confirm=async()=>{
    if(working.current)return;
    working.current=true;setPending(true);setError('');
    try{await remove();close()}
    catch(e){setError(e instanceof Error?e.message:'移除失败，请重试')}
    finally{working.current=false;setPending(false)}
  };
  return <div className="modal-shade"><section className="modal remove-host-modal" role="dialog" aria-modal="true" aria-labelledby="remove-host-title">
    <div className="modal-header"><div><div className="eyebrow">MACHINES / REMOVE</div><h2 id="remove-host-title">移除机器</h2></div><button className="icon-button" aria-label="关闭移除机器确认" disabled={pending} onClick={close}><X size={20}/></button></div>
    <p>确定从本软件移除 <strong>{host.target}</strong> 吗？</p>
    <p className="subtle remove-host-description">会清除这台机器的监控规则、卡预约和已保存的 SSH / sudo 密码，并关闭它在软件中的终端会话与文件窗口。远端文件和本机 SSH 配置保持不变。</p>
    {error&&<div className="connection-error" role="alert">{error}</div>}
    <div className="modal-footer"><button className="secondary" aria-label="取消移除机器" disabled={pending} onClick={close}>取消</button><button className="secondary remove-host-button" aria-label="确认移除机器" disabled={pending} onClick={confirm}>{pending?<LoaderCircle size={15} className="spin"/>:<Trash2 size={15}/ >}{pending?'正在移除…':'确认移除'}</button></div>
  </section></div>;
}
