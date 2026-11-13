import React,{useCallback,useEffect,useId,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {Link2,X} from 'lucide-react';
import {t,useLocale} from './i18n';
import {SSHTunnelPanel,tunnelRequest,type TunnelRule} from './SSHTunnelPanel';
import './sshTunnels.css';
type Host={id:string;target:string;alias?:string;ssh_tunnels?:TunnelRule[]};
const active=(rule:TunnelRule)=>['connected','connecting','reconnecting'].includes(rule.status);
export function TunnelManagerButton({hosts,disabled=false}:{hosts:Host[];disabled?:boolean}){
 const [open,setOpen]=useState(false);
 const count=hosts.reduce((sum,h)=>sum+(h.ssh_tunnels??[]).filter(active).length,0);
 return <><button className="secondary" disabled={disabled} onClick={()=>setOpen(true)}><Link2 size={16}/>{t('隧道管理','Tunnel manager')} ({count})</button>{open&&<TunnelManager hosts={hosts} close={()=>setOpen(false)}/>}</>;
}
export function TunnelManager({hosts,close}:{hosts:Host[];close:()=>void}){
 useLocale();const dialog=useRef<HTMLDialogElement>(null),title=useId();
 const [rules,setRules]=useState<Record<string,TunnelRule[]>>({}),[errors,setErrors]=useState<string[]>([]),[busy,setBusy]=useState(false),[all,setAll]=useState(false),[loaded,setLoaded]=useState(false),[detail,setDetail]=useState<Host|null>(null),[now,setNow]=useState(Date.now());
 const mounted=useRef(true),acting=useRef(false),hostRef=useRef(hosts),generation=useRef(0);hostRef.current=hosts;
 useEffect(()=>{if(detail)return;const previous=document.activeElement;dialog.current?.showModal();return()=>{dialog.current?.close();if(previous instanceof HTMLElement&&previous.isConnected)previous.focus()}},[detail]);
 async function refresh(){
  const version=++generation.current,list=hostRef.current;
  const results=await Promise.allSettled(list.map(h=>tunnelRequest(h.id)));
  if(!mounted.current||acting.current||version!==generation.current)return;
  const next:Record<string,TunnelRule[]>={},failures:string[]=[];
  results.forEach((result,i)=>{if(result.status==='fulfilled')next[list[i].id]=result.value;else failures.push((list[i].alias||list[i].target)+': '+String(result.reason))});
  setRules(next);setErrors(failures);setLoaded(true);setNow(Date.now());
 }
 useEffect(()=>{mounted.current=true;let timer:ReturnType<typeof setTimeout>;async function poll(){await refresh();if(mounted.current)timer=setTimeout(poll,2000)}void poll();return()=>{mounted.current=false;clearTimeout(timer)}},[]);
 const rows=hosts.flatMap(host=>(rules[host.id]??[]).map(rule=>({host,rule})));
 const running=rows.filter(({rule})=>active(rule));
 async function stop(items:typeof rows){
  if(acting.current)return;++generation.current;acting.current=true;setBusy(true);
  const results=await Promise.allSettled(items.map(({host,rule})=>tunnelRequest(host.id,`/${encodeURIComponent(rule.id)}/stop`,'POST')));
  acting.current=false;
  if(!mounted.current)return;
  await refresh();
  const failures=results.flatMap((r,i)=>r.status==='rejected'?[items[i].host.target+' / '+items[i].rule.name+': '+String(r.reason)]:[]);
  if(mounted.current){setErrors(old=>[...old,...failures]);setBusy(false)}
 }
 const updateDetail=useCallback((items:TunnelRule[])=>{if(detail)setRules(old=>({...old,[detail.id]:items}))},[detail?.id]);
 if(detail)return <SSHTunnelPanel host={detail} close={()=>{setDetail(null);void refresh()}} onRules={updateDetail} onStarted={close}/>;
 return createPortal(<dialog ref={dialog} className="ssh-tunnel-panel tunnel-manager" aria-labelledby={title} onCancel={e=>{e.preventDefault();if(!busy)close()}}>
  <header className="tunnel-heading"><div><h2 id={title}><Link2 size={21}/>{t('隧道管理','Tunnel manager')}</h2><p>{t('全部机器 · 运行中 ','All machines · Active ')}{running.length}</p></div><button className="icon-button" disabled={busy} aria-label={t('关闭','Close')} onClick={close}><X size={20}/></button></header>
  <div className="tunnel-body"><div className="tunnel-manager-tools"><label><input type="checkbox" checked={all} onChange={e=>setAll(e.target.checked)}/>{t('显示全部已保存隧道','Show all saved tunnels')}</label><button className="tunnel-disconnect" disabled={busy||!running.length} onClick={()=>void stop(running)}>{t('断开全部运行中隧道','Disconnect all active tunnels')}</button></div>
   {errors.map((error,i)=><p key={i} className="tunnel-error" role="alert">{error}</p>)}
   {!loaded&&<p role="status">{t('正在读取隧道状态…','Loading tunnel status…')}</p>}
   {loaded&&!errors.length&&!(all?rows:running).length&&<p>{all?t('没有已保存的隧道。','No saved tunnels.'):t('当前没有运行中的隧道。','No active tunnels.')}</p>}
   {(all?rows:running).map(({host,rule})=><article className="tunnel-manager-row" key={host.id+':'+rule.id}>
    <div><strong>{rule.name}</strong><p>{host.alias||host.target}{host.alias&&' · '+host.target}</p><code>{rule.direction==='remote'?`${t('远端','Remote')} 127.0.0.1:${rule.remote_port} → ${t('本机','Local')} 127.0.0.1:${rule.local_port}`:`${t('本机','Local')} 127.0.0.1:${rule.local_port} → ${t('远端','Remote')} 127.0.0.1:${rule.remote_port}`}</code>
    <p><i className={'tunnel-dot '+rule.status}/>{rule.status==='connected'?t('已连接','Connected'):rule.status==='connecting'?t('正在连接','Connecting'):rule.status==='reconnecting'?t('正在重连','Reconnecting'):rule.status==='error'?t('连接失败','Connection failed'):t('未连接','Disconnected')}{rule.connected_at&&` · ${Math.max(0,Math.floor(now/1000-rule.connected_at))} ${t('秒','s')}`}</p>{rule.error&&<p className="tunnel-error">{rule.error}</p>}</div>
    <div className="tunnel-manager-row-actions"><button className="secondary" disabled={busy} onClick={()=>setDetail({...host,ssh_tunnels:rules[host.id]})}>{t('管理','Manage')}</button>{active(rule)&&<button className="tunnel-disconnect" disabled={busy} onClick={()=>void stop([{host,rule}])}>{t('断开','Disconnect')}</button>}</div>
   </article>)}
   <p className="tunnel-footnote">{t('关闭此窗口后隧道继续在后台运行；从托盘退出后台时会断开全部隧道并停止重连。','Tunnels continue in the background when this window closes. Quitting the backend from the tray disconnects all tunnels and stops reconnecting.')}</p>
  </div>
 </dialog>,document.body);
}
