import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Activity, ArrowDownLeft, ArrowUpRight, Bell, CalendarClock, Check, ChevronRight, CircleHelp, Copy, Cpu, Database, LayoutGrid, LoaderCircle, Monitor, Plus, Palette, Radio, RefreshCw, Search, Server, Settings, ShieldCheck, Terminal, Trash2, X, Zap} from 'lucide-react';
import './style.css';
import './themes.css';
import './journey.css';
import {JourneyArt} from './JourneyArt';
import {PrecisionCompare} from './PrecisionCompare';
import type {TerminalRequest} from './TerminalDock';
import {pageFromHash,hostSelectionPage,type Page} from './navigation';
const TerminalDock=React.lazy(()=>import('./TerminalDock').then(module=>({default:module.TerminalDock})));
import {THEMES, browserStorage, loadPreferences, savePreferences, scopedHosts, toggleHost} from './preferences';
import {shouldNotify} from './notifications';
import {Reservations,ReservationDialog,type ReservationDraft} from './ReservationPanel';
import type {Reservation} from './reservations';
import {MailSettingsPage} from './MailSettingsPage';
const bootPreferences=loadPreferences(browserStorage());
document.documentElement.dataset.theme=bootPreferences.theme;

type Proc = {pid:number; name:string; user:string|null; memory_used:number|null; uid?:number|null; effective_uid?:number|null; parent_pid?:number|null; cwd?:string|null; executable?:string|null; command?:string|null; command_truncated?:boolean; identity_verified?:boolean; detail_status?:string; detail_source?:string; errors?:Record<string,string>};
type Device = {id:string; display_id?:string; card_id?:string; chip_id?:string; physical_id?:string|null; kind:string; name:string; memory_total:number; memory_used:number; memory_free:number; utilization:number|null; temperature:number|null; processes:Proc[]; processes_known:boolean; health:string};
type SystemMetrics = {cpu_percent:number|null;cpu_cores:number|null;memory:{memory_total:number;memory_used:number;memory_available:number}|null};
type SudoSettings = {enabled:boolean;password_saved:boolean;password_in_memory:boolean;can_remember:boolean;status:string;message:string};
type Host = {id:string; target:string; user:string|null; port:number|null; manual:boolean; auth:string; sudo?:SudoSettings; snapshot:{status:string; fresh:boolean; collected_at:number|null; error?:string; error_stage?:string; system?:SystemMetrics|null; devices:Device[]}};
type Rule = {id:string; host_id:string; devices:string[]; minimum_gib:number; port:number; status?:string};
type Event = {id:number; created:number; host:string; message:string; notify?:boolean};
type State = {hosts:Host[]; rules:Rule[]; reservations:Reservation[]; events:Event[]; server_time:number};
const gib=(n:number|null|undefined)=>n==null?'—':(n/1024**3).toFixed(1);
const clock=(n:number)=>new Date(n*1000).toLocaleTimeString('zh-CN',{hour12:false});
const displayId=(d:Device|undefined)=>d?.display_id??d?.id??'已失效';
function machineSummary(ds:Device[]){
  if(!ds.length)return '等待设备信息';
  const npus=ds.filter(d=>d.kind==='NPU'),cards=new Set(npus.map(d=>d.card_id??d.id));
  return npus.length>cards.size?`${cards.size} 张 NPU 卡 / ${npus.length} 个设备 · ${npus[0].name}`:`${ds.length} × ${ds[0].name}`;
}
async function api(path:string,method='GET',body?:unknown){
  const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'操作失败');
  return data;
}
function isEligible(d:Device,min:number,clear:boolean){return d.memory_free>=min*1024**3&&(!clear||(d.processes_known&&d.processes.length===0))&&d.health!=='Alarm'}
function Badge({children,tone='muted'}:{children:React.ReactNode;tone?:string}){return <span className={'badge '+tone}>{children}</span>}

