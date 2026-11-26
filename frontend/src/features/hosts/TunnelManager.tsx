import React,{useCallback,useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Link2,X} from 'lucide-react';
import {t,useLocale} from '../../shared/i18n';
import {UI_TUNNEL_POLL_MS} from '../../internalDefaults.ts';
import {SSHTunnelPanel,tunnelError,tunnelRequest,tunnelStatusText,type TunnelRule} from './SSHTunnelPanel';
import './sshTunnels.css';

type Host={
 id:string;
 target:string;
 alias?:string;
 auth?:string;
 ssh_password?:{password_saved:boolean|null};
 snapshot:{fresh:boolean};
 ssh_tunnels?:TunnelRule[];
};
type TunnelItem={host:Host;rule:TunnelRule};
type HostRules={rules:TunnelRule[];error?:string};
const active=(rule:TunnelRule)=>['connected','connecting','reconnecting'].includes(rule.status);

function connectionRank(rules:TunnelRule[]){
 if(rules.some(rule=>rule.status==='connected'))return 0;
 // Keep older saved rules with previously connected tunnels until they acquire history.
 if(rules.some(rule=>rule.has_connected!==false))return 1;
 return 2;
}

export function TunnelManagerButton({hosts,disabled=false}:{hosts:Host[];disabled?:boolean}){
 const [open,setOpen]=useState(false);
 const count=hosts.reduce((sum,h)=>sum+(h.ssh_tunnels??[]).filter(active).length,0);
 return <><button data-tour="tunnels" className="secondary" disabled={disabled} onClick={()=>setOpen(true)}><Link2 size={16}/>{t('隧道管理','Tunnel manager')} ({count})</button>{open&&<TunnelManager hosts={hosts} close={()=>setOpen(false)}/>}</>;
}

