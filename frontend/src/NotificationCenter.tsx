import {t,useLocale,dateLocale} from './i18n';
import {useWorkspaceRestore} from './workspaceHooks';
import React,{useEffect,useRef,useState} from 'react';
import {Bell,Check,Radio,Trash2,X} from 'lucide-react';
import {browserStorage} from './preferences';
import {loadReadEvent,saveReadEvent,unreadEvents,type NotificationRecord} from './notifications';
import './notificationCenter.css';

export type NotificationTab='messages'|'rules'|null;
type Rule={id:string;host_id:string;devices:string[];minimum_gib:number;port:number;status?:string};
type Props={events:NotificationRecord[];rules:Rule[];hosts:{id:string;target:string}[];tab:NotificationTab;setTab:(tab:NotificationTab)=>void;notify:boolean;busy:boolean;toggleNotifications:()=>Promise<void>;removeRule:(id:string)=>void;locate:(event:NotificationRecord)=>void};

export function NotificationCenter({events,rules,hosts,tab,setTab,notify,busy,toggleNotifications,removeRule,locate}:Props){
  useLocale();
  const root=useRef<HTMLDivElement>(null),bell=useRef<HTMLButtonElement>(null),panel=useRef<HTMLElement>(null);
  const [read,setRead]=useState(()=>loadReadEvent(browserStorage()));
  useWorkspaceRestore('infra-workbench:notifications:read:v1',()=>loadReadEvent(browserStorage()),setRead);
  const unread=unreadEvents(events,read);
  const close=()=>{setTab(null);bell.current?.focus()};
  useEffect(()=>{
    if(!tab)return;
    panel.current?.focus();
    const outside=(event:PointerEvent)=>{if(!root.current?.contains(event.target as Node))setTab(null)};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();setTab(null);bell.current?.focus()}};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)};
  },[!!tab,setTab]);
  const markRead=()=>{const id=Math.max(read,...events.map(event=>event.id));setRead(id);saveReadEvent(browserStorage(),id)};
  const tabKeys=(event:React.KeyboardEvent<HTMLDivElement>)=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();
    const index=event.key==='Home'?0:event.key==='End'?1:tab==='messages'?1:0;
    setTab(index===0?'messages':'rules');event.currentTarget.querySelectorAll<HTMLButtonElement>('[role=tab]')[index]?.focus();
  };
  const ordered=[...events].sort((a,b)=>b.id-a.id);
  return <div className="notification-center" ref={root}>
    <button ref={bell} className={'icon-button notification-bell '+(tab?'active':'')} title={t("通知中心","Notification center")} aria-label={unread?t(`通知中心，${unread} 条未读`,`Notification center, ${unread} unread`):t("通知中心","Notification center")} aria-expanded={!!tab} aria-controls="notification-panel" onClick={()=>setTab(tab?null:'messages')}><Bell size={18}/>{unread>0&&<span className="notification-count">{unread>99?'99+':unread}</span>}</button>
    {tab&&<section ref={panel} id="notification-panel" className="notification-panel" role="dialog" aria-label={t("通知中心","Notification center")} tabIndex={-1}>
      <div className="notification-heading"><div><h2>{t("通知中心","Notification center")}</h2><p>{t("资源提醒、预约通知与运行记录","Resource alerts, reservations, and activity")}</p></div><button className="icon-button" aria-label={t("关闭通知中心","Close notification center")} onClick={close}><X size={17}/></button></div>
      <div className="notification-tabs" role="tablist" aria-label={t("通知分类","Notification categories")} onKeyDown={tabKeys}><button role="tab" id="notification-messages-tab" tabIndex={tab==='messages'?0:-1} aria-selected={tab==='messages'} aria-controls="notification-messages" onClick={()=>setTab('messages')}>{t("消息记录","Messages")}{unread>0&&<span>{unread}</span>}</button><button role="tab" id="notification-rules-tab" tabIndex={tab==='rules'?0:-1} aria-selected={tab==='rules'} aria-controls="notification-rules" onClick={()=>setTab('rules')}>{t("监控规则","Monitoring rules")}<span>{rules.length}</span></button></div>
      <div className="notification-body">
        {tab==='messages'?<div id="notification-messages" role="tabpanel" aria-labelledby="notification-messages-tab"><div className="notification-list-heading"><span>{t("最近 7 天 · 最多 100 条","Last 7 days · Up to 100 messages")}</span><button className="text-button" disabled={!unread} onClick={markRead}><Check size={13}/>{t("全部已读","Mark all as read")}</button></div>
          {ordered.length===0?<div className="notification-empty"><Bell size={26}/><h3>{t("暂无消息","No messages")}</h3><p>{t("预约提醒、资源变化和运行记录会出现在这里。","Reservation alerts, resource changes, and activity will appear here.")}</p></div>:ordered.map(event=><article className={'notification-item '+(unreadEvents([event],read)?'unread':'')} key={event.id}><span className="notification-dot"/><div><p>{event.message}</p><time dateTime={new Date(event.created*1000).toISOString()}>{new Date(event.created*1000).toLocaleString(dateLocale(),{hour12:false})}</time>{(event.url||hosts.some(host=>host.id===event.host))&&<button className="text-button" onClick={()=>{locate(event);setTab(null)}}>{t("查看机器和设备","View machine and devices")}</button>}</div></article>)}
        </div>:<div id="notification-rules" role="tabpanel" aria-labelledby="notification-rules-tab"><p className="notification-explainer">{t("持续关注设备、显存和端口的变化。在总览勾选设备后，点击“监控所选”添加。","Monitor changes in devices, memory, and ports. Select devices in Overview and click “Monitor selected” to add a rule.")}</p>
          {rules.length===0?<div className="notification-empty"><Radio size={26}/><h3>{t("暂无监控规则","No monitoring rules")}</h3><p>{t("已有规则会在这里显示，可随时移除。","Existing rules appear here and can be removed at any time.")}</p></div>:rules.map(rule=><article className="notification-rule" key={rule.id}><Radio size={16}/><div><h3>{hosts.find(host=>host.id===rule.host_id)?.target||t("机器已移除","Machine removed")}</h3><p>{t("设备 ","Devices ")}{rule.devices.join(', ')} {t(" · 每设备 ≥ "," · Per device ≥ ")}{rule.minimum_gib} GiB<br/>{t("端口 ","Port ")}{rule.port}</p><small>{rule.status==='needs_selection'?t("需重新选设备","Select devices again"):rule.status==='active'?t("监控中","Monitoring"):t("等待有效采集","Waiting for valid data")}</small></div><button className="icon-button" disabled={busy} aria-label={t("删除监控规则 ","Delete monitoring rule ")+rule.id} onClick={()=>removeRule(rule.id)}><Trash2 size={15}/></button></article>)}
        </div>}
      </div>
      <div className="notification-delivery"><span>{t("浏览器通知：","Browser notifications: ")}{notify?t("已开启","Enabled"):t("未开启","Disabled")}</span><button className="secondary compact" onClick={toggleNotifications}>{notify?t("关闭浏览器通知","Turn off browser notifications"):t("开启浏览器通知","Enable browser notifications")}</button><small>{t("托盘开启桌面通知时优先发送桌面通知。浏览器通知需保持网页打开。","Desktop notifications take priority when enabled in the tray. Keep the page open for browser notifications.")}</small></div>
    </section>}
  </div>;
}
