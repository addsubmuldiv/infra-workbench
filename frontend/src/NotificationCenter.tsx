import {useWorkspaceRestore} from './workspaceHooks';
import React,{useEffect,useRef,useState} from 'react';
import {Bell,Check,Radio,Trash2,X} from 'lucide-react';
import {browserStorage} from './preferences';
import {loadReadEvent,saveReadEvent,unreadEvents,type NotificationRecord} from './notifications';
import './notificationCenter.css';

export type NotificationTab='messages'|'rules'|null;
type Rule={id:string;host_id:string;devices:string[];minimum_gib:number;port:number;status?:string};
type Props={events:NotificationRecord[];rules:Rule[];hosts:{id:string;target:string}[];tab:NotificationTab;setTab:(tab:NotificationTab)=>void;notify:boolean;busy:boolean;enableNotifications:()=>Promise<void>;removeRule:(id:string)=>void;locate:(event:NotificationRecord)=>void};

export function NotificationCenter({events,rules,hosts,tab,setTab,notify,busy,enableNotifications,removeRule,locate}:Props){
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
    <button ref={bell} className={'icon-button notification-bell '+(tab?'active':'')} title="通知中心" aria-label={unread?`通知中心，${unread} 条未读`:'通知中心'} aria-expanded={!!tab} aria-controls="notification-panel" onClick={()=>setTab(tab?null:'messages')}><Bell size={18}/>{unread>0&&<span className="notification-count">{unread>99?'99+':unread}</span>}</button>
    {tab&&<section ref={panel} id="notification-panel" className="notification-panel" role="dialog" aria-label="通知中心" tabIndex={-1}>
      <div className="notification-heading"><div><h2>通知中心</h2><p>资源提醒、预约通知与运行记录</p></div><button className="icon-button" aria-label="关闭通知中心" onClick={close}><X size={17}/></button></div>
      <div className="notification-tabs" role="tablist" aria-label="通知分类" onKeyDown={tabKeys}><button role="tab" id="notification-messages-tab" tabIndex={tab==='messages'?0:-1} aria-selected={tab==='messages'} aria-controls="notification-messages" onClick={()=>setTab('messages')}>消息记录{unread>0&&<span>{unread}</span>}</button><button role="tab" id="notification-rules-tab" tabIndex={tab==='rules'?0:-1} aria-selected={tab==='rules'} aria-controls="notification-rules" onClick={()=>setTab('rules')}>监控规则<span>{rules.length}</span></button></div>
      <div className="notification-body">
        {tab==='messages'?<div id="notification-messages" role="tabpanel" aria-labelledby="notification-messages-tab"><div className="notification-list-heading"><span>最近 7 天 · 最多 100 条</span><button className="text-button" disabled={!unread} onClick={markRead}><Check size={13}/>全部已读</button></div>
          {ordered.length===0?<div className="notification-empty"><Bell size={26}/><h3>暂无消息</h3><p>预约提醒、资源变化和运行记录会出现在这里。</p></div>:ordered.map(event=><article className={'notification-item '+(unreadEvents([event],read)?'unread':'')} key={event.id}><span className="notification-dot"/><div><p>{event.message}</p><time dateTime={new Date(event.created*1000).toISOString()}>{new Date(event.created*1000).toLocaleString('zh-CN',{hour12:false})}</time>{(event.url||hosts.some(host=>host.id===event.host))&&<button className="text-button" onClick={()=>{locate(event);setTab(null)}}>查看机器和设备</button>}</div></article>)}
        </div>:<div id="notification-rules" role="tabpanel" aria-labelledby="notification-rules-tab"><p className="notification-explainer">持续关注设备、显存和端口的变化。在总览勾选设备后，点击“监控所选”添加。</p>
          {rules.length===0?<div className="notification-empty"><Radio size={26}/><h3>暂无监控规则</h3><p>已有规则会在这里显示，可随时移除。</p></div>:rules.map(rule=><article className="notification-rule" key={rule.id}><Radio size={16}/><div><h3>{hosts.find(host=>host.id===rule.host_id)?.target||'机器已移除'}</h3><p>设备 {rule.devices.join(', ')} · 每设备 ≥ {rule.minimum_gib} GiB<br/>端口 {rule.port}</p><small>{rule.status==='needs_selection'?'需重新选设备':rule.status==='active'?'监控中':'等待有效采集'}</small></div><button className="icon-button" disabled={busy} aria-label={'删除监控规则 '+rule.id} onClick={()=>removeRule(rule.id)}><Trash2 size={15}/></button></article>)}
        </div>}
      </div>
      <div className="notification-delivery"><span>浏览器通知：{notify?'已开启':'未开启'}</span><button className="secondary compact" onClick={enableNotifications}>{notify?'检查浏览器权限':'开启浏览器通知'}</button><small>浏览器通知需保持网页打开；系统桌面通知由后台托盘控制。</small></div>
    </section>}
  </div>;
}