export function TunnelManager({hosts,close}:{hosts:Host[];close:()=>void}){
 useLocale();
 const dialog=useRef<HTMLDialogElement>(null),title=useId();
 const [results,setResults]=useState<Record<string,HostRules>>({});
 const [errors,setErrors]=useState<string[]>([]),[busy,setBusy]=useState(false),[loaded,setLoaded]=useState(false);
 const [detail,setDetail]=useState<{host:Host;ruleId?:string}|null>(null),[now,setNow]=useState(Date.now());
 const mounted=useRef(true),acting=useRef(false),hostRef=useRef(hosts),generation=useRef(0);
 hostRef.current=hosts;

 useEffect(()=>{
  if(detail)return;
  const previous=document.activeElement,element=dialog.current;
  element?.showModal();
  return()=>{element?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()};
 },[detail]);

 const refresh=useCallback(async()=>{
  if(acting.current)return;
  const version=++generation.current,list=hostRef.current;
  const reads=await Promise.allSettled(list.map(host=>tunnelRequest(host.id)));
  if(!mounted.current||acting.current||version!==generation.current)return;
  setResults(old=>Object.fromEntries(reads.map((result,index)=>{
   const host=list[index];
   return [host.id,result.status==='fulfilled'
    ?{rules:result.value}
    :{rules:old[host.id]?.rules??host.ssh_tunnels??[],error:String(result.reason)}];
  })));
  setLoaded(true);
  setNow(Date.now());
 },[]);

 useEffect(()=>{
  mounted.current=true;
  let cancelled=false,timer:ReturnType<typeof setTimeout>;
  async function poll(){await refresh();if(!cancelled)timer=setTimeout(poll,UI_TUNNEL_POLL_MS)}
  void poll();
  return()=>{cancelled=true;mounted.current=false;clearTimeout(timer)};
 },[refresh]);

 const machines=hosts.map(host=>{
  const result=results[host.id];
  const rules=result?.rules??host.ssh_tunnels??[];
  return {host,rules,error:result?.error,ready:!!result&&!result.error,rank:connectionRank(rules)};
 }).filter(({host,rules,error})=>host.snapshot.fresh||rules.length||error)
   .sort((a,b)=>a.rank-b.rank);
 const running=machines.flatMap(({host,rules,ready})=>ready?rules.filter(active).map(rule=>({host,rule})):[]);

 async function operate(items:TunnelItem[],action:'start'|'stop'){
  if(acting.current)return;
  ++generation.current;
  acting.current=true;
  setBusy(true);
  setErrors([]);
  const changes=await Promise.allSettled(items.map(({host,rule})=>tunnelRequest(host.id,`/${encodeURIComponent(rule.id)}/${action}`,'POST')));
  acting.current=false;
  if(!mounted.current)return;
  setResults(old=>{
   const next={...old};
   changes.forEach((change,index)=>{
    if(change.status!=='fulfilled')return;
    const {host,rule}=items[index];
    const result=next[host.id];
     if(result)next[host.id]={...result,rules:result.rules.map(item=>item.id===rule.id?change.value:item)};
   });
   return next;
  });
  setErrors(changes.flatMap((change,index)=>{
   if(change.status==='fulfilled')return [];
   const {host,rule}=items[index];
   return [`${host.alias||host.target} / ${rule.name} — ${String(change.reason)}`];
  }));
  setBusy(false);
  void refresh();
 }

 const detailHostId=detail?.host.id;
 const updateDetail=useCallback((rules:TunnelRule[])=>{
  if(detailHostId)setResults(old=>({...old,[detailHostId]:{rules}}));
 },[detailHostId]);
 function closeDetail(){setDetail(null);void refresh()}
 if(detail)return <SSHTunnelPanel host={detail.host} initialRuleId={detail.ruleId} close={closeDetail} onRules={updateDetail}/>;

 return createPortal(<dialog ref={dialog} className="ssh-tunnel-panel tunnel-manager" aria-labelledby={title} onCancel={e=>{e.preventDefault();if(!busy)close()}}>
  <header className="tunnel-heading">
   <div><h2 id={title}><Link2 size={19}/>{t('隧道管理','Tunnel manager')}</h2><p>{t(`${machines.length} 台机器 · ${running.length} 条运行中`,`${machines.length} machines · ${running.length} active tunnels`)}</p></div>
   <div className="tunnel-manager-tools">
    <button className="tunnel-disconnect" disabled={busy||!running.length} onClick={()=>void operate(running,'stop')}>{t('断开全部运行中隧道','Disconnect all active tunnels')}</button>
    <button className="icon-button" disabled={busy} aria-label={t('关闭','Close')} onClick={close}><X size={19}/></button>
   </div>
  </header>
  <div className="tunnel-body">
   {errors.map((error,i)=><p key={i} className="tunnel-error" role="alert">{error}</p>)}
   {!loaded&&<p role="status">{t('正在读取隧道状态…','Loading tunnel status…')}</p>}
   {loaded&&!machines.length&&<p>{t('没有在线机器或已保存的隧道。','No online machines or saved tunnels.')}</p>}
   {machines.map(({host,rules,error,ready})=><article className="tunnel-manager-machine" key={host.id}>
    <div className="tunnel-manager-machine-heading">
     <h3>{host.alias||host.target}</h3>{host.alias&&<p>{host.target}</p>}
    </div>
    <div className="tunnel-manager-rules">
     {error&&<p className="tunnel-error" role="alert">{t('无法读取隧道状态','Could not read tunnel status')} · {error}</p>}
     {ready&&!rules.length&&<div className="tunnel-manager-setup"><p>{t('尚未配置隧道','No tunnel configured')}</p><button className="secondary" disabled={busy} onClick={()=>setDetail({host})}>{t('配置隧道','Set up tunnel')}</button></div>}
     {rules.map(rule=><div className="tunnel-manager-row" key={rule.id}>
      <div className="tunnel-manager-rule-name">
       <strong>{rule.name}</strong>
       <code>{rule.direction==='remote'?`${t('远端','Remote')} ${rule.remote_port} → ${t('本机','Local')} ${rule.local_port}`:`${t('本机','Local')} ${rule.local_port} → ${t('远端','Remote')} ${rule.remote_port}`}</code>
      </div>
      {ready&&<p className="tunnel-manager-status"><i className={'tunnel-dot '+rule.status}/>{tunnelStatusText(rule.status)}{rule.status==='connected'&&rule.connected_at!==null&&` · ${Math.max(0,Math.floor(now/1000-rule.connected_at))} ${t('秒','s')}`}</p>}
      <div className="tunnel-manager-row-actions">
       <button className="secondary" disabled={busy} onClick={()=>setDetail({host:{...host,ssh_tunnels:rules},ruleId:rule.id})}>{t('管理','Manage')}</button>
       {ready&&(active(rule)
        ?<button className="tunnel-disconnect" disabled={busy} onClick={()=>void operate([{host,rule}],'stop')}>{t('断开','Disconnect')}</button>
        :<button className="primary" disabled={busy} onClick={()=>void operate([{host,rule}],'start')}>{rule.has_connected?t('重连','Reconnect'):t('连接','Connect')}</button>)}
      </div>
      {ready&&rule.error&&<p className="tunnel-error">{tunnelError(rule.error_code,rule.error)}</p>}
     </div>)}
    </div>
   </article>)}
   <p className="tunnel-footnote">{t('关闭此窗口后隧道继续在后台运行；从托盘退出后台时会断开全部隧道并停止重连。','Tunnels continue in the background when this window closes. Quitting the backend from the tray disconnects all tunnels and stops reconnecting.')}</p>
  </div>
 </dialog>,document.body);
}