function App(){
  const [state,setState]=useState<State>({hosts:[],rules:[],reservations:[],events:[],server_time:0});
  const [reservationDraft,setReservationDraft]=useState<ReservationDraft|null>(null);
  const [preferences,setPreferences]=useState(()=>loadPreferences(browserStorage()));
  const [hostSearch,setHostSearch]=useState('');
  const [sudoHost,setSudoHost]=useState<Host|null>(null);
  const [terminalRequest,setTerminalRequest]=useState<TerminalRequest|null>(null);
  const [precisionMounted,setPrecisionMounted]=useState(()=>pageFromHash(location.hash)==='precision');
  const [page,setPage]=useState<Page>(()=>pageFromHash(location.hash)),[filter,setFilter]=useState('全部'),[count,setCount]=useState(1),[minimum,setMinimum]=useState(16),[clear,setClear]=useState(true);
  const [adding,setAdding]=useState(false),[detail,setDetail]=useState<{host:string;device:string}|null>(null),[selected,setSelected]=useState<Record<string,string[]>>({});
  const [notice,setNotice]=useState(''),[error,setError]=useState(''),[notify,setNotify]=useState(false),[busy,setBusy]=useState(''),[port,setPort]=useState(29500),[check,setCheck]=useState<{status:string;reasons:string[]}|null>(null);
  const lastEvent=useRef<number|null>(null),notifyRef=useRef(false),storageWarning=useRef(false),themeMenu=useRef<HTMLDetailsElement>(null),terminalMenu=useRef<HTMLDetailsElement>(null),mobileHosts=useRef<HTMLDetailsElement>(null);
  const navigate=(next:Page)=>{
    setPage(next);if(next==='precision')setPrecisionMounted(true);
    setDetail(null);setCheck(null);
    if(themeMenu.current)themeMenu.current.open=false;if(terminalMenu.current)terminalMenu.current.open=false;
    if(location.hash!=='#'+next&&!(next==='overview'&&!location.hash))location.hash=next;
    if(next!==page)window.scrollTo({top:0});
  };
  useEffect(()=>{
    const sync=()=>{const next=pageFromHash(location.hash);setPage(next);if(next==='precision')setPrecisionMounted(true);setDetail(null);setCheck(null);window.scrollTo({top:0})};
    window.addEventListener('hashchange',sync);return()=>window.removeEventListener('hashchange',sync);
  },[]);
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{for(const menu of [themeMenu.current,terminalMenu.current])if(menu?.open&&!menu.contains(event.target as Node))menu.open=false};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')for(const menu of [themeMenu.current,terminalMenu.current])if(menu)menu.open=false};
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)};
  },[]);
  const load=async()=>{
    try{
      const next:State=await api('/state');setState({...next,reservations:next.reservations??[]});setError('');
      if(lastEvent.current!==null&&notifyRef.current&&'Notification' in window&&Notification.permission==='granted')
        for(const event of [...next.events].reverse())if(event.id>lastEvent.current&&shouldNotify(event))new Notification('Infra Workbench',{body:event.message,tag:String(event.id)});
      lastEvent.current=next.events[0]?.id??lastEvent.current??0;
    }catch{setError('本地服务未连接，请检查启动窗口。')}
  };
  useEffect(()=>{load();const timer=setInterval(load,2000);return()=>clearInterval(timer)},[]);
  useEffect(()=>{
    document.documentElement.dataset.theme=preferences.theme;
    if(!savePreferences(browserStorage(),preferences)&&!storageWarning.current){storageWarning.current=true;setNotice('浏览器不允许保存偏好，主题与机器选择在关闭页面后将无法恢复。')}
  },[preferences]);
  useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),7000);return()=>clearTimeout(t)},[notice]);
  const act=async(key:string,fn:()=>Promise<unknown>)=>{setBusy(key);try{await fn();await load()}catch(e){setNotice(e instanceof Error?e.message:String(e))}finally{setBusy('')}};
  const enableNotifications=async()=>{
    if(!('Notification'in window)){setNotice('此浏览器不支持系统通知，事件仍显示在页面中。');return}
    const permission=await Notification.requestPermission();notifyRef.current=permission==='granted';setNotify(notifyRef.current);
    setNotice(notifyRef.current?'浏览器通知已开启；请保持页面和本地服务运行。':'浏览器通知未开启，事件仍显示在页面中。');
  };
  const scope=scopedHosts(state.hosts,preferences.hostIds);
  const devices=scope.flatMap(h=>h.snapshot.devices),online=scope.filter(h=>h.snapshot.fresh).length;
  const matches=(h:Host)=>h.snapshot.fresh?h.snapshot.devices.filter(d=>(filter==='全部'||d.kind===filter)&&isEligible(d,minimum,clear)):[];
  const candidates=scope.filter(h=>matches(h).length>=count);
  const shown=scope.filter(h=>filter==='全部'||h.snapshot.devices.some(d=>d.kind===filter)||!h.snapshot.devices.length);
  const detailHost=state.hosts.find(h=>h.id===detail?.host),detailDevice=detailHost?.snapshot.devices.find(d=>d.id===detail?.device);
  const toggle=(h:string,d:string)=>setSelected(old=>({...old,[h]:(old[h]||[]).includes(d)?old[h].filter(i=>i!==d):[...(old[h]||[]),d]}));
  const selectHosts=(ids:string[]|null,direct=false)=>{
    setPreferences(old=>({...old,hostIds:ids}));
    if(direct){setFilter('全部');if(mobileHosts.current)mobileHosts.current.open=false;window.scrollTo({top:0})}
    navigate(hostSelectionPage(page,direct));
  };
  const openTerminal=(host:Host)=>{if(terminalMenu.current)terminalMenu.current.open=false;setTerminalRequest({id:crypto.randomUUID(),host})};

  const resourceBody=(h:Host)=>({host_id:h.id,devices:selected[h.id]||[],minimum_gib:minimum,port});
  const inspect=(host:Host,d:Device)=>{setDetail({host:host.id,device:d.id});setCheck(null)};
  const pageTitle=page==='overview'?'算力总览':page==='connections'?'机器连接':page==='precision'?'训练精度对比':page==='reservations'?'卡预约':page==='settings'?'设置':'资源监控';
  useEffect(()=>{document.title=pageTitle+' · Infra Workbench'},[pageTitle]);
  const hostList=<div className="host-picker">
    <div className="host-picker-heading"><span>机器列表</span><span>{scope.length} / {state.hosts.length}</span></div>
    <div className="host-search"><Search size={14}/><input aria-label="搜索机器列表" placeholder="搜索机器…" value={hostSearch} onChange={e=>setHostSearch(e.target.value)}/></div>
    <div className="host-picker-actions"><button onClick={()=>selectHosts(null)} className={preferences.hostIds===null?'selected':''}>全部</button><button onClick={()=>selectHosts([])}>清空</button><span>点击名称查看设备，勾选多选</span></div>
    <div className="host-picker-items">{state.hosts.filter(h=>h.target.toLowerCase().includes(hostSearch.toLowerCase())).map(h=>{
      const checked=preferences.hostIds===null||preferences.hostIds.includes(h.id);
      return <div className={'host-picker-row '+(checked?'selected':'')} key={h.id}>
        <input type="checkbox" aria-label={'显示机器 '+h.target} checked={checked} onChange={()=>selectHosts(toggleHost(preferences.hostIds,h.id,state.hosts.map(h=>h.id)))}/>
        <button aria-label={'只看机器 '+h.target} title="查看此机器的设备" onClick={()=>selectHosts([h.id],true)}><span className={'host-dot '+(h.snapshot.fresh?'online':'')}/><span><strong>{h.target}</strong><small>{h.snapshot.devices.length} 个设备 · {h.snapshot.fresh?'在线':h.snapshot.status==='error'?'采集失败':'等待采集'}</small></span><ChevronRight size={13}/></button>
      </div>})}
      {state.hosts.length===0&&<p className="subtle">添加机器后会出现在这里。</p>}
      {state.hosts.length>0&&!state.hosts.some(h=>h.target.toLowerCase().includes(hostSearch.toLowerCase()))&&<p className="subtle">没有匹配的机器。</p>}
    </div><small className="saved-hint"><Check size={11}/>自动记住本次选择</small>
  </div>;
  return <div className="shell">
    <aside className="sidebar"><div className="brand"><span className="brand-icon"><Cpu size={23}/></span><div>Infra<span>WORKBENCH</span></div></div>
      <div className="workspace"><span className="avatar">本</span><div>本地工作空间<small>Personal workspace</small></div></div>
      <div className="nav-label">工作台</div><nav>{[["overview","算力总览",LayoutGrid],["connections","机器连接",Server],["watch","资源监控",Radio],["reservations","卡预约",CalendarClock],["precision","精度对比",Activity],["settings","设置",Settings]].map(([key,label,Icon])=><button key={String(key)} className={page===key?'active':''} aria-current={page===key?'page':undefined} onClick={()=>navigate(String(key) as Page)}><Icon size={18}/>{String(label)}{key==='connections'&&<span className="nav-count">{state.hosts.length}</span>}{key==='watch'&&state.rules.length>0&&<span className="nav-count">{state.rules.length}</span>}{key==='reservations'&&state.reservations.some(r=>r.status!=='ready')&&<span className="nav-count">{state.reservations.filter(r=>r.status!=='ready').length}</span>}</button>)}</nav>
      <div className="sidebar-hosts">{hostList}</div>
      <div className="sidebar-bottom"><div className="agent"><i/>本地服务{error?'未连接':'已连接'}<small>SSH · 无需远端 Agent</small></div><div className="version">Infra Workbench <span>v0.1</span></div></div>
    </aside>
    <main><header><div className="breadcrumb">工作空间 <ChevronRight size={13}/>{pageTitle}</div>
      <div className="header-tools"><span className="live"><i/>10s 实时采集</span>
        <details className="theme-menu" ref={themeMenu}><summary><Palette size={16}/><span>主题</span></summary><div className="theme-options"><h3>选择界面主题</h3><p>主题偏好自动保存在本机</p>{THEMES.map(t=><button key={t.id} aria-pressed={preferences.theme===t.id} onClick={()=>{setPreferences(old=>({...old,theme:t.id}));if(themeMenu.current)themeMenu.current.open=false}}>
          <span className="theme-swatches">{t.swatches.map(color=><i key={color} style={{background:color}}/>)}</span><span><strong>{t.name}</strong><small>{t.mode==='light'?'亮色':'暗色'} · {t.description}</small></span>{preferences.theme===t.id&&<Check size={15}/>}</button>)}</div></details>
        {scope.length===1||!state.hosts.length?<button className="ssh-open" title={scope[0]?'连接 '+scope[0].target:'请先添加机器'} onClick={()=>{if(scope[0])openTerminal(scope[0]);else setNotice('请先添加机器')}}><Terminal size={15}/><span>SSH 终端</span></button>:<details className="global-ssh-menu" ref={terminalMenu}><summary className="ssh-open"><Terminal size={15}/><span>SSH 终端</span><ChevronRight size={12}/></summary><div className="global-ssh-targets" role="menu" aria-label="选择 SSH 目标机器"><strong>选择要连接的机器</strong><small>{scope.length?'当前选择了多台机器，请指定连接目标':'未选择机器，请从已连接机器中选择'}</small>{(scope.length?scope:state.hosts).map(host=><button key={host.id} role="menuitem" onClick={()=>openTerminal(host)}><Server size={15}/><span>{host.target}<small>{host.user||'使用 SSH 配置账号'}</small></span><ChevronRight size={13}/></button>)}</div></details>}<button className={'icon-button '+(notify?'teal':'')} aria-label="开启浏览器通知" onClick={enableNotifications}><Bell size={18}/></button><span className="avatar small">本</span>
      </div></header>
    {preferences.theme==='frieren'&&<JourneyArt/>}
    <div className="content"><div className="page-heading"><div><div className="eyebrow">COMPUTE / {page==='precision'?'PRECISION COMPARE':page==='overview'?'OVERVIEW':page==='connections'?'CONNECTIONS':page==='reservations'?'RESERVATIONS':page==='settings'?'SETTINGS':'RESOURCE GUARD'}</div><h1>{pageTitle}<span className="heading-dot"/></h1><p>{page==='precision'?'跨机器读取训练日志，自动提取指标并按真实步数对齐。':page==='watch'?'关注准备使用的设备，在资源变化时收到提醒。':page==='reservations'?'预约指定设备，等它们连续空闲后收到提醒。':page==='settings'?'管理邮件通知与发件邮箱。':`正在查看 ${scope.length} 台机器 · 从左侧列表选择你关注的资源`}</p></div><button className="primary" onClick={()=>setAdding(true)}><Plus size={17}/>添加机器</button></div>
    <details className="mobile-hosts" ref={mobileHosts}><summary><Server size={15}/>选择机器 · {scope.length} / {state.hosts.length}</summary>{hostList}</details>
    {error&&<div className="error-banner">{error}</div>}
    {precisionMounted&&<div className="precision-cache" hidden={page!=='precision'}><PrecisionCompare hosts={state.hosts}/></div>}
    {page==='overview'&&<><div className="stats"><div><span>所选机器<Server size={16}/></span><strong>{online}<small>/ {scope.length}</small></strong><p><i className="dot"/>在线 / 已选择</p></div><div><span>加速设备<Cpu size={16}/></span><strong>{devices.length}<small>个设备</small></strong><p>{devices.filter(d=>d.kind==='NPU').length} NPU <b>·</b> {devices.filter(d=>d.kind==='GPU').length} GPU</p></div><div><span>满足筛选条件<ShieldCheck size={16}/></span><strong className="teal">{candidates.length}<small>台机器</small></strong><p>至少 {count} 个设备 · 每个 ≥ {minimum} GiB</p></div><div><span>监控中的规则<Radio size={16}/></span><strong>{state.rules.length}<small>条</small></strong><p>占用变化与资源恢复提醒</p></div></div>
      <section className="finder"><div className="finder-label"><Search size={18}/><div>寻找训练资源<small>仅在所选机器内匹配</small></div></div><label>需要设备数<select aria-label="需要设备数" value={count} onChange={e=>setCount(+e.target.value)}>{Array.from({length:Math.max(8,count,...scope.map(h=>h.snapshot.devices.length))},(_,i)=>i+1).map(i=><option key={i} value={i}>{i} 个</option>)}</select></label><label>剩余显存<div className="input-unit"><input aria-label="每个设备剩余显存" type="number" min="0" max="100000" value={minimum} onChange={e=>setMinimum(Math.max(0,+e.target.value))}/><span>GiB</span></div></label><label className="checkbox-label"><input type="checkbox" checked={clear} onChange={e=>setClear(e.target.checked)}/>无可见计算进程</label><div className="match-count"><strong>{candidates.length}</strong> 台匹配<ArrowUpRight size={17}/></div></section>
    </>}
    {(page==='overview'||page==='connections')&&<div className="two-columns"><div className="machines"><div className="section-heading"><h2>设备详情<span>{shown.length} 台机器</span></h2><div className="segmented">{['全部','NPU','GPU'].map(f=><button className={filter===f?'chosen':''} key={f} onClick={()=>setFilter(f)}>{f}</button>)}</div></div>
      {shown.length===0&&<div className="empty"><Server size={32}/><h3>{state.hosts.length===0?'连接第一台机器':scope.length===0?'选择要查看的机器':'没有符合设备类型的机器'}</h3><p>{state.hosts.length===0?'从本机 SSH 配置选择，或输入主机和账号密码。':'在机器列表中点击名称单选，或勾选多台机器。'}</p>{state.hosts.length===0?<button className="primary" onClick={()=>setAdding(true)}><Plus size={16}/>添加机器</button>:<button className="secondary" onClick={()=>{selectHosts(null);setFilter('全部')}}>显示全部机器</button>}</div>}
      {shown.map(host=>{const snapshot=host.snapshot,ids=selected[host.id]||[];return <section className="machine" key={host.id} aria-label={'机器详情 '+host.target}>
        <div className="machine-heading"><span className="machine-icon"><Server size={20}/></span><div className="machine-name"><h3>{host.target}<Badge tone={snapshot.fresh?'green':'amber'}>{snapshot.fresh?'在线':snapshot.status==='error'?'采集失败':snapshot.status==='connecting'?'连接中':'数据过期'}</Badge></h3><p>{machineSummary(snapshot.devices)} <span>·</span> SSH {host.auth==='password_session'?'密码会话':'免密连接'}</p></div><button className="ssh-open" aria-label={'打开 '+host.target+' 终端'} onClick={()=>setTerminalRequest({id:crypto.randomUUID(),host})}><Terminal size={15}/><span>终端</span></button><button className={'sudo-button '+(host.sudo?.enabled?'enabled':'')} title={host.sudo?.message||'设置 sudo 进程详情'} aria-label={host.target+' sudo 设置'} onClick={()=>setSudoHost(host)}><ShieldCheck size={15}/><span>sudo</span></button><button className="icon-button" aria-label={'刷新 '+host.target} disabled={busy===host.id} onClick={()=>act(host.id,()=>api('/hosts/'+host.id+'/refresh','POST'))}><RefreshCw size={16} className={busy===host.id?'spin':''}/></button><button className="icon-button" aria-label={'移除 '+host.target} onClick={()=>act('remove',()=>api('/hosts/'+host.id,'DELETE'))}><Trash2 size={15}/></button></div>
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
        {ids.length>0&&<div className="selection-bar"><span>已选设备 {ids.map(id=>displayId(snapshot.devices.find(d=>d.id===id))).join(', ')}</span><label>端口<input type="number" min="1" max="65535" aria-label="训练端口" value={port} onChange={e=>setPort(+e.target.value)}/></label><button className="secondary" disabled={!!busy} onClick={()=>act('check',async()=>{setCheck(await api('/preflight','POST',resourceBody(host)));setDetail({host:host.id,device:ids[0]})})}>训练前检查</button><button className="primary compact" disabled={!!busy} onClick={()=>act('rule',async()=>{await api('/rules','POST',resourceBody(host));setNotice('监控已添加，连续两次检测到变化时提醒。')})}><Radio size={14}/>监控所选</button><button className="primary compact" disabled={!!busy||!snapshot.fresh} onClick={()=>setReservationDraft({hostId:host.id,devices:ids,minimum})}><CalendarClock size={14}/>预约所选</button></div>}
      </section>})}
      <div className="footnote"><CircleHelp size={14}/>低利用率不代表空闲。筛选结果反映资源指标，不代表资源授权或预留。</div>
    </div><aside className="event-column"><EventPanel events={state.events}/><div className="data-source"><Database size={14}/>真实 SSH 采集<span>本地存储</span></div></aside></div>}
    {page==='settings'&&<MailSettingsPage/>}
    {page==='reservations'&&<Reservations items={state.reservations} create={()=>setReservationDraft({})} update={async(id,wait_seconds)=>{await api('/reservations/'+id,'PATCH',{wait_seconds});await load()}} remove={async(id)=>{await api('/reservations/'+id,'DELETE');await load()}} enableNotifications={enableNotifications} notify={notify}/>}
    {page==='watch'&&<><div className="watch-heading"><h2>监控规则 <Badge>{state.rules.length}</Badge></h2><button className="secondary" onClick={enableNotifications}><Bell size={15}/>{notify?'通知已开启':'开启浏览器通知'}</button></div><p className="subtle">从设备列表勾选后点击“监控所选”。规则持续监控，不受当前查看的机器选择影响。</p>{state.rules.length===0&&<div className="empty"><Radio size={32}/><h3>还没有监控规则</h3><button className="secondary" onClick={()=>navigate('overview')}>去选择设备</button></div>}{state.rules.map(r=><div className="rule-row" key={r.id}><Radio size={20}/><div><h3>{state.hosts.find(h=>h.id===r.host_id)?.target}</h3><p>设备 {r.devices.map(id=>id.replace('phy:','Phy-ID ')).join(', ')} · 每设备 ≥ {r.minimum_gib} GiB · 端口 {r.port}</p></div><Badge tone={r.status==='active'?'green':'amber'}>{r.status==='needs_selection'?'需重新选设备':r.status==='active'?'监控中':'等待有效采集'}</Badge><button className="icon-button" aria-label="删除监控规则" onClick={()=>act('rule',()=>api('/rules/'+r.id,'DELETE'))}><Trash2 size={16}/></button></div>)}<EventPanel events={state.events}/></>}
    <footer className="page-footer"><span><ShieldCheck size={13}/>私钥留在本机 · sudo 密码可选存入系统凭据管理器</span><span>LOCAL WORKSPACE / {new Date().getFullYear()}</span></footer></div></main>
    <React.Suspense fallback={null}>{terminalRequest&&<TerminalDock request={terminalRequest} hosts={state.hosts}/>}</React.Suspense>
    {notice&&<div role="status" className="toast"><Check size={17}/>{notice}<button className="icon-button" aria-label="关闭提示" onClick={()=>setNotice('')}><X size={15}/></button></div>}
    {adding&&<AddMachine close={()=>setAdding(false)} connected={async(message,hostId)=>{if(hostId)setPreferences(old=>({...old,hostIds:old.hostIds===null?null:[...new Set([...old.hostIds,hostId])]}));setNotice(message);setAdding(false);await load()}}/>}
    {reservationDraft&&<ReservationDialog hosts={state.hosts} draft={reservationDraft} close={()=>setReservationDraft(null)} save={async(body)=>{await api('/reservations','POST',body);await load();setNotice('预约已保存；所选设备连续空闲后会提醒一次。');navigate('reservations')}}/>}
    {sudoHost&&<SudoModal key={sudoHost.id} host={sudoHost} close={()=>setSudoHost(null)} updated={async()=>{await load()}}/>}
    {detail&&<div className="drawer-shade" onClick={()=>{setDetail(null);setCheck(null)}}><section className="drawer" onClick={e=>e.stopPropagation()}><div className="drawer-heading"><div className="eyebrow">DEVICE INSPECTOR</div><button className="icon-button" aria-label="关闭设备详情" onClick={()=>{setDetail(null);setCheck(null)}}><X size={20}/></button></div><h2>{detailHost?.target}</h2><p className="subtle">{detailDevice?.kind} {detailDevice?displayId(detailDevice):''} · {detailDevice?.name}{detailDevice?.physical_id!=null&&` · 卡 ${detailDevice.card_id} / 芯片 ${detailDevice.chip_id}`}</p>{detailDevice&&<><div className="detail-metrics"><div>剩余显存<strong>{gib(detailDevice.memory_free)} <small>GiB</small></strong></div><div>计算利用率<strong>{detailDevice.utilization??'—'}<small>%</small></strong></div></div><h3>计算进程 <Badge>{detailDevice.processes.length}</Badge></h3>{!detailDevice.processes_known?<div className="error-banner">进程信息无法完整读取，不能确认空闲。</div>:detailDevice.processes.length===0?<p className="subtle">采集工具未报告可见计算进程。</p>:detailDevice.processes.map(p=><ProcessDetails key={p.pid} process={p} onCopy={text=>navigator.clipboard.writeText(text).then(()=>setNotice("已复制")).catch(()=>setNotice("复制失败，可手动选择文本复制"))}/>)}<button className="secondary wide" onClick={()=>toggle(detail.host,detail.device)}><Check size={15}/>{(selected[detail.host]||[]).includes(detail.device)?'取消选择此设备':'选择此设备'}</button></>}{check&&<div className={'check-result '+(check.status==='PASS'?'pass':'')}><h3><ShieldCheck size={18}/>检查结果：{check.status}</h3>{check.reasons.map((r,i)=><p key={i}>{r}</p>)}</div>}<div className="drawer-note">数据来自最近一次采集。进程不可见时会明确标记，检查结果不构成资源预留。</div></section></div>}
  </div>;
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

