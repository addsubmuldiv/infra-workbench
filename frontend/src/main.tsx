import {browserId} from './browserId';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, KeyRound, ArrowDownLeft, ArrowUpRight, CalendarClock, Check, ChevronRight, CircleHelp, Copy, Cpu, Database, LayoutGrid, LoaderCircle, Monitor, Plus, Palette, Radio, RefreshCw, Search, Server, Settings, ShieldCheck, Terminal, Trash2, X, Zap} from 'lucide-react';
import './style.css';
import './themes.css';
import './journey.css';
import './sidebarLayout.css';
import './windowLayers.css';
import './resourceOverview.css';
import './rendering.css';
import {WorkspaceLayout} from './WorkspaceLayout';
import {JourneyArt} from './JourneyArt';
const PrecisionCompare=React.lazy(()=>import('./PrecisionCompare').then(module=>({default:module.PrecisionCompare})));
const FileBrowser=React.lazy(()=>import('./FileBrowser').then(module=>({default:module.FileBrowser})));
import type {TerminalRequest} from './TerminalDock';
import {TerminalBoundary} from './TerminalBoundary';
import {pageFromHash,hostLocationFromHash,notificationLocation,type Page} from './navigation';
const TerminalDock=React.lazy(()=>import('./TerminalDock').then(module=>({default:module.TerminalDock})));
const ServerImport=React.lazy(()=>import('./ServerImport'));
import {THEMES, browserStorage, loadPreferences, savePreferences, scopedHosts, toggleHost} from './preferences';
import {shouldNotify,type NotificationRecord} from './notifications';
import {NotificationCenter,type NotificationTab} from './NotificationCenter';
import {Reservations,ReservationDialog,type ReservationDraft} from './ReservationPanel';
import {reservationDraft as draftFromReservation,reservationLocation,type Reservation} from './reservations';
const SettingsPage=React.lazy(()=>import('./SettingsPage'));
const InfraAssistant=React.lazy(()=>import('./InfraAssistantPage').then(module=>({default:module.InfraAssistant})));
import {Sparkles} from 'lucide-react';
import {singleFlight,reuseStateSnapshot} from './requests';
import {SSHPasswordDialog} from './SSHPasswordDialog';
import {RemoveHostDialog} from './RemoveHostDialog';
import {deviceUsage} from './hostUsage';
import {HOST_CATEGORIES,filterHosts,type HostCategory} from './hostList';
const bootPreferences=loadPreferences(browserStorage());
document.documentElement.dataset.theme=bootPreferences.theme;

type Proc = {pid:number; name:string; user:string|null; memory_used:number|null; uid?:number|null; effective_uid?:number|null; parent_pid?:number|null; cwd?:string|null; executable?:string|null; command?:string|null; command_truncated?:boolean; identity_verified?:boolean; detail_status?:string; detail_source?:string; errors?:Record<string,string>};
type Device = {id:string; display_id?:string; card_id?:string; chip_id?:string; physical_id?:string|null; kind:string; name:string; memory_total:number; memory_used:number; memory_free:number; utilization:number|null; temperature:number|null; processes:Proc[]; processes_known:boolean; health:string};
type SystemMetrics = {cpu_percent:number|null;cpu_cores:number|null;memory:{memory_total:number;memory_used:number;memory_available:number}|null};
type SudoSettings = {enabled:boolean;password_saved:boolean|null;credential_error?:string;password_in_memory:boolean;can_remember:boolean;status:string;message:string};
type Host = {id:string; target:string; user:string|null; port:number|null; manual:boolean; auth:string; sudo?:SudoSettings; ssh_password?:{password_saved:boolean|null;can_remember:boolean;error?:string|null}; snapshot:{status:string; fresh:boolean; collected_at:number|null; error?:string; error_stage?:string; system?:SystemMetrics|null; devices:Device[]}};
type Rule = {id:string; host_id:string; devices:string[]; minimum_gib:number; port:number; status?:string};
type Event = {id:number; created:number; host:string; message:string; notify?:boolean; url?:string};
type State = {hosts:Host[]; rules:Rule[]; reservations:Reservation[]; reservation_modes?:string[]; events:Event[]; server_time:number};
const gib=(n:number|null|undefined)=>n==null?'—':(n/1024**3).toFixed(1);
const clock=(n:number)=>new Date(n*1000).toLocaleTimeString('zh-CN',{hour12:false});
const displayId=(d:Device|undefined)=>d?.display_id??d?.id??'已失效';
function machineSummary(ds:Device[]){
  if(!ds.length)return '等待设备信息';
  const npus=ds.filter(d=>d.kind==='NPU'),cards=new Set(npus.map(d=>d.card_id??d.id));
  return npus.length>cards.size?`${cards.size} 张 NPU 卡 / ${npus.length} 个设备 · ${npus[0].name}`:`${ds.length} × ${ds[0].name}`;
}
async function api(path:string,method='GET',body?:unknown,signal?:AbortSignal){
  const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body),signal});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'操作失败');
  return data;
}
function isEligible(d:Device,min:number,clear:boolean){return d.memory_free>=min*1024**3&&(!clear||(d.processes_known&&d.processes.length===0))&&d.health!=='Alarm'}
function Badge({children,tone='muted'}:{children:React.ReactNode;tone?:string}){return <span className={'badge '+tone}>{children}</span>}

