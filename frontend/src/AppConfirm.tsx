import {t,useLocale} from './i18n';
import React,{useCallback,useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ShieldCheck,X} from 'lucide-react';
import './appConfirm.css';
type Decision={message:string;resolve:(accepted:boolean)=>void};
export function useAppConfirm(){
  const [decision,setDecision]=useState<Decision|null>(null);
  const pending=useRef<Decision|null>(null);
  const finish=useCallback((accepted:boolean)=>{const current=pending.current;pending.current=null;setDecision(null);current?.resolve(accepted)},[]);
  const confirm=useCallback((message:string)=>new Promise<boolean>(resolve=>{pending.current?.resolve(false);const next={message,resolve};pending.current=next;setDecision(next)}),[]);
  useEffect(()=>()=>{pending.current?.resolve(false);pending.current=null},[]);
  return {confirm,confirmation:decision?<AppConfirm message={decision.message} finish={finish}/>:null};
}
function AppConfirm({message,finish}:{message:string;finish:(accepted:boolean)=>void}){
  useLocale();
  const dialog=useRef<HTMLDialogElement>(null),cancel=useRef<HTMLButtonElement>(null);
  const title=useId(),description=useId();
  useEffect(()=>{const previous=document.activeElement;const element=dialog.current;element?.showModal();cancel.current?.focus();return()=>{element?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()}},[]);
  return createPortal(<dialog ref={dialog} className="modal app-confirm" aria-labelledby={title} aria-describedby={description} onCancel={event=>{event.preventDefault();finish(false)}}>
    <div className="modal-header"><div className="app-confirm-heading"><ShieldCheck size={22}/><h2 id={title}>{t("确认操作","Confirm action")}</h2></div><button className="icon-button" aria-label={t("关闭确认提示","Close confirmation")} onClick={()=>finish(false)}><X size={20}/></button></div>
    <p id={description}>{message}</p>
    <div className="modal-footer"><button ref={cancel} className="secondary" onClick={()=>finish(false)}>{t("取消","Cancel")}</button><button className="primary" onClick={()=>finish(true)}>{t("确认继续","Continue")}</button></div>
  </dialog>,document.body);
}