function EventPanel({events}:{events:Event[]}){return <section className="events"><div className="section-heading"><h2><Activity size={16}/>最近事件</h2><Badge>7 天</Badge></div>{events.length===0?<div className="events-empty"><div><Check size={18}/></div><p>暂无资源变化</p><small>添加监控后，变化会记录在这里。</small></div>:events.slice(0,20).map(e=><div className="event" key={e.id}><span className="event-dot"/><div><p>{e.message}</p><small>{new Date(e.created*1000).toLocaleDateString('zh-CN')} · {clock(e.created)}</small></div></div>)}</section>}

function SudoModal({host,close,updated}:{host:Host;close:()=>void;updated:()=>Promise<void>}){
  const [settings,setSettings]=useState<SudoSettings|undefined>(host.sudo);
  const [enabled,setEnabled]=useState(host.sudo?.enabled??false),[password,setPassword]=useState('');
  const [remember,setRemember]=useState(host.sudo?.password_saved??false),[install,setInstall]=useState(false);
  const [pending,setPending]=useState(false),[ready,setReady]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{let active=true;api('/hosts/'+host.id+'/sudo').then(value=>{if(active){setSettings(value);setEnabled(value.enabled);setRemember(value.password_saved);setReady(true)}}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[host.id]);
  const save=async(e:React.FormEvent)=>{
    e.preventDefault();setPending(true);setError('');setMessage('');
    try{const value=await api('/hosts/'+host.id+'/sudo','POST',{enabled,password:password||null,remember,install_helper:install});setSettings(value);setRemember(value.password_saved);setInstall(false);setMessage(enabled?'已保存并验证，下一次采集会补齐进程详情。':'已关闭 sudo 采集，普通监控继续运行。');await updated()}
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
      <div className="sudo-state"><ShieldCheck size={16}/><div><strong>{settings?.message||'正在读取设置…'}</strong><small>{settings?.password_saved?'密码已保存在 Windows 凭据管理器':settings?.password_in_memory?'密码仅保留到软件退出':'未保存 sudo 密码'}</small></div></div>
      <label className="form-label">此机器的 sudo 密码 <small>已保存密码或具备 sudo 免密权限时可留空</small><input aria-label="sudo 密码" type="password" autoComplete="off" maxLength={512} disabled={!enabled||pending||!ready} value={password} onChange={e=>setPassword(e.target.value)} placeholder={settings?.password_saved?'留空使用已保存密码':'输入当前 SSH 账号的 sudo 密码'}/></label>
      <label className="checkbox-label sudo-remember"><input type="checkbox" checked={remember} disabled={!enabled||pending||!ready||!settings?.can_remember} onChange={e=>setRemember(e.target.checked)}/>记住 sudo 密码（Windows 凭据管理器）</label>
      <p className="subtle sudo-hint">不勾选时，输入的密码只保留到本地服务退出。取消勾选后保存，也会删除原来保存的密码。</p>
      <label className="sudo-option sudo-install"><input type="checkbox" checked={install} disabled={!enabled||pending||!ready} onChange={e=>setInstall(e.target.checked)}/><div><strong>安装或更新固定的只读采集程序</strong><p>首次启用时勾选。保存后会在远端安装 root 所有的进程采集文件，不修改 sudo 授权规则。后续采集只调用此程序。</p></div></label>
      <div className="privacy-note"><ShieldCheck size={14}/>密码不会写入配置文件、浏览器存储或日志；普通账号仍需拥有服务器授予的 sudo 权限。</div>
      {error&&<div role="alert" className="connection-error">{error}</div>}{message&&<p role="status" className="sudo-success">{message}</p>}
      <div className="modal-footer"><button type="button" className="text-button sudo-forget" disabled={pending||!ready||(!settings?.password_saved&&!settings?.password_in_memory)} onClick={forget}><Trash2 size={14}/>删除保存的密码</button><button className="primary" disabled={pending||!ready}>{pending?<LoaderCircle size={16} className="spin"/>:<ShieldCheck size={16}/ >}{pending?'正在处理…':enabled?'保存并验证':'保存设置'}</button></div>
    </form>
  </section></div>;
}

function AddMachine({close,connected}:{close:()=>void;connected:(message:string,hostId?:string)=>void}){
  const [manual,setManual]=useState(false),[aliases,setAliases]=useState<string[]>([]),[query,setQuery]=useState(''),[target,setTarget]=useState(''),[user,setUser]=useState(''),[port,setPort]=useState(22),[password,setPassword]=useState(''),[provision,setProvision]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[configPath,setConfigPath]=useState('');
  useEffect(()=>{api('/config-hosts').then(data=>{setAliases(data.aliases);setConfigPath(data.path)}).catch(e=>setError(e.message))},[]);
  const connect=async(e:React.FormEvent)=>{e.preventDefault();setLoading(true);setError('');try{const result=await api('/connect','POST',{target,user:user||null,port:manual?port:null,manual,password:password||null,provision});setPassword('');connected(result.message,result.host_id)}catch(e){setPassword('');setError(e instanceof Error?e.message:String(e))}finally{setLoading(false)}};
  return <div className="modal-shade"><section role="dialog" aria-modal="true" aria-labelledby="add-title" className="modal"><div className="modal-header"><div><div className="eyebrow">CONNECT / SSH</div><h2 id="add-title">添加机器</h2></div><button className="icon-button" disabled={loading} aria-label="关闭添加机器" onClick={close}><X size={20}/></button></div><div className="tabs"><button type="button" className={!manual?'selected':''} onClick={()=>{setManual(false);setTarget('');setError('')}}>从 SSH 配置选择</button><button type="button" className={manual?'selected':''} onClick={()=>{setManual(true);setTarget('');setError('')}}>手动添加</button></div><form onSubmit={connect}>
    {!manual?<><p className="config-path"><Terminal size={13}/>{configPath||'读取 ~/.ssh/config…'}</p><div className="search-input"><Search size={16}/><input aria-label="搜索 SSH 机器" placeholder="搜索已保存的机器…" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="alias-list">{aliases.filter(a=>a.toLowerCase().includes(query.toLowerCase())).map(a=><button type="button" className={target===a?'selected':''} key={a} onClick={()=>setTarget(a)}><Server size={15}/><span>{a}</span>{target===a?<Check size={15}/>:<ChevronRight size={14}/>}</button>)}{aliases.length===0&&<p className="subtle">未找到机器，可切换到手动添加。</p>}</div></>:<><label className="form-label">主机地址<input required placeholder="例如 192.168.1.10" value={target} onChange={e=>setTarget(e.target.value.trim())}/></label><label className="form-label">SSH 端口<input required type="number" min="1" max="65535" value={port} onChange={e=>setPort(+e.target.value)}/></label></>}
    <div className="form-row"><label className="form-label">用户名 {!manual&&<small>留空使用 SSH 配置</small>}<input required={manual} autoComplete="username" value={user} onChange={e=>setUser(e.target.value.trim())} placeholder={manual?'登录用户名':'使用已有配置'}/></label><label className="form-label">密码 <small>已有免密可留空</small><input type="password" autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} placeholder="仅在本次连接时使用"/></label></div>
    <label className="provision-option"><input type="checkbox" checked={provision} onChange={e=>setProvision(e.target.checked)}/><div><strong>登录后自动配置免密连接</strong><p>生成本机专用密钥，向远端追加公钥，再验证无密码登录。需要提供本次登录密码。</p></div><ShieldCheck size={20}/></label><div className="privacy-note"><ShieldCheck size={14}/>密码不保存；不覆盖远端已有公钥。未勾选时仅保持本次会话。</div>
    {error&&<div role="alert" className="connection-error">{error}</div>}<div className="modal-footer"><span>{target?<><i className="dot"/>{target}</>:'选择一台机器开始'}</span><button className="primary" disabled={loading||!target||(provision&&!password)}>{loading?<LoaderCircle size={16} className="spin"/>:<ArrowUpRight size={16}/ >}{loading?'正在连接…':'连接机器'}</button></div></form></section></div>
}
createRoot(document.getElementById('root')!).render(<App/>);