function App(){
  const [state,setState]=useState<State>({hosts:[],rules:[],reservations:[],events:[],server_time:0});
  const [reservationDraft,setReservationDraft]=useState<ReservationDraft|null>(null);
  const [pendingLocation,setPendingLocation]=useState(()=>hostLocationFromHash(location.hash));
  const [preferences,setPreferences]=useState(()=>loadPreferences(browserStorage()));
  const [hostSearch,setHostSearch]=useState('');
  const [hostCategory,setHostCategory]=useState<HostCategory>('全部');
  const [sudoHost,setSudoHost]=useState<Host|null>(null);
  const [sshPasswordHost,setSSHPasswordHost]=useState<Host|null>(null);
  const [removalHosts,setRemovalHosts]=useState<Host[]>([]);
  const [fileHost,setFileHost]=useState<{host:Host;requestId:string;path?:string}|null>(null);
  const [terminalRequest,setTerminalRequest]=useState<TerminalRequest|null>(null);
  const [notificationTab,setNotificationTab]=useState<NotificationTab>(()=>location.hash.split('?')[0]==='#watch'?'messages':null);
  const [precisionMounted,setPrecisionMounted]=useState(()=>pageFromHash(location.hash)==='precision');
  const [page,setPage]=useState<Page>(()=>pageFromHash(location.hash)),[filter,setFilter]=useState('全部'),[count,setCount]=useState(1),[minimum,setMinimum]=useState(16),[clear,setClear]=useState(true);
  const [resourceKind,setResourceKind]=useState('全部'),[selectedScope,setSelectedScope]=useState(false),[deviceOverview,setDeviceOverview]=useState(false);
  const [adding,setAdding]=useState(false),[detail,setDetail]=useState<{host:string;device:string}|null>(null),[selected,setSelected]=useState<Record<string,string[]>>({});
  const [notice,setNotice]=useState(''),[error,setError]=useState(''),[notify,setNotify]=useState(false),[busy,setBusy]=useState(''),[port,setPort]=useState(29500),[check,setCheck]=useState<{status:string;reasons:string[]}|null>(null);
  const lastEvent=useRef<number|null>(null),notifyRef=useRef(false),storageWarning=useRef(false),themeMenu=useRef<HTMLDetailsElement>(null),mobileHosts=useRef<HTMLDetailsElement>(null);
  const navigate=(next:Page)=>{
    setPage(next);if(next==='precision')setPrecisionMounted(true);
    setDetail(null);setCheck(null);
    if(themeMenu.current)themeMenu.current.open=false;
    if(location.hash!=='#'+next&&!(next==='overview'&&!location.hash))location.hash=next;
    if(next!==page)window.scrollTo({top:0});
  };
  useEffect(()=>{
    const sync=()=>{setPendingLocation(hostLocationFromHash(location.hash));const next=pageFromHash(location.hash);setPage(next);if(next==='precision')setPrecisionMounted(true);setDetail(null);setCheck(null);window.scrollTo({top:0})};
    const syncLegacy=()=>{const legacy=location.hash.split('?')[0];if(legacy==='#watch')setNotificationTab('messages');if(legacy==='#connections'||legacy==='#watch')window.history.replaceState(window.history.state,'',location.hash.replace(/^#(?:connections|watch)/,'#overview'));sync()};
    if(['#connections','#watch'].includes(location.hash.split('?')[0]))syncLegacy();
    window.addEventListener('hashchange',syncLegacy);return()=>window.removeEventListener('hashchange',syncLegacy);
  },[]);
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{for(const menu of [themeMenu.current])if(menu?.open&&!menu.contains(event.target as Node))menu.open=false};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')for(const menu of [themeMenu.current])if(menu)menu.open=false};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)};
  },[]);
  const stateRequest=useRef<AbortController|null>(null);
  const [load]=useState(()=>singleFlight(async()=>{
    const controller=new AbortController();stateRequest.current=controller;
    try{
      const next:State=await api('/state','GET',undefined,controller.signal);if(controller.signal.aborted)return;setState(old=>reuseStateSnapshot(old,{...next,reservations:next.reservations??[]}));setError('');
      if(lastEvent.current!==null&&notifyRef.current&&'Notification' in window&&Notification.permission==='granted')
        for(const event of [...next.events].reverse())if(event.id>lastEvent.current&&shouldNotify(event)){
          const notification=new Notification('Infra Workbench',{body:event.message,tag:String(event.id)});
          notification.onclick=()=>{window.open(location.origin+location.pathname+notificationLocation(event.url),'_blank','noopener');notification.close()};
        }
      lastEvent.current=next.events[0]?.id??lastEvent.current??0;
    }catch{if(!controller.signal.aborted)setError('本地服务未连接，请检查启动窗口。')}
    finally{if(stateRequest.current===controller)stateRequest.current=null}
  }));
  useEffect(()=>{load();const timer=setInterval(load,2000);return()=>{clearInterval(timer);stateRequest.current?.abort()}},[]);
  useEffect(()=>{
    document.documentElement.dataset.theme=preferences.theme;
    if(!savePreferences(browserStorage(),preferences)&&!storageWarning.current){storageWarning.current=true;setNotice('浏览器不允许保存偏好，主题与机器选择在关闭页面后将无法恢复。')}
  },[preferences]);
  useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),7000);return()=>clearTimeout(t)},[notice]);
  useEffect(()=>{
    if(!pendingLocation||!state.server_time)return;
    const host=state.hosts.find(host=>host.id===pendingLocation.hostId);
    if(!host){setNotice('提醒对应的机器已移除，请在卡预约中查看记录。');setPendingLocation(null);return}
    if(host.snapshot.status==='connecting'&&!host.snapshot.devices.length)return;
    const ids=pendingLocation.devices.filter(id=>host.snapshot.devices.some(device=>device.id===id));
    setPreferences(old=>({...old,hostIds:[host.id]}));setFilter('全部');setHostCategory('全部');setHostSearch('');
    setSelected({[host.id]:ids});
    if(ids.length<pendingLocation.devices.length)setNotice('已定位机器；部分设备未出现在最近采集中，请核对当前设备列表。');
    else if(ids.length)setNotice('已定位提醒对应的机器和设备，请在使用前检查当前占用。');
    setPendingLocation(null);
  },[pendingLocation,state.hosts,state.server_time]);
  const locateReservation=(item:Reservation)=>{
    const hash=reservationLocation(item);setPage('overview');setDetail(null);setCheck(null);
    setPendingLocation(hostLocationFromHash(hash));location.hash=hash;window.scrollTo({top:0});
  };

  const locateEvent=(event:NotificationRecord)=>{
    const target=hostLocationFromHash(event.url??'');
    if(target){setPage('overview');setPendingLocation(target);setDetail(null);setCheck(null);location.hash=event.url!;window.scrollTo({top:0})}
    else if(state.hosts.some(host=>host.id===event.host))selectHosts([event.host],true);
    else navigate('reservations');
  };

  const act=async(key:string,fn:()=>Promise<unknown>)=>{setBusy(key);try{await fn();await load()}catch(e){setNotice(e instanceof Error?e.message:String(e))}finally{setBusy('')}};
  const enableNotifications=async()=>{
    if(!('Notification'in window)){setNotice('此浏览器不支持系统通知，事件仍显示在页面中。');return}
    const permission=await Notification.requestPermission();notifyRef.current=permission==='granted';setNotify(notifyRef.current);
    setNotice(notifyRef.current?'浏览器通知已开启；请保持页面和本地服务运行。':'浏览器通知未开启，事件仍显示在页面中。');
  };
  const scope=useMemo(()=>scopedHosts(state.hosts,preferences.hostIds),[state.hosts,preferences.hostIds]);
  const allMachinesSelected=state.hosts.length>0&&scope.length===state.hosts.length;
  const devices=useMemo(()=>state.hosts.flatMap(h=>h.snapshot.devices),[state.hosts]);
  const online=useMemo(()=>state.hosts.filter(h=>h.snapshot.fresh).length,[state.hosts]);
  const waitingReservations=useMemo(()=>state.reservations.filter(item=>item.status!=='ready'),[state.reservations]);
  const reservationMachines=new Set(waitingReservations.map(item=>item.host_id)).size;
  const pendingReservations=waitingReservations.length;
  const matches=(h:Host)=>h.snapshot.fresh?h.snapshot.devices.filter(d=>(resourceKind==='全部'||d.kind===resourceKind)&&isEligible(d,minimum,clear)):[];
  const searchScope=selectedScope?scope:state.hosts;
  const candidates=useMemo(()=>searchScope.filter(h=>matches(h).length>=count),[searchScope,resourceKind,minimum,clear,count]);
  const globalCandidates=useMemo(()=>state.hosts.filter(h=>matches(h).length>=count),[state.hosts,resourceKind,minimum,clear,count]);
  const deviceGroups=useMemo(()=>!deviceOverview?[]:Array.from(new Set(devices.map(d=>JSON.stringify([d.kind,d.name])))).sort().map(key=>{
    const [kind,name]=JSON.parse(key) as [string,string];
    const hosts=state.hosts.filter(h=>h.snapshot.devices.some(d=>d.kind===kind&&d.name===name));
    return {key,kind,name,hosts,total:hosts.reduce((n,h)=>n+h.snapshot.devices.filter(d=>d.kind===kind&&d.name===name).length,0)};
  }),[deviceOverview,devices,state.hosts]);
  const shown=useMemo(()=>scope.filter(h=>filter==='全部'||h.snapshot.devices.some(d=>d.kind===filter)||!h.snapshot.devices.length),[scope,filter]);
  const detailHost=state.hosts.find(h=>h.id===detail?.host),detailDevice=detailHost?.snapshot.devices.find(d=>d.id===detail?.device);
  const toggle=(h:string,d:string)=>setSelected(old=>({...old,[h]:(old[h]||[]).includes(d)?old[h].filter(i=>i!==d):[...(old[h]||[]),d]}));
  const clearDeviceSelection=(event:React.MouseEvent<HTMLElement>)=>{
    const target=event.target;
    // Only the background itself counts as blank space. Device rows, controls,
    // selection actions and floating windows keep their normal interactions.
    if(!(target instanceof Element)||!target.matches('main,.content,.two-columns,.machines,.section-heading,.page-heading,.machine,.machine-heading,.machine-footer,.stats,.stats>div,.finder,.system-summary,.page-footer,.footnote'))return;
    if(window.getSelection()?.isCollapsed===false)return;
    setSelected(old=>Object.values(old).some(ids=>ids.length)?{}:old);
  };
  const selectHosts=(ids:string[]|null,direct=false)=>{
    setPreferences(old=>({...old,hostIds:ids}));
    if(direct){setFilter('全部');if(mobileHosts.current)mobileHosts.current.open=false;window.scrollTo({top:0})}
    navigate('overview');
  };

  const showMachines=(ids:string[]|null,kind='全部')=>{
    setDeviceOverview(false);setHostSearch('');setHostCategory('全部');setSelected({});setFilter(kind);selectHosts(ids);
    if(mobileHosts.current)mobileHosts.current.open=false;
    setNotice(ids===null?'已展示全部机器':ids.length?`已展示 ${ids.length} 台机器`:'已清空机器选择，仍可在全部机器中寻找资源');
  };
  const showMatches=(hosts:Host[])=>{if(hosts.length)showMachines(hosts.map(h=>h.id),resourceKind)};
  const resourceBody=(h:Host)=>({host_id:h.id,devices:selected[h.id]||[],minimum_gib:minimum,port});
  const removeHost=async(host:Pick<Host,'id'|'target'>)=>{
    await api('/hosts/'+encodeURIComponent(host.id),'DELETE');
    await load();
    setState(old=>({...old,hosts:old.hosts.filter(h=>h.id!==host.id),rules:old.rules.filter(r=>r.host_id!==host.id),reservations:old.reservations.filter(r=>r.host_id!==host.id)}));
    setPreferences(old=>({...old,hostIds:old.hostIds===null?null:old.hostIds.filter(id=>id!==host.id)}));
    setSelected(old=>{const next={...old};delete next[host.id];return next});
    if(fileHost?.host.id===host.id)setFileHost(null);
    if(sshPasswordHost?.id===host.id)setSSHPasswordHost(null);
    if(sudoHost?.id===host.id)setSudoHost(null);
    if(detail?.host===host.id){setDetail(null);setCheck(null)}
    setNotice('已移除机器 '+host.target);
  };
  const inspect=(host:Host,d:Device)=>{setDetail({host:host.id,device:d.id});setCheck(null)};
  const pageTitle=page==='overview'?'算力总览':page==='precision'?'训练精度对比':page==='reservations'?'卡预约':page==='settings'?'设置':page==='assistant'?'AI 助手':'算力总览';
  useEffect(()=>{document.title=pageTitle+' · Infra Workbench'},[pageTitle]);
  const listedHosts=filterHosts(state.hosts,hostCategory,hostSearch);
  const hostList=<div className="host-picker">
    <div className="host-picker-heading"><span>机器列表</span><span>{scope.length} / {state.hosts.length}</span></div>
    <div className="host-search"><Search size={14}/><input aria-label="搜索机器列表" placeholder="搜索机器…" value={hostSearch} onChange={e=>setHostSearch(e.target.value)}/></div>
    <div className="host-category-filter" role="group" aria-label="机器分类">{HOST_CATEGORIES.map(category=><button key={category} type="button" aria-label={category==='全部'?'显示全部类型的机器':'只显示'+category+'机器'} aria-pressed={hostCategory===category} className={hostCategory===category?'selected':''} onClick={()=>setHostCategory(category)}>{category}<b>{filterHosts(state.hosts,category).length}</b></button>)}</div>
    <div className="host-picker-actions"><button title="选择全部机器，包括其他分类" onClick={()=>selectHosts(null)} className={preferences.hostIds===null?'selected':''}>全选</button><button onClick={()=>selectHosts([])}>清空</button><span>点击名称查看设备，勾选多选</span></div>
    <div className="host-picker-items">{listedHosts.map(h=>{
      const checked=preferences.hostIds===null||preferences.hostIds.includes(h.id);
      const usage=deviceUsage(h.snapshot);
      return <div className={'host-picker-row '+(checked?'selected':'')} key={h.id}>
        <input type="checkbox" aria-label={'显示机器 '+h.target} checked={checked} onChange={()=>selectHosts(toggleHost(preferences.hostIds,h.id,state.hosts.map(h=>h.id)))}/>
        <button aria-label={'只看机器 '+h.target} title={h.target+" · 查看此机器的设备"} onClick={()=>selectHosts([h.id],true)}><span className={'host-dot '+(h.snapshot.fresh?'online':'')}/><span><strong>{h.target}</strong><small>{usage.total} 卡 · {h.snapshot.fresh?'在线':h.snapshot.status==='error'?'采集失败':'等待采集'}</small><small className="host-usage" title="按设备数统计（多芯片卡每个 die 单独计数）。有计算进程计为占用；确认无计算进程且无 Alarm 计为空闲，不受显存筛选影响。">{h.snapshot.fresh&&usage.total>0?<><span className="occupied">占用 <b>{usage.occupied}</b></span><span className="idle">空闲 <b>{usage.idle}</b></span>{usage.unknown>0&&<span>未知 <b>{usage.unknown}</b></span>}{usage.abnormal>0&&<span className="abnormal">异常 <b>{usage.abnormal}</b></span>}</>:<span>{usage.total?'状态待更新':'等待设备信息'}</span>}</small></span></button>
        <small className="host-compact-status" title={`${h.target} · ${h.snapshot.fresh?'在线':h.snapshot.status==='error'?'采集失败':'等待采集'} · ${usage.total} 卡 · 空闲 ${usage.idle} · 占用 ${usage.occupied} · 未知 ${usage.unknown} · 异常 ${usage.abnormal}`}>
          {h.snapshot.fresh&&usage.total>0?<><span>空闲 {usage.idle}</span><span>占用 {usage.occupied}</span>{usage.abnormal>0&&<span className="abnormal">异常 {usage.abnormal}</span>}{usage.unknown>0&&<span>未知 {usage.unknown}</span>}</>:<span className={h.snapshot.status==='error'?'abnormal':''}>{h.snapshot.status==='error'?'采集失败':h.snapshot.fresh?'等待设备':'等待采集'}</span>}
        </small>
        <button className="host-remove-button" aria-label={'从列表移除机器 '+h.target} title={'移除机器 '+h.target} onClick={()=>setRemovalHosts([h])}><Trash2 size={14}/></button>
      </div>})}
      {state.hosts.length===0&&<p className="subtle">添加机器后会出现在这里。</p>}
      {state.hosts.length>0&&!listedHosts.length&&<p className="subtle">{hostSearch.trim()?'没有匹配的机器。':`暂无${hostCategory==='全部'?'':' '+hostCategory+' '}机器。`}</p>}
    </div>
  </div>;
  return <WorkspaceLayout onClickCapture={event=>{
    if(deviceOverview&&event.target instanceof Element&&!event.target.closest('#device-overview,[aria-controls="device-overview"]'))setDeviceOverview(false);
  }}>
    <aside className="sidebar"><div className="brand"><span className="brand-icon"><Cpu size={23}/></span><div>Infra<span>WORKBENCH</span></div></div>
      <div className="nav-label">工作台</div><nav>{[["overview","算力总览",LayoutGrid],["reservations","卡预约",CalendarClock],["precision","精度对比",Activity],["assistant","AI 助手",Sparkles],["settings","设置",Settings]].map(([key,label,Icon])=><button key={String(key)} title={String(label)} aria-label={String(label)} className={page===key?'active':''} aria-current={page===key?'page':undefined} onClick={()=>navigate(String(key) as Page)}><Icon size={18}/>{String(label)}{key==='reservations'&&state.reservations.some(r=>r.status!=='ready')&&<span className="nav-count">{state.reservations.filter(r=>r.status!=='ready').length}</span>}</button>)}</nav>
      <div className="sidebar-hosts">{hostList}</div>
      <div className="sidebar-bottom"><div className={'agent'+(error?' disconnected':'')} role="status" tabIndex={0} title="自动保存机器选择，下次打开时恢复（需浏览器允许本地存储）。通过 SSH 连接远端机器，无需远端常驻 Agent。"><i aria-hidden="true"/>本地服务{error?'未连接':'已连接'}</div></div>
    </aside>
    <main onClick={clearDeviceSelection}><header><div className="breadcrumb">工作空间 <ChevronRight size={13}/>{pageTitle}</div>
      <div className="header-tools"><span className="live"><i/>10s 实时采集</span>
        <details className="theme-menu" ref={themeMenu}><summary><Palette size={16}/><span>主题</span></summary><div className="theme-options"><h3>选择界面主题</h3><p>主题偏好自动保存在本机</p>{THEMES.map(t=><button key={t.id} aria-pressed={preferences.theme===t.id} onClick={()=>{setPreferences(old=>({...old,theme:t.id}));if(themeMenu.current)themeMenu.current.open=false}}>
          <span className="theme-swatches">{t.swatches.map(color=><i key={color} style={{background:color}}/>)}</span><span><strong>{t.name}</strong><small>{t.mode==='light'?'亮色':'暗色'} · {t.description}</small></span>{preferences.theme===t.id&&<Check size={15}/>}</button>)}</div></details>
        <NotificationCenter events={state.events} rules={state.rules} hosts={state.hosts} tab={notificationTab} setTab={setNotificationTab} notify={notify} busy={!!busy} enableNotifications={enableNotifications} removeRule={id=>act('rule',()=>api('/rules/'+encodeURIComponent(id),'DELETE'))} locate={locateEvent}/><span className="avatar small">本</span>
      </div></header>
    {preferences.theme==='frieren'&&<JourneyArt/>}
    <div className="content"><div className="page-heading"><div><div className="eyebrow">COMPUTE / {page==='precision'?'PRECISION COMPARE':page==='overview'?'OVERVIEW':page==='reservations'?'RESERVATIONS':page==='settings'?'SETTINGS':page==='assistant'?'AI ASSISTANT':'OVERVIEW'}</div><h1>{pageTitle}<span className="heading-dot"/></h1><p>{page==='precision'?'跨机器读取训练日志，自动提取指标并按真实步数对齐。':page==='reservations'?'预约指定设备，等它们连续空闲后收到提醒。':page==='settings'?'管理模型接口、外部 Agent 接入和邮件通知。':page==='assistant'?'查找多台机器上的任务与会话，了解资源发生了哪些变化。':`全部 ${state.hosts.length} 台机器的资源概况 · 左侧勾选用于查看详情和批量删除`}</p></div><div className="page-heading-actions"><button className="primary" onClick={()=>setAdding(true)}><Plus size={17}/>添加机器</button><button className="secondary machine-delete-action" aria-label="删除机器" title={scope.length?`删除选中的 ${scope.length} 台机器`:'请先在左侧勾选机器'} disabled={scope.length===0} onClick={()=>setRemovalHosts([...scope])}><Trash2 size={15}/>删除机器{scope.length>0&&<span className="machine-delete-count">{scope.length}</span>}</button></div></div>
    <details className="mobile-hosts" ref={mobileHosts}><summary><Server size={15}/>选择机器 · {scope.length} / {state.hosts.length}</summary>{hostList}</details>
    {error&&<div className="error-banner">{error}</div>}
    {precisionMounted&&<div className="precision-cache" hidden={page!=='precision'}><React.Suspense fallback={<p role="status">正在加载精度对比…</p>}><PrecisionCompare hosts={state.hosts}/></React.Suspense></div>}
    {page==='overview'&&<><div className="stats" aria-label="全部机器资源总览"><div className="overview-stat"><span>全部机器<Server size={16}/></span><strong>{online}<small>/ {state.hosts.length}</small></strong><p><i className="dot"/>在线 / 已添加</p><span className="stat-action">{allMachinesSelected?'清空机器选择':'查看全部机器'} <ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label={allMachinesSelected?'清空机器选择':'查看全部机器'} aria-pressed={allMachinesSelected} disabled={!state.hosts.length} title={allMachinesSelected?'已全选，点击清空机器选择':'全选机器并清除详情筛选'} onClick={()=>showMachines(allMachinesSelected?[]:null)}/></div><div className="overview-stat"><span>加速设备<Cpu size={16}/></span><strong>{devices.length}<small>个设备</small></strong><p>{devices.filter(d=>d.kind==='NPU').length} NPU <b>·</b> {devices.filter(d=>d.kind==='GPU').length} GPU</p><span className="stat-action">{deviceOverview?'收起设备概览':'按类型与型号查看'} <ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label={deviceOverview?'收起加速设备概览':'展开加速设备概览'} aria-expanded={deviceOverview} aria-controls="device-overview" onClick={()=>setDeviceOverview(!deviceOverview)}/></div><div className="overview-stat"><span title="根据当前设备数量、类型、显存和进程条件，在全部机器中统计，不受左侧选择影响">全局符合条件<ShieldCheck size={16}/></span><strong className="teal">{globalCandidates.length}<small>台机器</small></strong><p>至少 {count} 个{resourceKind==='全部'?'设备':resourceKind} · 每个 ≥ {minimum} GiB</p><span className="stat-action">查看符合条件的机器 <ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label="查看全局符合条件的机器" disabled={!globalCandidates.length} title="在全部机器中按寻找栏条件匹配，点击展示结果" onClick={()=>showMatches(globalCandidates)}/></div><div className="reservation-stat"><span>我的预约<CalendarClock size={16}/></span><strong>{pendingReservations}<small>条</small></strong><p>{reservationMachines} 台机器 · {pendingReservations} 条等待中</p><button className="reservation-stat-link" aria-label={`查看卡预约，${pendingReservations} 条等待中`} title="仅统计尚未满足条件的预约。点击查看和管理全部预约；预约为空闲提醒，不锁定设备。" onClick={()=>navigate('reservations')}/></div></div>
      {deviceOverview&&<section id="device-overview" className="device-overview" aria-label="加速设备分类概览"><div className="section-heading"><h2>全局加速设备 <span>{devices.length} 个设备</span></h2><button className="text-button" onClick={()=>setDeviceOverview(false)}>收起 <X size={14}/></button></div><p>按类型和型号查看对应机器；数量包含最近采集记录，请以机器在线状态为准。</p><div className="device-groups">{deviceGroups.map(group=><button key={group.key} aria-label={`查看 ${group.kind} ${group.name} 对应机器`} onClick={()=>showMachines(group.hosts.map(h=>h.id),group.kind)}><span className="badge">{group.kind}</span><span className="device-group-name">{group.name}</span><strong>{group.total} 个设备 <small>· {group.hosts.length} 台机器</small></strong><ArrowUpRight size={15}/></button>)}</div>{!deviceGroups.length&&<p>尚未采集到设备，连接机器后会在这里显示。</p>}</section>}
      <section className="finder"><div className="finder-label"><Search size={18}/><div>寻找训练资源<small>{selectedScope?`仅搜索所选 ${scope.length} 台机器`:`搜索全部 ${state.hosts.length} 台机器 · 不受左侧勾选影响`}</small></div></div><label>设备类型<select aria-label="寻找设备类型" value={resourceKind} onChange={e=>setResourceKind(e.target.value)}>{['全部','NPU','GPU'].map(kind=><option key={kind} value={kind}>{kind}</option>)}</select></label><label>需要设备数<select aria-label="需要设备数" value={count} onChange={e=>setCount(+e.target.value)}>{Array.from({length:Math.max(8,count,...state.hosts.map(h=>h.snapshot.devices.length))},(_,i)=>i+1).map(i=><option key={i} value={i}>{i} 个</option>)}</select></label><label>剩余显存<div className="input-unit"><input aria-label="每个设备剩余显存" type="number" min="0" max="100000" value={minimum} onChange={e=>setMinimum(Math.max(0,+e.target.value))}/><span>GiB</span></div></label><label className="checkbox-label"><input type="checkbox" checked={clear} onChange={e=>setClear(e.target.checked)}/>无可见计算进程</label><label className="checkbox-label"><input type="checkbox" aria-label="仅在所选机器中寻找" checked={selectedScope} onChange={e=>setSelectedScope(e.target.checked)}/>仅在所选机器中寻找</label><div className="match-count"><strong>{candidates.length}</strong><span>台符合条件{selectedScope?'（所选范围）':'（全局）'}</span><button className="secondary" aria-label="查看匹配机器" disabled={!candidates.length} onClick={()=>showMatches(candidates)}>查看机器 <ArrowUpRight size={15}/></button></div></section>
    </>}
    {page==='overview'&&<div className="two-columns"><div className="machines"><div className="section-heading"><h2>所选机器详情<span>{shown.length} 台机器</span></h2><div className="segmented">{['全部','NPU','GPU'].map(f=><button className={filter===f?'chosen':''} key={f} onClick={()=>setFilter(f)}>{f}</button>)}</div></div>
      {shown.length===0&&<div className="empty"><Server size={32}/><h3>{state.hosts.length===0?'连接第一台机器':scope.length===0?'选择要查看的机器':'没有符合设备类型的机器'}</h3><p>{state.hosts.length===0?'从本机 SSH 配置选择，或输入主机和账号密码。':'在机器列表中点击名称单选，或勾选多台机器。'}</p>{state.hosts.length===0?<button className="primary" onClick={()=>setAdding(true)}><Plus size={16}/>添加机器</button>:<button className="secondary" onClick={()=>showMachines(null)}>显示全部机器</button>}</div>}
      {shown.map(host=>{const snapshot=host.snapshot,ids=selected[host.id]||[];return <section className="machine" key={host.id} aria-label={'机器详情 '+host.target}>
        <div className="machine-heading"><span className="machine-icon"><Server size={20}/></span><div className="machine-name"><h3>{host.target}<Badge tone={snapshot.fresh?'green':'amber'}>{snapshot.fresh?'在线':snapshot.status==='error'?'采集失败':snapshot.status==='connecting'?'连接中':'数据过期'}</Badge></h3><p>{machineSummary(snapshot.devices)} <span>·</span> SSH {host.auth==='password_session'?'密码会话':'免密连接'}</p></div><button className="ssh-open" aria-label={'预约 '+host.target+' 的卡'} title="预约这台机器的卡" onClick={()=>setReservationDraft({hostId:host.id,devices:ids.filter(id=>snapshot.devices.some(device=>device.id===id)),minimum})}><CalendarClock size={15}/><span>预约</span></button><button className="ssh-open" aria-label={'浏览 '+host.target+' 文件'} onClick={()=>setFileHost({host,requestId:browserId()})}><Database size={15}/><span>文件</span></button><button className="ssh-open" aria-label={'打开 '+host.target+' 终端'} onClick={()=>setTerminalRequest({id:browserId(),host})}><Terminal size={15}/><span>终端</span></button><button className={'sudo-button '+(host.ssh_password?.password_saved===true?'enabled':'')} aria-label={host.target+' SSH 密码设置'} title={host.ssh_password?.password_saved===true?'SSH 密码已保存，点击管理':host.ssh_password?.password_saved===false?'尚未保存 SSH 密码，点击配置':'SSH 密码保存状态尚未确认，点击查看'} onClick={()=>setSSHPasswordHost(host)}><KeyRound size={15}/><span>SSH 密码</span></button><button className={'sudo-button '+(host.sudo?.enabled?'enabled':'')} title={host.sudo?.message||'设置 sudo 进程详情'} aria-label={host.target+' sudo 设置'} onClick={()=>setSudoHost(host)}><ShieldCheck size={15}/><span>sudo</span></button><button className="icon-button" aria-label={'刷新 '+host.target} disabled={busy===host.id} onClick={()=>act(host.id,()=>api('/hosts/'+host.id+'/refresh','POST'))}><RefreshCw size={16} className={busy===host.id?'spin':''}/></button><button className="secondary compact remove-host-button" aria-label={'移除机器 '+host.target} title="移除机器" onClick={()=>setRemovalHosts([host])}><Trash2 size={15}/><span>移除</span></button></div>
        {host.sudo?.enabled&&!['ready','pending'].includes(host.sudo.status)&&<div className="sudo-alert"><ShieldCheck size={14}/><span>{host.sudo.message}</span><button className="text-button" onClick={()=>setSudoHost(host)}>设置</button></div>}
        <SystemSummary system={snapshot.system} fresh={snapshot.fresh}/>
        {snapshot.error&&<div className="connection-error"><p>{snapshot.error_stage==='parse'?'SSH 已连接 · 设备信息解析失败：':snapshot.error_stage==='probe'?'SSH 已连接 · 远端采集失败：':''}{snapshot.error}</p>{snapshot.error_stage==='connection'?<button className="text-button" onClick={()=>setAdding(true)}>检查连接凭据 <ArrowUpRight size={13}/></button>:<button className="text-button" disabled={busy===host.id} onClick={()=>act(host.id,()=>api('/hosts/'+host.id+'/refresh','POST'))}>重试采集 <RefreshCw size={13}/></button>}</div>}
        {snapshot.devices.length>0&&<div className="device-table-scroll"><table className="device-table"><thead><tr><th>选择</th><th>设备</th><th>状态</th><th>显存已用 / 总量</th><th>计算利用率</th><th>温度</th><th>占用用户 / PID</th></tr></thead><tbody>
          {snapshot.devices.filter(d=>filter==='全部'||d.kind===filter).map(d=>{const suitable=snapshot.fresh&&isEligible(d,minimum,clear),occupied=d.processes.length>0;
            return <tr key={d.id} className={!snapshot.fresh?'stale':''} onClick={()=>inspect(host,d)}>
              <td onClick={e=>e.stopPropagation()}><input type="checkbox" aria-label={'选择 '+host.target+' 设备 '+displayId(d)} checked={ids.includes(d.id)} onChange={()=>toggle(host.id,d.id)}/></td>
              <td><button className="device-open" aria-label={host.target+' '+d.kind+' '+displayId(d)+' 详情'} onClick={e=>{e.stopPropagation();inspect(host,d)}}><span className="device-number">{d.kind} {displayId(d).padStart(2,'0')}</span>{(d.physical_id!=null||d.id.startsWith('chip:'))&&<small>卡 {d.card_id} / 芯片 {d.chip_id}</small>}</button></td>
              <td><span className={'device-pill '+(!snapshot.fresh?'muted':d.health==='Alarm'?'danger':occupied?'amber':suitable?'green':'muted')}><i/>{!snapshot.fresh?'信息过期':d.health==='Alarm'?'设备异常':!d.processes_known?'进程未知':occupied?'进程占用':suitable?'满足条件':'显存不足'}</span>{d.health==='Warning'&&<span className="health-warning" title="仅提示，不影响资源推荐">Warning</span>}</td>
              <td className="memory-cell"><span>{gib(d.memory_used)} <small>/ {gib(d.memory_total)} GiB</small></span><div className={'meter '+(occupied?'busy-meter':'')}><i style={{width:Math.min(100,d.memory_used/d.memory_total*100)+'%'}}/></div></td>
              <td className="numeric">{d.utilization??'—'}<small>%</small></td><td className="numeric">{d.temperature??'—'}<small>°C</small></td><td><button className="process-link process-summary" aria-label={host.target+' 设备 '+displayId(d)+' 占用进程'} onClick={e=>{e.stopPropagation();inspect(host,d)}}><span><strong>{d.processes.length?[...new Set(d.processes.map(p=>p.user||'用户未知'))].join(', '):d.processes_known?'无计算进程':'未知'}</strong>{d.processes.length>0&&<small>PID {d.processes.slice(0,3).map(p=>p.pid).join(', ')}{d.processes.length>3?'…':''} · {d.processes.length} 个</small>}</span><ChevronRight size={12}/></button></td>
            </tr>})}
        </tbody></table></div>}
        <div className="machine-footer"><span><i className={'dot '+(!snapshot.fresh?'muted-dot':'')}/>{snapshot.collected_at?'最近采集 '+clock(snapshot.collected_at):'尚未采集'}{snapshot.fresh&&matches(host).length>=count&&<em>符合当前资源需求</em>}</span><button className="text-button" onClick={()=>navigator.clipboard.writeText('ssh '+host.target).then(()=>setNotice('SSH 命令已复制')).catch(()=>setNotice('复制失败，请手动使用 ssh '+host.target))}><Terminal size={13}/>复制 SSH</button></div>
        {ids.length>0&&<div className="selection-bar"><span>已选设备 {ids.map(id=>displayId(snapshot.devices.find(d=>d.id===id))).join(', ')}</span><label>端口<input type="number" min="1" max="65535" aria-label="训练端口" value={port} onChange={e=>setPort(+e.target.value)}/></label><button className="secondary" disabled={!!busy} onClick={()=>act('check',async()=>{setCheck(await api('/preflight','POST',resourceBody(host)));setDetail({host:host.id,device:ids[0]})})}>训练前检查</button><button className="primary compact" disabled={!!busy} onClick={()=>act('rule',async()=>{await api('/rules','POST',resourceBody(host));setNotice('监控已添加，可在右上角通知中心管理。');setNotificationTab('rules')})}><Radio size={14}/>监控所选</button><button className="primary compact" disabled={!!busy||!snapshot.fresh} onClick={()=>setReservationDraft({hostId:host.id,devices:ids,minimum})}><CalendarClock size={14}/>预约所选</button></div>}
      </section>})}
      <div className="footnote"><CircleHelp size={14}/>低利用率不代表空闲。筛选结果反映资源指标，不代表资源授权或预留。</div>
    </div></div>}
    {page==='settings'&&<React.Suspense fallback={<p role="status">正在加载设置…</p>}><SettingsPage/></React.Suspense>}
    {page==='assistant'&&<React.Suspense fallback={<p role="status">正在加载 AI 助手…</p>}><InfraAssistant selectedHostIds={scope.map(host=>host.id)} openSettings={()=>navigate('settings')} locate={(hostId,devices)=>{if(!state.hosts.some(host=>host.id===hostId)){setNotice('这台机器已不在当前列表中。');return}showMachines([hostId]);setSelected({[hostId]:devices});navigate('overview')}} openTerminal={hostId=>{const host=state.hosts.find(host=>host.id===hostId);if(host)setTerminalRequest({id:browserId(),host});else setNotice('这台机器已不在当前列表中。')}}/></React.Suspense>}
    {page==='reservations'&&<Reservations items={state.reservations} create={()=>setReservationDraft({})} edit={item=>setReservationDraft(draftFromReservation(item,true))} rebook={item=>setReservationDraft(draftFromReservation(item,false))} locate={locateReservation} remove={async(id)=>{await api('/reservations/'+id,'DELETE');await load()}} enableNotifications={enableNotifications} notify={notify}/>}
    <footer className="page-footer"><span><ShieldCheck size={13}/>私钥留在本机 · sudo 密码可选存入系统凭据管理器</span><span>LOCAL WORKSPACE / {new Date().getFullYear()}</span></footer></div></main>
    <TerminalBoundary close={()=>setTerminalRequest(null)}><React.Suspense fallback={<div className="terminal-loading" role="status">正在加载终端…</div>}>{terminalRequest&&<TerminalDock request={terminalRequest} hosts={state.hosts} onDirectory={(hostId,path)=>{const host=state.hosts.find(host=>host.id===hostId);if(host)setFileHost({host,path,requestId:browserId()})}}/>}</React.Suspense></TerminalBoundary>
    {notice&&<div role="status" className="toast"><Check size={17}/>{notice}<button className="icon-button" aria-label="关闭提示" onClick={()=>setNotice('')}><X size={15}/></button></div>}
    {adding&&<AddMachine close={()=>setAdding(false)} imported={async ids=>{setPreferences(old=>({...old,hostIds:old.hostIds===null?null:[...new Set([...old.hostIds,...ids])]}));await load()}} connected={async(message,hostId)=>{if(hostId)setPreferences(old=>({...old,hostIds:old.hostIds===null?null:[...new Set([...old.hostIds,hostId])]}));setNotice(message);setAdding(false);await load()}}/>}
    {reservationDraft&&<ReservationDialog countEnabled={state.reservation_modes?.includes('count')} hosts={state.hosts} draft={reservationDraft} close={()=>setReservationDraft(null)} openSettings={()=>{setReservationDraft(null);navigate('settings')}} save={async(body)=>{await api(reservationDraft.editingId?'/reservations/'+encodeURIComponent(reservationDraft.editingId):'/reservations',reservationDraft.editingId?'PATCH':'POST',body);await load();setNotice(reservationDraft.editingId?'预约已更新，按新条件重新计时。':'预约已保存；所选设备连续空闲后会提醒一次。')}}/>}
    {fileHost&&<React.Suspense fallback={<p role="status">正在加载文件浏览器…</p>}><FileBrowser onTerminal={(hostId,cwd)=>{const host=state.hosts.find(host=>host.id===hostId);if(host)setTerminalRequest({id:browserId(),host,cwd})}} initialPath={fileHost.path} host={fileHost.host} requestId={fileHost.requestId} hosts={state.hosts} close={()=>setFileHost(null)}/></React.Suspense>}
    {sshPasswordHost&&<SSHPasswordDialog key={sshPasswordHost.id} host={sshPasswordHost} close={()=>setSSHPasswordHost(null)} updated={async()=>{await load()}}/>}
    {removalHosts.length>0&&<RemoveHostDialog hosts={removalHosts} close={()=>setRemovalHosts([])} remove={removeHost}/>}
    {sudoHost&&<SudoModal key={sudoHost.id} host={sudoHost} close={()=>setSudoHost(null)} updated={async()=>{await load()}}/>}
    {detail&&<div className="drawer-shade" onClick={()=>{setDetail(null);setCheck(null)}}><section className="drawer" onClick={e=>e.stopPropagation()}><div className="drawer-heading"><div className="eyebrow">DEVICE INSPECTOR</div><button className="icon-button" aria-label="关闭设备详情" onClick={()=>{setDetail(null);setCheck(null)}}><X size={20}/></button></div><h2>{detailHost?.target}</h2><p className="subtle">{detailDevice?.kind} {detailDevice?displayId(detailDevice):''} · {detailDevice?.name}{detailDevice?.physical_id!=null&&` · 卡 ${detailDevice.card_id} / 芯片 ${detailDevice.chip_id}`}</p>{detailDevice&&<><div className="detail-metrics"><div>剩余显存<strong>{gib(detailDevice.memory_free)} <small>GiB</small></strong></div><div>计算利用率<strong>{detailDevice.utilization??'—'}<small>%</small></strong></div></div><h3>计算进程 <Badge>{detailDevice.processes.length}</Badge></h3>{!detailDevice.processes_known?<div className="error-banner">进程信息无法完整读取，不能确认空闲。</div>:detailDevice.processes.length===0?<p className="subtle">采集工具未报告可见计算进程。</p>:detailDevice.processes.map(p=><ProcessDetails key={p.pid} process={p} onCopy={text=>navigator.clipboard.writeText(text).then(()=>setNotice("已复制")).catch(()=>setNotice("复制失败，可手动选择文本复制"))}/>)}<button className="secondary wide" onClick={()=>toggle(detail.host,detail.device)}><Check size={15}/>{(selected[detail.host]||[]).includes(detail.device)?'取消选择此设备':'选择此设备'}</button></>}{check&&<div className={'check-result '+(check.status==='PASS'?'pass':'')}><h3><ShieldCheck size={18}/>检查结果：{check.status}</h3>{check.reasons.map((r,i)=><p key={i}>{r}</p>)}</div>}<div className="drawer-note">数据来自最近一次采集。进程不可见时会明确标记，检查结果不构成资源预留。</div></section></div>}
  </WorkspaceLayout>;
}

function SystemSummary({system,fresh}:{system?:SystemMetrics|null;fresh:boolean}){
  const cpu=system?.cpu_percent,memory=system?.memory;
  const percent=memory?memory.memory_used/memory.memory_total*100:null;
  return <div className={'system-summary '+(!fresh?'stale':'')} title="CPU 为 250ms 采样窗口；内存已用 = MemTotal − MemAvailable。均为远端 /proc 系统视角，容器限额可能不同。">
    <div><Cpu size={15}/><span>CPU</span><strong>{cpu==null?'无法读取':cpu.toFixed(1)+'%'}</strong><div className="system-meter"><i style={{width:(cpu??0)+'%'}}/></div><small>{system?.cpu_cores?system.cpu_cores+' 逻辑核':'核数未知'}</small></div>
    <div><Database size={15}/><span>内存</span><strong>{memory?gib(memory.memory_used)+' / '+gib(memory.memory_total)+' GiB':'无法读取'}</strong><div className="system-meter"><i style={{width:(percent??0)+'%'}}/></div><small>{percent==null?'—':percent.toFixed(1)+'%'}</small></div>
  </div>;
}

function ProcessDetails({process:p,onCopy}:{process:Proc;onCopy:(text:string)=>void}){
  const reason=(field:string)=>{
    if(p.detail_status==='process_changed')return '采集期间 PID 已被复用，请刷新';
    if(p.detail_status==='started_during_collection')return '进程在采集期间新启动，等待下次采集确认';
    if(p.detail_status==='not_visible_or_exited')return '进程已退出或当前 PID 命名空间不可见';
    return p.errors?.[field]==='permission_denied'?'权限不足，无法读取':p.errors?.[field]==='not_visible_or_exited'?'进程已退出或当前命名空间不可见':'未获取';
  };
  const field=(label:string,value:string|number|null|undefined,key:string)=>
    <div><dt>{label}</dt><dd>{value!=null&&value!==''?<><span>{value}</span>{(key==='cwd'||key==='executable')&&<button className="icon-button" aria-label={'复制 '+label+' PID '+p.pid} onClick={()=>onCopy(String(value))}><Copy size={12}/></button>}</>:<span className="missing-field">{reason(key)}</span>}</dd></div>;
  return <article className="process process-details"><div className="process-title"><Terminal size={16}/><strong>{p.name}</strong><Badge>PID {p.pid}</Badge></div>
    {['not_visible_or_exited','process_changed','started_during_collection'].includes(p.detail_status||'')?<p className="process-caution">{reason('identity')}</p>:null}
    <dl>{field('进程用户',p.user,'user')}{field('UID',p.uid,'user')}{p.effective_uid!=null&&p.effective_uid!==p.uid&&field('有效 UID',p.effective_uid,'user')}{field('父进程 PID',p.parent_pid,'user')}{field('设备显存',gib(p.memory_used)+' GiB','memory')}{field('工作目录',p.cwd,'cwd')}{field('可执行文件',p.executable,'executable')}</dl>
    <div className="command-heading"><span>启动命令</span>{p.command&&<button className="text-button" onClick={()=>onCopy(p.command!)}><Copy size={12}/>复制</button>}</div>
    <pre className={!p.command?'missing-field':''}>{p.command||reason('command')}</pre>
    {p.command_truncated&&<p className="process-caution">命令过长，仅显示完整参数的前段。</p>}
    <small className="process-note">{p.detail_source==='sudo'?'已使用 sudo 补齐详情。':'使用 SSH 当前账号读取。'}用户按进程 UID 解析；目录与可执行文件来自远端 /proc。常见密码、Token 参数已脱敏。</small>
  </article>;
}


function SudoModal({host,close,updated}:{host:Host;close:()=>void;updated:()=>Promise<void>}){
  const [settings,setSettings]=useState<SudoSettings|undefined>(host.sudo);
  const [enabled,setEnabled]=useState(host.sudo?.enabled??false),[password,setPassword]=useState('');
  const [remember,setRemember]=useState(host.sudo?.password_saved??false),[install,setInstall]=useState(false);
  const [pending,setPending]=useState(false),[ready,setReady]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{let active=true;api('/hosts/'+host.id+'/sudo').then(value=>{if(active){setSettings(value);setEnabled(value.enabled);setRemember(value.password_saved);setReady(true)}}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[host.id]);
  const save=async(e:React.FormEvent)=>{
    e.preventDefault();setPending(true);setError('');setMessage('');
    try{const value=await api('/hosts/'+host.id+'/sudo','POST',{enabled,password:password||null,remember,install_helper:install});setSettings(value);setRemember(value.password_saved);setInstall(false);await updated();close()}
    catch(e){setError(e instanceof Error?e.message:String(e))}finally{setPassword('');setPending(false)}
  };
  const forget=async()=>{
    setPending(true);setError('');setMessage('');setPassword('');
    try{const value=await api('/hosts/'+host.id+'/sudo','DELETE');setSettings(value);setRemember(false);setMessage('已删除系统中保存的密码，并清除本次运行中的密码。服务器已有的 sudo 免密权限或授权缓存仍按服务器策略生效。');await updated()}
    catch(e){setError(e instanceof Error?e.message:String(e))}finally{setPending(false)}
  };
  return <div className="modal-shade"><section role="dialog" aria-modal="true" aria-labelledby="sudo-title" className="modal sudo-modal">
    <div className="modal-header"><div><div className="eyebrow">MACHINE / PERMISSIONS</div><h2 id="sudo-title">sudo 进程详情</h2><p className="subtle">{host.target} · 仅对这台机器生效</p></div><button className="icon-button" aria-label="关闭 sudo 设置" disabled={pending} onClick={close}><X size={20}/></button></div>
    <form onSubmit={save}>
      <label className="sudo-option"><input type="checkbox" checked={enabled} disabled={!ready||pending} onChange={e=>setEnabled(e.target.checked)}/><div><strong>启用 sudo 补齐进程详情</strong><p>读取占卡进程的用户、工作目录、启动命令和可执行文件。GPU、NPU、CPU 和内存监控保持普通账号采集。</p></div></label>
      <div className="sudo-state"><ShieldCheck size={16}/><div><strong>{settings?.message||'正在读取设置…'}</strong><small>{settings?.password_saved?'密码已保存在 系统安全存储':settings?.password_in_memory?'密码仅保留到软件退出':'未保存 sudo 密码'}</small></div></div>
      <label className="form-label">此机器的 sudo 密码 <small>已保存密码或具备 sudo 免密权限时可留空</small><input aria-label="sudo 密码" type="password" autoComplete="off" maxLength={512} disabled={!enabled||pending||!ready} value={password} onChange={e=>setPassword(e.target.value)} placeholder={settings?.password_saved?'留空使用已保存密码':'输入当前 SSH 账号的 sudo 密码'}/></label>
      <label className="checkbox-label sudo-remember"><input type="checkbox" checked={remember} disabled={!enabled||pending||!ready||!settings?.can_remember} onChange={e=>setRemember(e.target.checked)}/>记住 sudo 密码（系统安全存储）</label>
      <p className="subtle sudo-hint">不勾选时，输入的密码只保留到本地服务退出。取消勾选后保存，也会删除原来保存的密码。</p>
      <label className="sudo-option sudo-install"><input type="checkbox" checked={install} disabled={!enabled||pending||!ready} onChange={e=>setInstall(e.target.checked)}/><div><strong>安装或更新固定的只读采集程序</strong><p>首次启用时勾选。保存后会在远端安装 root 所有的进程采集文件，不修改 sudo 授权规则。后续采集只调用此程序。</p></div></label>
      <div className="privacy-note"><ShieldCheck size={14}/>密码不会写入配置文件、浏览器存储或日志；普通账号仍需拥有服务器授予的 sudo 权限。</div>
      {error&&<div role="alert" className="connection-error">{error}</div>}{message&&<p role="status" className="sudo-success">{message}</p>}
      <div className="modal-footer"><button type="button" className="text-button sudo-forget" disabled={pending||!ready||(!settings?.password_saved&&!settings?.password_in_memory)} onClick={forget}><Trash2 size={14}/>删除保存的密码</button><button className="primary" disabled={pending||!ready}>{pending?<LoaderCircle size={16} className="spin"/>:<ShieldCheck size={16}/ >}{pending?'正在处理…':enabled?'保存并验证':'保存设置'}</button></div>
    </form>
  </section></div>;
}

function AddMachine({close,connected,imported}:{close:()=>void;connected:(message:string,hostId?:string)=>void;imported:(ids:string[])=>void}){
  const [bulk,setBulk]=useState(false);
  const [manual,setManual]=useState(false),[aliases,setAliases]=useState<string[]>([]),[query,setQuery]=useState(''),[target,setTarget]=useState(''),[user,setUser]=useState(''),[port,setPort]=useState(22),[password,setPassword]=useState(''),[provision,setProvision]=useState(false),[rememberPassword,setRememberPassword]=useState(false),[canRemember,setCanRemember]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[configPath,setConfigPath]=useState('');
  useEffect(()=>{api('/config-hosts').then(data=>{setAliases(data.aliases);setConfigPath(data.path);setCanRemember(data.can_remember_ssh_password===true)}).catch(e=>setError(e.message))},[]);
  const connect=async(e:React.FormEvent)=>{e.preventDefault();setLoading(true);setError('');try{const result=await api('/connect','POST',{target,user:user||null,port:manual?port:null,manual,password:password||null,provision,remember_password:rememberPassword});setPassword('');connected(result.message,result.host_id)}catch(e){setPassword('');setError(e instanceof Error?e.message:String(e))}finally{setLoading(false)}};
  return <div className="modal-shade"><section role="dialog" aria-modal="true" aria-labelledby="add-title" className={'modal '+(bulk?'import-modal':'')}><div className="modal-header"><div><div className="eyebrow">CONNECT / SSH</div><h2 id="add-title">添加机器</h2></div><button className="icon-button" disabled={loading} aria-label="关闭添加机器" onClick={close}><X size={20}/></button></div><div className="tabs"><button type="button" disabled={loading} className={!manual&&!bulk?'selected':''} onClick={()=>{setBulk(false);setManual(false);setTarget('');setError('')}}>从 SSH 配置选择</button><button type="button" disabled={loading} className={manual&&!bulk?'selected':''} onClick={()=>{setBulk(false);setManual(true);setTarget('');setError('')}}>手动添加</button><button type="button" disabled={loading} className={bulk?'selected':''} onClick={()=>{setBulk(true);setPassword('');setError('')}}>Excel 批量导入</button></div>{bulk?<React.Suspense fallback={<p className="subtle">正在加载…</p>}><ServerImport onChanged={imported}/></React.Suspense>:<form onSubmit={connect}>
    {!manual?<><p className="config-path"><Terminal size={13}/>{configPath||'读取 ~/.ssh/config…'}</p><div className="search-input"><Search size={16}/><input aria-label="搜索 SSH 机器" placeholder="搜索已保存的机器…" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="alias-list">{aliases.filter(a=>a.toLowerCase().includes(query.toLowerCase())).map(a=><button type="button" className={target===a?'selected':''} key={a} onClick={()=>setTarget(a)}><Server size={15}/><span>{a}</span>{target===a?<Check size={15}/>:<ChevronRight size={14}/>}</button>)}{aliases.length===0&&<p className="subtle">未找到机器，可切换到手动添加。</p>}</div></>:<><label className="form-label">主机地址<input required placeholder="例如 192.168.1.10" value={target} onChange={e=>setTarget(e.target.value.trim())}/></label><label className="form-label">SSH 端口<input required type="number" min="1" max="65535" value={port} onChange={e=>setPort(+e.target.value)}/></label></>}
    <div className="form-row"><label className="form-label">用户名 {!manual&&<small>留空使用 SSH 配置</small>}<input required={manual} autoComplete="username" value={user} onChange={e=>setUser(e.target.value.trim())} placeholder={manual?'登录用户名':'使用已有配置'}/></label><label className="form-label">密码 <small>已有免密可留空</small><input type="password" autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} placeholder={rememberPassword?'连接成功后保存到系统凭据管理器':'仅在本次连接时使用'}/></label></div>
    <label className="provision-option"><input type="checkbox" checked={provision} onChange={e=>setProvision(e.target.checked)}/><div><strong>登录后自动配置免密连接</strong><p>生成本机专用密钥，向远端追加公钥，再验证无密码登录。需要提供本次登录密码。</p></div><ShieldCheck size={20}/></label><label className="checkbox-label"><input aria-label="记住 SSH 登录密码" type="checkbox" checked={rememberPassword} disabled={!canRemember||loading} onChange={e=>setRememberPassword(e.target.checked)}/>记住 SSH 登录密码，供 MCP 工具 读取</label><div className="privacy-note"><ShieldCheck size={14}/>{rememberPassword?'登录成功后保存到当前用户的系统凭据管理器，可在机器的 SSH 密码设置中删除。':'未勾选记住时不保存 SSH 密码；免密配置不覆盖已有公钥。'}</div>
    {error&&<div role="alert" className="connection-error">{error}</div>}<div className="modal-footer"><span>{target?<><i className="dot"/>{target}</>:'选择一台机器开始'}</span><button className="primary" disabled={loading||!target||((provision||rememberPassword)&&!password)}>{loading?<LoaderCircle size={16} className="spin"/>:<ArrowUpRight size={16}/ >}{loading?'正在连接…':'连接机器'}</button></div></form>}</section></div>
}
createRoot(document.getElementById('root')!).render(<App/>);
