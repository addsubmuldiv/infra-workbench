import {MONITORING_REFRESH_INTERVAL_SECONDS,UI_NOTICE_DURATION_MS} from './internalDefaults.ts';
import {RefreshIntervalPicker} from './features/monitoring/RefreshIntervalPicker';
import {TunnelManagerButton} from './features/hosts/TunnelManager';
import {HostAliasDialog} from './features/hosts/HostAliasDialog';
import {GroupReservations,type GroupDraft} from './features/reservations/GroupReservations';
import {ResourceHistory} from './features/monitoring/ResourceHistory';
import {ClusterTarget} from './features/hosts/ClusterTarget';
import {ClusterSidebar} from './features/hosts/ClusterSidebar';
import {ClusterPanel} from './features/hosts/ClusterPanel';
import {ModalDialog} from './shared/ModalDialog';
import type {Cluster} from './features/hosts/clusterApi';
import {ServicePanel} from './features/hosts/ServicePanel';
import {VSCodeButton} from './features/hosts/VSCodeButton';
import {SSHTunnelButton,type TunnelRule} from './features/hosts/SSHTunnelPanel';
import {TERMINAL_CONTEXT_EVENT} from './features/terminal/terminalContext';
import {isDemo,demoRuntime} from './features/onboarding/demoBootstrap';
import {LanguageSettings} from './features/settings/LanguageSettings';
import {DesktopUpdateNotification,DesktopVersion} from './features/desktop/DesktopUpdatePanel';
import {DemoGuide,type DemoStep} from './features/onboarding/DemoGuide';
import {FirstRunGuide} from './features/onboarding/FirstRunGuide';
import {GitHubStarPrompt} from './features/onboarding/GitHubStarPrompt';
import {DemoSettings,DemoTerminal} from './features/onboarding/DemoPanels';
import {ui,themeText} from './shared/mainI18n';
import {t as tr,useLocale,initializeLocale,dateLocale} from './shared/i18n';
import {initializeWorkspace,workspaceStorage} from './workspace/workspaceState';
import {useWorkspaceRestore,useWorkspaceValue} from './workspace/workspaceHooks';
import {browserId} from './shared/browserId';
import React, {useEffect, useMemo, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {History, ChartLine, KeyRound, ArrowDownLeft, ArrowUpRight, CalendarClock, Check, ChevronDown, ChevronRight, CircleHelp, Copy, Cpu, Database, LayoutGrid, LoaderCircle, Monitor, Pause, Play, Plus, Palette, Radio, RefreshCw, Search, Server, Settings, Shield, ShieldCheck, Terminal, Trash2, X, Zap} from 'lucide-react';
import './style.css';
import './styles/themes.css';
import {DeviceDrawerFrame} from './features/monitoring/DeviceDrawerFrame';
import './styles/journey.css';
import './workspace/sidebarLayout.css';
import './workspace/windowLayers.css';
import './features/monitoring/resourceOverview.css';
import './styles/rendering.css';
import './styles/solidGlass.css';
import './styles/coastSunset.css';
import {WorkspaceLayout} from './workspace/WorkspaceLayout';
import {DesktopWindowControls,hasDesktopTitlebar} from './features/desktop/DesktopWindowControls';
import {JourneyArt} from './styles/JourneyArt';
const PrecisionCompare=React.lazy(()=>import('./features/training-logs/PrecisionCompare').then(module=>({default:module.PrecisionCompare})));
const FileBrowser=React.lazy(()=>import('./features/files/FileBrowser').then(module=>({default:module.FileBrowser})));
import type {TerminalRequest} from './features/terminal/TerminalDock';
import {TerminalBoundary} from './features/terminal/TerminalBoundary';
import {RenderBoundary,RenderFailure} from './shared/RenderBoundary';
const QuickWindow=React.lazy(()=>import('./features/desktop/QuickWindow').then(module=>({default:module.QuickWindow})));
import {pageFromHash,hostLocationFromHash,modelSettingsHash,notificationLocation,type Page} from './workspace/navigation';
const ClusterTerminalWorkspace=React.lazy(()=>import('./features/terminal/ClusterTerminalWorkspace').then(module=>({default:module.ClusterTerminalWorkspace})));
const TerminalDock=React.lazy(()=>import('./features/terminal/TerminalDock').then(module=>({default:module.TerminalDock})));
const ServerImport=React.lazy(()=>import('./features/hosts/ServerImport'));
import {THEMES, browserStorage, loadPreferences, savePreferences, scopedHosts, toggleHost} from './workspace/preferences';
import {shouldNotify,type NotificationRecord} from './features/reservations/notifications';
import {NotificationCenter,type NotificationTab} from './features/reservations/NotificationCenter';
import {Reservations,ReservationDialog,type ReservationDraft} from './features/reservations/ReservationPanel';
import {reservationDraft as draftFromReservation,reservationLocation,type Reservation} from './features/reservations/reservations';
const SettingsPage=React.lazy(()=>import('./features/settings/SettingsPage'));
const AssistantWindow=React.lazy(()=>import('./features/assistant/AssistantWindow').then(module=>({default:module.AssistantWindow})));
import {ASSISTANT_OPEN_KEY,loadAssistantOpen} from './features/assistant/assistantLayout';
import {Sparkles} from 'lucide-react';
import {singleFlight,reuseStateSnapshot} from './shared/requests';
import {watchStateChanges} from './features/monitoring/stateChanges';
import {SSHAccountsDialog} from './features/hosts/SSHAccountsDialog';
import {SSHAccountPicker} from './features/hosts/SSHAccountPicker';
import {pinSSHLogin, sshAccountUrl, type SSHLoginHost} from './features/hosts/sshLogins';
import {RemoveHostDialog} from './features/hosts/RemoveHostDialog';
import {deviceUsage} from './features/monitoring/hostUsage';
import {HOST_CATEGORIES,filterHosts,type HostCategory} from './features/hosts/hostList';

type Collection = {paused?:boolean;actual_interval_seconds?:number;status:string;queue_seconds?:number;duration_seconds?:number;request_bytes?:number;response_bytes?:number;samples?:number;total_response_bytes?:number};
type ProcessContainer = {
  id?:string|null; name?:string|null; runtime?:string|null; orchestrator?:string|null; pid?:number|null;
  audit_login_user?:string|null; audit_login_uid?:number|null; host_cwd_status:string;
};
type Proc = {details_collected_at?:number|null;pid:number; name:string; user:string|null; memory_used:number|null; uid?:number|null; effective_uid?:number|null; parent_pid?:number|null; cwd?:string|null; host_cwd?:string|null; container?:ProcessContainer|null; executable?:string|null; command?:string|null; command_truncated?:boolean; identity_verified?:boolean; detail_status?:string; detail_source?:string; errors?:Record<string,string>};
type Device = {id:string; display_id?:string; card_id?:string; chip_id?:string; physical_id?:string|null; kind:string; name:string; memory_total:number; memory_used:number; memory_free:number; utilization:number|null; temperature:number|null; processes:Proc[]; processes_known:boolean; health:string};
type SystemMetrics = {cpu_percent:number|null;cpu_cores:number|null;memory:{memory_total:number;memory_used:number;memory_available:number}|null};
type SudoSettings = {enabled:boolean;password_saved:boolean|null;credential_error?:string;password_in_memory:boolean;can_remember:boolean;status:string;message:string;ssh_password_saved?:boolean|null};
type Host = SSHLoginHost & {collection?:Collection; alias?:string; user:string|null; port:number|null; manual:boolean; auth:string; sudo?:SudoSettings; ssh_tunnels?:TunnelRule[]; ssh_password?:{password_saved:boolean|null;can_remember:boolean;error?:string|null}; snapshot:{status:string; fresh:boolean; collected_at:number|null; error?:string; error_stage?:string; sections?:Record<string,{fresh:boolean;collected_at:number|null}>; system?:SystemMetrics|null; devices:Device[]}};
type Rule = {id:string; host_id:string; devices:string[]; minimum_gib:number; port:number; status?:string};
type Event = {id:number; created:number; host:string; message:string; notify?:boolean; url?:string};
type State = {refresh_interval_seconds?:number;hosts:Host[]; rules:Rule[]; reservations:Reservation[]; reservation_modes?:string[];group_reservations?:{id:string;status:string;candidate_host_ids:string[]}[]; events:Event[]; server_time:number};
const gib=(n:number|null|undefined)=>n==null?'—':(n/1024**3).toFixed(1);
const clock=(n:number)=>new Date(n*1000).toLocaleTimeString(dateLocale(),{hour12:false});
const displayId=(d:Device|undefined)=>d?.display_id??d?.id??ui("已失效");
function machineSummary(ds:Device[]){
  if(!ds.length)return ui("等待设备信息");
  const npus=ds.filter(d=>d.kind==='NPU'),cards=new Set(npus.map(d=>d.card_id??d.id));
  return npus.length>cards.size?tr(`${cards.size} 张 NPU 卡 / ${npus.length} 个设备 · ${npus[0].name}`,`${cards.size} NPU cards / ${npus.length} devices · ${npus[0].name}`):`${ds.length} × ${ds[0].name}`;
}
async function api(path:string,method='GET',body?:unknown,signal?:AbortSignal){
  const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body),signal});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:ui("操作失败"));
  return data;
}
function isEligible(d:Device,min:number,clear:boolean){return d.memory_free>=min*1024**3&&(!clear||(d.processes_known&&d.processes.length===0))&&d.health!=='Alarm'}
function Badge({children,tone='muted'}:{children:React.ReactNode;tone?:string}){return <span className={'badge '+tone}>{children}</span>}

const BROWSER_NOTIFICATIONS_KEY='workspace:browser-notifications:v1';
const browserPermissionGranted=()=>!isDemo&&'Notification' in window&&Notification.permission==='granted';
const canSendBrowserNotifications=()=>browserPermissionGranted()&&workspaceStorage.getItem(BROWSER_NOTIFICATIONS_KEY)==='true';

async function showBrowserNotifications(events:NotificationRecord[]){
  if(!events.length)return;
  try{
    const {ids}=await api('/notifications/browser-claim','POST',{ids:events.map(event=>event.id)});
    if(!canSendBrowserNotifications())return;
    const claimed=new Set<number>(ids);
    for(const event of events){
      if(!claimed.has(event.id))continue;
      const notification=new Notification('Infra Workbench',{
        body:event.message,tag:String(event.id),
        icon:new URL('../../backend/assets/workbench.png',import.meta.url).href,
      });
      notification.onclick=()=>{window.open(location.origin+location.pathname+notificationLocation(event.url),'_blank','noopener');notification.close()};
    }
  }catch{
    // Events remain visible in the notification center if pop-ups are unavailable.
  }
}

// Every value read by the card is listed in dependencies below. Handlers use
// those same values, stable setters and the shared single-flight state reader.
const EMPTY_SELECTION:string[]=[];
const MachineView=React.memo(function MachineView({render}:{dependencies:unknown[];render:()=>React.ReactNode}){return render()},
  (before,after)=>before.dependencies.length===after.dependencies.length&&before.dependencies.every((value,index)=>Object.is(value,after.dependencies[index])));

function App(){
  const locale=useLocale();
  const [aliasHost,setAliasHost]=useState<Host|null>(null);
  const [state,setState]=useState<State>({hosts:[],rules:[],reservations:[],events:[],server_time:0});
  const [reservationDraft,setReservationDraft]=useState<ReservationDraft|null>(null);
  const [groupDraft,setGroupDraft]=useState<GroupDraft|null>(null);
  const [historyHostIds,setHistoryHostIds]=useState<string[]|undefined>(undefined);
  const [pendingLocation,setPendingLocation]=useState(()=>hostLocationFromHash(location.hash));
  const [preferences,setPreferences]=useState(()=>loadPreferences(browserStorage()));
  useWorkspaceRestore('infra-workbench:preferences:v1',()=>loadPreferences(browserStorage()),setPreferences);
  const [hostSearch,setHostSearch]=useWorkspaceValue('workspace:host-search','');
  const [hostCategory,setHostCategory]=useWorkspaceValue<HostCategory>('workspace:host-category','全部');
  const [clusterPanel,setClusterPanel]=useState<{cluster:Cluster|null}|null>(null);
  const [clusterTerminal,setClusterTerminal]=useState<{cluster:Cluster|null;batchId?:string}|null>(()=>{const id=new URLSearchParams(location.search).get('cluster_terminal_batch');return id?{cluster:null,batchId:id}:null});
  function closeClusterTerminal(){
    setClusterTerminal(null);
    const url=new URL(location.href);
    url.searchParams.delete('cluster_terminal_batch');
    history.replaceState(history.state,'',url);
  }
  const [sudoHost,setSudoHost]=useState<Host|null>(null);
  const [sshAccountsHost,setSSHAccountsHost]=useState<Host|null>(null);
  const [sshAccountChoice,setSSHAccountChoice]=useState<{host:Host;tool:'terminal'|'files'}|null>(null);
  const [removalHosts,setRemovalHosts]=useState<Host[]>([]);
  const [fileHost,setFileHost]=useState<{host:Host;requestId:string;path?:string}|null>(null);
  const [serviceHost,setServiceHost]=useState<Host|null>(null);
  const [terminalRequest,setTerminalRequest]=useState<TerminalRequest|null>(null);
  function openSSHWindow(host: Host, tool: 'terminal' | 'files', accountId?: string, directory?: string) {
    const login = pinSSHLogin(host, accountId);
    if (login.ssh_account_id && !host.ssh_logins?.accounts.some(account => account.id === login.ssh_account_id)) {
      setSSHAccountChoice({host, tool});
      return;
    }
    if (tool === 'terminal') setTerminalRequest({id: browserId(), host: login, cwd: directory});
    else setFileHost({host: login, requestId: browserId(), path: directory});
  }
  const [notificationTab,setNotificationTab]=useState<NotificationTab>(()=>location.hash.split('?')[0]==='#watch'?'messages':null);
  const [precisionMounted,setPrecisionMounted]=useState(()=>pageFromHash(location.hash)==='precision');
  const [assistantOpen,setAssistantOpen]=useState(()=>location.hash.split('?')[0]==='#assistant'||loadAssistantOpen(browserStorage())),[assistantWidth,setAssistantWidth]=useState(0);
  useWorkspaceRestore(ASSISTANT_OPEN_KEY,()=>loadAssistantOpen(browserStorage()),setAssistantOpen);
  useEffect(()=>{try{browserStorage()?.setItem(ASSISTANT_OPEN_KEY,String(assistantOpen))}catch{}},[assistantOpen]);
  useEffect(()=>{const open=()=>setAssistantOpen(true);window.addEventListener(TERMINAL_CONTEXT_EVENT,open);return()=>window.removeEventListener(TERMINAL_CONTEXT_EVENT,open)},[]);
  const [page,setPage]=useWorkspaceValue<Page>('workspace:page',pageFromHash(location.hash)==='assistant'?'overview':pageFromHash(location.hash)),[filter,setFilter]=useWorkspaceValue('workspace:filter','全部'),[count,setCount]=useWorkspaceValue('workspace:count',1),[minimum,setMinimum]=useWorkspaceValue('workspace:minimum',16),[clear,setClear]=useWorkspaceValue('workspace:clear',true);
  const [resourceKind,setResourceKind]=useWorkspaceValue('workspace:resourceKind','全部'),[selectedScope,setSelectedScope]=useWorkspaceValue('workspace:selectedScope',false),[deviceOverview,setDeviceOverview]=useWorkspaceValue('workspace:deviceOverview',false);
  const [adding,setAdding]=useState(false),[detail,setDetail]=useState<{host:string;device:string}|null>(null),[selected,setSelected]=useWorkspaceValue<Record<string,string[]>>('workspace:selected-devices',{});
  const [refreshing,setRefreshing]=useState<Record<string,string>>({});
  const [collectionBusy,setCollectionBusy]=useState(false);
  const refreshPending=useRef(new Map<string,Promise<void>>());
  const refreshTimers=useRef(new Map<string,ReturnType<typeof setTimeout>>());
  useEffect(()=>()=>{for(const timer of refreshTimers.current.values())clearTimeout(timer);refreshTimers.current.clear()},[]);
  const finishRefresh=(hostId:string,status:string)=>{
    setRefreshing(old=>({...old,[hostId]:status}));
    refreshTimers.current.set(hostId,setTimeout(()=>{
      refreshTimers.current.delete(hostId);
      setRefreshing(old=>{if(old[hostId]!==status)return old;const next={...old};delete next[hostId];return next});
    },3000));
  };
  const [notice,setNotice]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(''),[port,setPort]=useWorkspaceValue('workspace:port',29500),[check,setCheck]=useState<{status:string;reasons:string[]}|null>(null);
  const [exportingSSH,setExportingSSH]=useState(false);
  async function addToSSHConfig(host:Host){
    if(isDemo||exportingSSH)return;
    setExportingSSH(true);
    try{
      const result=await api('/hosts/'+encodeURIComponent(host.id)+'/ssh-config','POST');
      setNotice(result.added
        ?tr(`已将 ${result.alias} 添加到 ~/.ssh/config，可在 VS Code 的 Remote - SSH 中选择。`,`Added ${result.alias} to ~/.ssh/config. Select it in VS Code Remote - SSH.`)
        :tr(`${result.alias} 已在 SSH 配置中，可在 VS Code 的 Remote - SSH 中选择。`,`${result.alias} is already in your SSH config. Select it in VS Code Remote - SSH.`));
    }catch(error){
      const messages:Record<string,[string,string]>={
        SSH_CONFIG_ALIAS_INVALID:['SSH 别名需要以字母、数字或下划线开头，只能包含字母、数字、下划线、点和连字符。请在机器的「别名」中修改后重试。','Start the SSH alias with a letter, number or underscore. Use only letters, numbers, underscores, dots and hyphens. Edit the machine alias and try again.'],
        SSH_CONFIG_ALIAS_CONFLICT:['SSH 配置中已有同名条目，但连接参数不同。请修改工作台里的机器别名后重试。','The alias already exists with different connection settings. Edit the machine alias and try again.'],
        SSH_CONFIG_SHADOWED:['SSH 配置里的规则会覆盖新条目的连接参数。请检查 ~/.ssh/config 后重试。','Existing SSH rules override the new connection settings. Check ~/.ssh/config and try again.'],
        SSH_CONFIG_CHANGED:['SSH 配置刚被修改，请重试。','The SSH config changed during export. Try again.'],
        SSH_CONFIG_UNRESOLVED:['无法解析机器的 SSH 配置，请检查本机 OpenSSH 和连接参数。','Could not resolve the SSH configuration. Check OpenSSH and the machine connection settings.'],
        SSH_CONFIG_IO_FAILED:['无法写入 ~/.ssh/config，请检查文件权限和可用空间。','Could not write ~/.ssh/config. Check file permissions and available space.'],
        SSH_CONFIG_HOST_NOT_FOUND:['机器已移除，请刷新列表。','The machine was removed. Refresh the list.'],
      };
      const message=error instanceof Error?messages[error.message]:undefined;
      setNotice(message?tr(...message):tr('添加到 SSH 配置失败，请重试。','Could not add the machine to SSH config. Try again.'));
    }finally{setExportingSSH(false)}
  }
  const [browserNotifications,setBrowserNotifications]=useWorkspaceValue(BROWSER_NOTIFICATIONS_KEY,false);
  const notify=browserNotifications&&browserPermissionGranted();
  useEffect(()=>{if(!isDemo)return;const blocked=()=>setNotice(tr('此操作在演示中不可用，不会访问真实服务。','This action is unavailable in demo; no real service is accessed.'));document.addEventListener('demo-operation-blocked',blocked);return()=>document.removeEventListener('demo-operation-blocked',blocked)},[]);
  const lastEvent=useRef<number|null>(null),storageWarning=useRef(false),themeMenu=useRef<HTMLDetailsElement>(null),mobileHosts=useRef<HTMLDetailsElement>(null);
  const machineActions=useRef<HTMLDetailsElement>(null);
  useEffect(()=>{if(page==='precision')setPrecisionMounted(true);if(pageFromHash(location.hash)!==page&&!hostLocationFromHash(location.hash)&&location.hash!==modelSettingsHash)window.history.replaceState(window.history.state,'','#'+page)},[page]);
  const [workspaceError,setWorkspaceError]=useState(false);
  useEffect(()=>{const status=(event:globalThis.Event)=>setWorkspaceError((event as unknown as CustomEvent<boolean>).detail);window.addEventListener('workspace-save-status',status as EventListener);return()=>window.removeEventListener('workspace-save-status',status as EventListener)},[]);
  const navigate=(next:Page,historyIds?:string[],hash='#'+next)=>{
    if(next==='assistant'){setAssistantOpen(true);return}
    if(next==='history')setHistoryHostIds(historyIds);
    setPage(next);if(next==='precision')setPrecisionMounted(true);
    setDetail(null);setCheck(null);
    if(themeMenu.current)themeMenu.current.open=false;
    if(machineActions.current)machineActions.current.open=false;
    if(location.hash!==hash&&!(next==='overview'&&!location.hash))location.hash=hash;
    if(next!==page)window.scrollTo({top:0});
  };
  const showDemoStep=(step:DemoStep)=>{
    setReservationDraft(null);setGroupDraft(null);setServiceHost(null);
    setFileHost(null);setTerminalRequest(null);setAssistantOpen(false);setNotificationTab(null);
    setPreferences(old=>({...old,hostIds:null}));setFilter('全部');
    if(step==='history'){
      navigate('history',['demo-gpu-busy','demo-gpu-free'].filter(id=>demoRuntime!.getHosts().some(host=>host.id===id)));
    }else if(step==='groups')navigate('reservations');
    else if(step==='precision'||step==='settings')navigate(step);
    else navigate('overview');
  };
  useEffect(()=>{
    const sync=()=>{setPendingLocation(hostLocationFromHash(location.hash));const requested=pageFromHash(location.hash);const next=requested==='assistant'?'overview':requested;if(requested==='assistant'){setAssistantOpen(true);window.history.replaceState(window.history.state,'','#overview')}setPage(next);if(next==='precision')setPrecisionMounted(true);setDetail(null);setCheck(null);window.scrollTo({top:0})};
    const syncLegacy=()=>{const legacy=location.hash.split('?')[0];if(legacy==='#watch')setNotificationTab('messages');if(legacy==='#connections'||legacy==='#watch')window.history.replaceState(window.history.state,'',location.hash.replace(/^#(?:connections|watch)/,'#overview'));sync()};
    if(location.hash===modelSettingsHash||['#connections','#watch','#assistant'].includes(location.hash.split('?')[0]))syncLegacy();
    window.addEventListener('hashchange',syncLegacy);return()=>window.removeEventListener('hashchange',syncLegacy);
  },[]);
  useEffect(()=>{
    const outside=(event:PointerEvent)=>{for(const menu of [themeMenu.current,machineActions.current])if(menu?.open&&!menu.contains(event.target as Node))menu.open=false};
    const escape=(event:KeyboardEvent)=>{
      if(event.key!=='Escape')return;
      for(const menu of [themeMenu.current,machineActions.current]){
        if(!menu?.open)continue;
        menu.open=false;
        if(menu.contains(event.target as Node))menu.querySelector('summary')?.focus();
      }
    };
    document.addEventListener('pointerdown',outside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape)};
  },[]);
  const stateRequest=useRef<AbortController|null>(null);
  const [load]=useState(()=>singleFlight(async()=>{
    const controller=new AbortController();stateRequest.current=controller;
    try{
      const next:State=await api('/state','GET',undefined,controller.signal);if(controller.signal.aborted)return;setState(old=>reuseStateSnapshot(old,{...next,reservations:next.reservations??[]}));setError('');
      const previousEvent=lastEvent.current;
      lastEvent.current=next.events[0]?.id??lastEvent.current??0;
      if(previousEvent!==null&&canSendBrowserNotifications())
        void showBrowserNotifications(next.events.filter(event=>event.id>previousEvent&&shouldNotify(event)).reverse());
      return true;
    }catch{if(!controller.signal.aborted)setError(ui("本地服务未连接，请检查启动窗口。"));return false}
    finally{if(stateRequest.current===controller)stateRequest.current=null}
  }));
  const refreshHost=(host:Host):Promise<void>=>{
    if(host.collection?.paused)return Promise.resolve();
    const existing=refreshPending.current.get(host.id);if(existing)return existing;
    clearTimeout(refreshTimers.current.get(host.id));refreshTimers.current.delete(host.id);
    setRefreshing(old=>({...old,[host.id]:'running'}));
    const task=(async()=>{
      try{
        const result=await api('/hosts/'+encodeURIComponent(host.id)+'/refresh','POST');
        finishRefresh(host.id,result.status==='error'?'error':'done');
        if(result.status==='error')setNotice(host.target+': '+result.error);
      }catch(error){finishRefresh(host.id,'error');setNotice(error instanceof Error?error.message:String(error))}
      finally{refreshPending.current.delete(host.id);await load()}
    })();
    refreshPending.current.set(host.id,task);return task;
  };
  const refreshMany=async(hosts:Host[])=>{
    const queue=hosts.filter(host=>!host.collection?.paused);
    setRefreshing(Object.fromEntries(queue.map(host=>[host.id,'waiting'])));
    await Promise.all(Array.from({length:Math.min(8,queue.length)},async()=>{
      while(queue.length){const host=queue.shift();if(host)await refreshHost(host)}
    }));
  };
  const setCollectionPaused=async(hosts:Host[],paused:boolean)=>{
    if(isDemo||collectionBusy||!hosts.length)return;
    setCollectionBusy(true);
    try{
      const results=await Promise.allSettled(hosts.map(host=>
        api('/hosts/'+encodeURIComponent(host.id)+'/collection','PUT',{paused})));
      const pending=stateRequest.current;
      if(await load()&&pending)await load();

      const failed=hosts.filter((_,index)=>results[index].status==='rejected');
      const changed=hosts.length-failed.length;
      const summary=paused?tr(`已暂停 ${changed} 台机器的采集`,`Paused collection on ${changed} machines`):tr(`已恢复 ${changed} 台机器的采集`,`Resumed collection on ${changed} machines`);
      const firstFailure=results.find(result=>result.status==='rejected');
      const detail=firstFailure?.reason instanceof Error?` · ${firstFailure.reason.message}`:'';
      const names=failed.map(host=>host.alias||host.target);
      setNotice(failed.length?tr(`${summary}，失败 ${failed.length} 台（${names.join('、')}）${detail}`,`${summary}. Failed on ${failed.length} (${names.join(', ')})${detail}`):summary);
    }finally{setCollectionBusy(false)}
  };
  const changeBatchCollection=(hosts:Host[],paused:boolean)=>{
    const menu=machineActions.current;
    if(menu){menu.open=false;menu.querySelector('summary')?.focus()}
    return setCollectionPaused(hosts,paused);
  };
  const refreshInterval=state.refresh_interval_seconds??MONITORING_REFRESH_INTERVAL_SECONDS;
  const saveRefreshInterval=async(interval:number|null)=>{setBusy('refresh-interval');try{const result=await api('/settings/refresh','PUT',{interval_seconds:interval});setState(old=>({...old,refresh_interval_seconds:result.interval_seconds}));setNotice(ui("刷新间隔已保存"))}catch(error){setNotice(error instanceof Error?error.message:ui("刷新间隔保存失败"))}finally{setBusy('')}};
  useEffect(()=>{load();const timer=setInterval(load,refreshInterval*1000);return()=>clearInterval(timer)},[refreshInterval]);
  useEffect(()=>{
    if(isDemo)return;
    const controller=new AbortController();
    void watchStateChanges({signal:controller.signal,onChange:async()=>{
      const pending=stateRequest.current;
      if(!await load()||pending&&!await load())throw Error('State refresh failed');
    }});
    return()=>controller.abort();
  },[load]);
  useEffect(()=>()=>stateRequest.current?.abort(),[]);
  useEffect(()=>{
    document.documentElement.dataset.theme=preferences.theme;
    if(!savePreferences(browserStorage(),preferences)&&!storageWarning.current){storageWarning.current=true;setNotice(ui("工作空间偏好暂时无法保存，请检查本地后台连接。"))}
  },[preferences]);
  useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),UI_NOTICE_DURATION_MS);return()=>clearTimeout(t)},[notice]);
  useEffect(()=>{
    if(!pendingLocation||!state.server_time)return;
    const hasDevices=pendingLocation.devices.length>0;
    const host=state.hosts.find(host=>host.id===pendingLocation.hostId);
    if(!host){setNotice(hasDevices?ui("提醒对应的机器已移除，请在卡预约中查看记录。"):ui("这台机器已不在当前列表中。"));setPendingLocation(null);return}
    if(hasDevices&&host.snapshot.status==='connecting'&&!host.snapshot.devices.length)return;
    const ids=pendingLocation.devices.filter(id=>host.snapshot.devices.some(device=>device.id===id));
    setPreferences(old=>({...old,hostIds:[host.id]}));setFilter('全部');setHostCategory('全部');setHostSearch('');
    setDeviceOverview(false);if(mobileHosts.current)mobileHosts.current.open=false;
    setSelected({[host.id]:ids});
    if(ids.length<pendingLocation.devices.length)setNotice(ui("已定位机器；部分设备未出现在最近采集中，请核对当前设备列表。"));
    else if(ids.length)setNotice(ui("已定位提醒对应的机器和设备，请在使用前检查当前占用。"));
    setPendingLocation(null);
  },[pendingLocation,state.hosts,state.server_time]);
  const locateReservation=(item:Reservation)=>{
    const hash=reservationLocation(item);setPage('overview');setDetail(null);setCheck(null);
    setPendingLocation(hostLocationFromHash(hash));location.hash=hash;window.scrollTo({top:0});
  };

  const locateEvent=(event:NotificationRecord)=>{
    if(event.url?.startsWith('#reservations?group=')&&notificationLocation(event.url)!=='#reservations'){setPage('reservations');location.hash=notificationLocation(event.url);return}
    const target=hostLocationFromHash(event.url??'');
    if(target){setPage('overview');setPendingLocation(target);setDetail(null);setCheck(null);location.hash=event.url!;window.scrollTo({top:0})}
    else if(state.hosts.some(host=>host.id===event.host))selectHosts([event.host],true);
    else navigate('reservations');
  };

  const act=async(key:string,fn:()=>Promise<unknown>)=>{setBusy(key);try{await fn();await load()}catch(e){setNotice(e instanceof Error?e.message:String(e))}finally{setBusy('')}};
  const toggleNotifications=async()=>{
    if(isDemo){setNotice(tr("演示提醒仅显示在页面内，不申请系统通知权限。","Demo alerts appear only in this page. System notifications are disabled."));return}
    if(!('Notification'in window)){setNotice(ui("此浏览器不支持系统通知，事件仍显示在页面中。"));return}
    if(canSendBrowserNotifications()){
      setBrowserNotifications(false);
      setNotice(tr("浏览器通知已关闭，消息仍会记录在通知中心。","Browser notifications are off. Messages remain in the notification center."));
      return;
    }
    let permission=Notification.permission;
    if(permission==='default'){
      try{permission=await Notification.requestPermission()}catch{}
    }
    if(permission==='granted')setBrowserNotifications(true);
    setNotice(permission==='granted'?ui("浏览器通知已开启；请保持页面和本地服务运行。"):ui("浏览器通知未开启，事件仍显示在页面中。"));
  };
  const scope=useMemo(()=>scopedHosts(state.hosts,preferences.hostIds),[state.hosts,preferences.hostIds]);
  const collectingHosts=scope.filter(host=>!host.collection?.paused);
  const pausedHosts=scope.filter(host=>host.collection?.paused);
  const refreshStates=Object.values(refreshing);
  const refreshInProgress=refreshStates.some(value=>value==='running'||value==='waiting');
  const allMachinesSelected=state.hosts.length>0&&scope.length===state.hosts.length;
  const devices=useMemo(()=>state.hosts.flatMap(h=>h.snapshot.devices),[state.hosts]);
  const online=useMemo(()=>state.hosts.filter(h=>h.snapshot.fresh).length,[state.hosts]);
  const waitingReservations=useMemo(()=>state.reservations.filter(item=>item.status!=='ready'),[state.reservations]);
  const waitingGroups=(state.group_reservations??[]).filter(item=>!['ready','cancelled'].includes(item.status));
  const reservationMachines=new Set([...waitingReservations.map(item=>item.host_id),...waitingGroups.flatMap(item=>item.candidate_host_ids)]).size;
  const pendingReservations=waitingReservations.length+waitingGroups.length;
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
    setNotice(ids===null?ui("已展示全部机器"):ids.length?tr(`已展示 ${ids.length} 台机器`,`Showing ${ids.length} machines`):ui("已清空机器选择，仍可在全部机器中寻找资源"));
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
    if(sshAccountsHost?.id===host.id)setSSHAccountsHost(null);
    if(sshAccountChoice?.host.id===host.id)setSSHAccountChoice(null);
    if(sudoHost?.id===host.id)setSudoHost(null);
    if(detail?.host===host.id){setDetail(null);setCheck(null)}
    setNotice(ui("已移除机器 ")+host.target);
  };
  const inspect=(host:Host,d:Device)=>{setDetail({host:host.id,device:d.id});setCheck(null)};
  const pageTitle=page==='overview'?ui("算力总览"):page==='precision'?ui("训练精度对比"):page==='history'?tr('资源历史','Resource history'):page==='reservations'?tr('资源预约','Resource alerts'):page==='settings'?ui("设置"):page==='assistant'?ui("AI 助手"):ui("算力总览");
  useEffect(()=>{document.title=pageTitle+' · Infra Workbench'},[pageTitle]);
  const copyMachineName=async(name:string)=>{
    try{
      await navigator.clipboard.writeText(name);
      setNotice(tr(`已复制机器名称 ${name}`,`Copied machine name ${name}`));
    }catch{
      setNotice(tr(`无法写入剪贴板，机器名称为 ${name}`,`Could not write to the clipboard. Machine name: ${name}`));
    }
  };
  const hostList=<ClusterSidebar hosts={state.hosts} selected={preferences.hostIds} select={selectHosts} search={hostSearch} setSearch={setHostSearch} category={hostCategory} setCategory={setHostCategory} copyName={copyMachineName} remove={host=>setRemovalHosts([host])} command={cluster=>setClusterPanel({cluster})} terminal={cluster=>setClusterTerminal({cluster})} history={()=>setClusterPanel({cluster:null})} reserve={cluster=>{setGroupDraft({cluster});navigate('reservations')}} resources={cluster=>navigate('history',cluster.host_ids)}/>;
  const desktopTitlebar=useMemo(()=>hasDesktopTitlebar(window),[]);
  const BrandMark=({size}:{size:number})=><svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M9 1v2.5M15 1v2.5M9 20.5V23M15 20.5V23M1 9h2.5M1 15h2.5M20.5 9H23M20.5 15H23" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeOpacity="0.78"/>
    <rect x="3.6" y="3.6" width="16.8" height="16.8" rx="4.4" stroke="currentColor" strokeWidth="1.9"/>
    <path d="M12 6.6c.48 3.1 2.3 4.92 5.4 5.4-3.1.48-4.92 2.3-5.4 5.4-.48-3.1-2.3-4.92-5.4-5.4 3.1-.48 4.92-2.3 5.4-5.4Z" fill="currentColor"/>
  </svg>;
  const header=<header className={desktopTitlebar?'workspace-titlebar desktop-titlebar':'workspace-titlebar'}>
      <div className="brand workspace-brand"><span className="brand-icon"><BrandMark size={24}/></span><div>Infra<span>WORKBENCH</span></div></div>
      <div className="breadcrumb">{ui("工作空间 ")}<ChevronRight size={13}/>{pageTitle}</div>
      {desktopTitlebar&&<div className="desktop-titlebar-space" onMouseDown={event=>{
        if(event.button!==0)return;
        event.preventDefault();
        void desktopTitlebar(event.detail===2?'toggle-maximize':'drag').catch(()=>{});
      }}/>}
      <div className="header-tools"><RefreshIntervalPicker label={ui("刷新间隔")} title={ui("同时调整后台采集与页面刷新频率，设置对本工作台的所有窗口生效")} value={refreshInterval} disabled={busy==='refresh-interval'||!state.server_time} format={seconds=>`${ui("每 ")}${seconds} ${ui(" 秒刷新")}`} onChange={saveRefreshInterval} resetLabel={tr(`恢复默认（${MONITORING_REFRESH_INTERVAL_SECONDS} 秒）`,`Restore default (${MONITORING_REFRESH_INTERVAL_SECONDS}s)`)} onReset={()=>saveRefreshInterval(null)}/>
        <details className="theme-menu" ref={themeMenu}><summary><Palette size={16}/><span>{ui("主题")}</span></summary><div className="theme-options"><h3>{ui("选择界面主题")}</h3><p>{ui("主题偏好由本机后台统一保存")}</p>{THEMES.map(t=><button key={t.id} aria-pressed={preferences.theme===t.id} onClick={()=>{setPreferences(old=>({...old,theme:t.id}));if(themeMenu.current)themeMenu.current.open=false}}>
          <span className="theme-swatches" data-theme={t.id} aria-hidden="true"><i/><i/><i/></span><span><strong>{themeText(t.name)}</strong><small>{t.mode==='light'?ui("亮色"):ui("暗色")} · {themeText(t.description)}</small></span>{preferences.theme===t.id&&<Check size={15}/>}</button>)}</div></details>
        <div className="header-panel-tools"><NotificationCenter events={state.events} rules={state.rules} hosts={state.hosts} tab={notificationTab} setTab={setNotificationTab} notify={notify} busy={!!busy} toggleNotifications={toggleNotifications} removeRule={id=>act('rule',()=>api('/rules/'+encodeURIComponent(id),'DELETE'))} locate={locateEvent}/><button data-tour="assistant" className={'assistant-toggle'+(assistantOpen?' active':'')} aria-label={ui("AI 助手")} title={assistantOpen?ui("收起 AI 助手"):ui("展开 AI 助手")} aria-expanded={assistantOpen} aria-controls="infra-assistant-panel" onClick={()=>setAssistantOpen(value=>!value)}><Sparkles size={17}/><span>{ui("AI 助手")}</span></button></div>
      </div>{desktopTitlebar&&<DesktopWindowControls invoke={desktopTitlebar}/>}</header>;
  return <WorkspaceLayout desktopTitlebar={!!desktopTitlebar} assistantWidth={assistantWidth} onClickCapture={event=>{
    if(deviceOverview&&event.target instanceof Element&&!event.target.closest('#device-overview,[aria-controls="device-overview"]'))setDeviceOverview(false);
  }}>
    {header}
    <aside className="sidebar">
      <div className="nav-label">{ui("工作台")}</div><nav>{[["overview",ui("算力总览"),LayoutGrid],["reservations",tr("资源预约","Resource alerts"),CalendarClock],["history",tr("资源历史","Resource history"),History],["precision",ui("精度对比"),ChartLine],["settings",ui("设置"),Settings]].map(([key,label,Icon])=><button key={String(key)} title={String(label)} aria-label={String(label)} className={page===key?'active':''} aria-current={page===key?'page':undefined} onClick={()=>navigate(String(key) as Page)}><Icon size={18}/>{String(label)}{key==='reservations'&&pendingReservations>0&&<span className="nav-count">{pendingReservations}</span>}</button>)}</nav>
      <div className="sidebar-hosts" data-tour="hosts">{hostList}</div>
      <div className="sidebar-bottom"><div className={'agent'+(error?' disconnected':'')} role="status" tabIndex={0} title={ui("机器选择保存在本机后台，其他窗口会同步更新。通过 SSH 连接远端机器，无需远端常驻 Agent。")}><i aria-hidden="true"/>{isDemo?tr("演示数据","Demo data"):ui("本地服务")}{error?ui("未连接"):ui("已连接")}</div></div>
    </aside>
    <main onClick={clearDeviceSelection}><DesktopUpdateNotification openSettings={()=>navigate('settings')}/>{workspaceError&&<div role="alert" className="assistant-error">{ui("工作空间状态同步失败，正在重试；未保存时请勿关闭页面。")}</div>}
    {!isDemo&&page==='overview'&&state.hosts.length>0&&!notice&&(!assistantOpen||assistantWidth>0)&&<GitHubStarPrompt key={state.hosts.map(host=>host.id).join(',')}/>}
    {preferences.theme==='frieren'&&<JourneyArt/>}
    <div className="content"><div className="page-heading" hidden={page==='history'}><div><div className="eyebrow">COMPUTE / {page==='precision'?'PRECISION COMPARE':page==='overview'?'OVERVIEW':page==='history'?'RESOURCE HISTORY':page==='reservations'?'RESERVATIONS':page==='settings'?'SETTINGS':page==='assistant'?'AI ASSISTANT':'OVERVIEW'}</div><h1>{pageTitle}<span className="heading-dot"/></h1><p>{page==='precision'?ui("跨机器读取训练日志，自动提取指标并按真实步数对齐。"):page==='history'?tr("查看各时段空闲设备和机器数量，未知数据单独标记。","View idle devices and machines over time, with missing data shown separately."):page==='reservations'?tr("单台、指定多台或集群任意几台连续空闲后提醒。","Receive an alert when a machine or group stays available."):page==='settings'?ui("管理模型接口、外部 Agent 接入和邮件通知。"):page==='assistant'?ui("查找多台机器上的任务与会话，了解资源发生了哪些变化。"):tr(`全部 ${state.hosts.length} 台机器的资源概况 · 左侧勾选用于查看详情和批量删除`,`Resources across ${state.hosts.length} machines · Select in the sidebar for details or removal`)}</p></div><div className="page-heading-actions"><TunnelManagerButton hosts={state.hosts}/><button className="primary" onClick={()=>isDemo?setNotice(tr("演示模式不接入真实机器或凭据，请退出演示后配置。","The demo does not accept real machines or credentials. Exit demo to configure them.")):setAdding(true)}><Plus size={17}/>{ui("添加机器")}</button><button className="secondary machine-delete-action" aria-label={ui("删除机器")} title={scope.length?tr(`删除选中的 ${scope.length} 台机器`,`Delete ${scope.length} selected machines`):ui("请先在左侧勾选机器")} disabled={scope.length===0} onClick={()=>setRemovalHosts([...scope])}><Trash2 size={15}/>{ui("删除机器")}{scope.length>0&&<span className="machine-delete-count">{scope.length}</span>}</button></div></div>
    <details data-tour="hosts" className="mobile-hosts" ref={mobileHosts}><summary><Server size={15}/>{ui("选择机器 · ")}{scope.length} / {state.hosts.length}</summary>{hostList}</details>
    {error&&<div className="error-banner">{error}</div>}
    {precisionMounted&&<div className="precision-cache" hidden={page!=='precision'}><RenderBoundary fallback={<RenderFailure title={tr("精度对比暂时无法打开","Precision comparison could not open")}/>}><React.Suspense fallback={<p role="status">{ui("正在加载精度对比…")}</p>}><PrecisionCompare hosts={state.hosts}/></React.Suspense></RenderBoundary></div>}
    {page==='overview'&&<><div className="stats" data-tour="overview" aria-label={ui("全部机器资源总览")}><div className="overview-stat"><span>{tr("在线机器","Online machines")}<Server size={16}/></span><strong>{online}<small>/ {state.hosts.length}</small></strong><p><i className="dot"/>{ui("在线 / 已添加")}</p><span className="stat-action">{allMachinesSelected?ui("清空机器选择"):ui("查看全部机器")} <ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label={allMachinesSelected?ui("清空机器选择"):ui("查看全部机器")} aria-pressed={allMachinesSelected} disabled={!state.hosts.length} title={allMachinesSelected?ui("已全选，点击清空机器选择"):ui("全选机器并清除详情筛选")} onClick={()=>showMachines(allMachinesSelected?[]:null)}/></div><div className="overview-stat"><span>{ui("加速设备")}<Cpu size={16}/></span><strong>{devices.length}<small>{ui("个设备")}</small></strong><p>{devices.filter(d=>d.kind==='NPU').length} NPU <b>·</b> {devices.filter(d=>d.kind==='GPU').length} GPU</p><span className="stat-action">{deviceOverview?ui("收起设备概览"):ui("按类型与型号查看")} <ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label={deviceOverview?ui("收起加速设备概览"):ui("展开加速设备概览")} aria-expanded={deviceOverview} aria-controls="device-overview" onClick={()=>setDeviceOverview(!deviceOverview)}/></div><div className="overview-stat"><span title={ui("根据当前设备数量、类型、显存和进程条件，在全部机器中统计，不受左侧选择影响")}>{ui("全局符合条件")}<ShieldCheck size={16}/></span><strong className="teal">{globalCandidates.length}<small>{ui("台机器")}</small></strong><p>{ui("至少 ")}{count} {ui(" 个")}{resourceKind==='全部'?ui("设备"):resourceKind} {ui(" · 每个 ≥ ")}{minimum} GiB</p><span className="stat-action">{ui("查看符合条件的机器 ")}<ArrowUpRight size={13}/></span><button className="reservation-stat-link" aria-label={ui("查看全局符合条件的机器")} disabled={!globalCandidates.length} title={ui("在全部机器中按寻找栏条件匹配，点击展示结果")} onClick={()=>showMatches(globalCandidates)}/></div><div className="reservation-stat"><span>{ui("我的预约")}<CalendarClock size={16}/></span><strong>{pendingReservations}<small>{ui("条")}</small></strong><p>{tr(`${reservationMachines} 台机器 · ${pendingReservations} 条等待中`,`${reservationMachines} machines · ${pendingReservations} pending`)}</p><button className="reservation-stat-link" aria-label={tr(`查看卡预约，${pendingReservations} 条等待中`,`View availability alerts: ${pendingReservations} pending`)} title={ui("仅统计尚未满足条件的预约。点击查看和管理全部预约；预约为空闲提醒，不锁定设备。")} onClick={()=>navigate('reservations')}/></div></div>
      {deviceOverview&&<section id="device-overview" className="device-overview" aria-label={ui("加速设备分类概览")}><div className="section-heading"><h2>{ui("全局加速设备 ")}<span>{devices.length} {ui(" 个设备 ")}</span></h2><button className="text-button" onClick={()=>setDeviceOverview(false)}>{ui("收起 ")}<X size={14}/></button></div><p>{ui("按类型和型号查看对应机器；数量包含最近采集记录，请以机器在线状态为准。")}</p><div className="device-groups">{deviceGroups.map(group=><button key={group.key} aria-label={tr(`查看 ${group.kind} ${group.name} 对应机器`,`View machines with ${group.kind} ${group.name}`)} onClick={()=>showMachines(group.hosts.map(h=>h.id),group.kind)}><span className="badge">{group.kind}</span><span className="device-group-name">{group.name}</span><strong>{group.total} {ui(" 个设备 ")}<small>· {group.hosts.length} {ui(" 台机器")}</small></strong><ArrowUpRight size={15}/></button>)}</div>{!deviceGroups.length&&<p>{ui("尚未采集到设备，连接机器后会在这里显示。")}</p>}</section>}
      <section className="finder" data-tour="finder"><div className="finder-label"><Search size={18}/><div>{ui("寻找训练资源")}<small>{selectedScope?tr(`仅搜索所选 ${scope.length} 台机器`,`Search ${scope.length} selected machines only`):tr(`搜索全部 ${state.hosts.length} 台机器 · 不受左侧勾选影响`,`Search all ${state.hosts.length} machines · Independent of sidebar selection`)}</small></div></div><label>{ui("设备类型")}<select aria-label={ui("寻找设备类型")} value={resourceKind} onChange={e=>setResourceKind(e.target.value)}>{['全部','NPU','GPU'].map(kind=><option key={kind} value={kind}>{kind==='全部'?ui(kind):kind}</option>)}</select></label><label>{ui("需要设备数")}<select aria-label={ui("需要设备数")} value={count} onChange={e=>setCount(+e.target.value)}>{Array.from({length:Math.max(8,count,...state.hosts.map(h=>h.snapshot.devices.length))},(_,i)=>i+1).map(i=><option key={i} value={i}>{i} {ui(" 个")}</option>)}</select></label><label>{ui("剩余显存")}<div className="input-unit"><input aria-label={ui("每个设备剩余显存")} type="number" min="0" max="100000" value={minimum} onChange={e=>setMinimum(Math.max(0,+e.target.value))}/><span>GiB</span></div></label><label className="checkbox-label"><input type="checkbox" checked={clear} onChange={e=>setClear(e.target.checked)}/>{ui("无可见计算进程")}</label><label className="checkbox-label"><input type="checkbox" aria-label={ui("仅在所选机器中寻找")} checked={selectedScope} onChange={e=>setSelectedScope(e.target.checked)}/>{ui("仅在所选机器中寻找")}</label><div className="match-count"><strong>{candidates.length}</strong><span>{ui("台符合条件")}{selectedScope?ui("（所选范围）"):ui("（全局）")}</span><button className="secondary" aria-label={ui("查看匹配机器")} disabled={!candidates.length} onClick={()=>showMatches(candidates)}>{ui("查看机器 ")}<ArrowUpRight size={15}/></button></div></section>
    </>}
    {page==='overview'&&<div className="two-columns"><div className="machines">
      <div className="section-heading machine-section-heading">
        <div className="machine-section-title">
          <h2>{ui("所选机器详情")}<span>{shown.length} {ui(" 台机器")}</span></h2>
          {refreshStates.length>0&&<span className="machine-refresh-progress" role="status">{tr('手动刷新','Manual refresh')} {refreshStates.filter(value=>value==='done'||value==='error').length}/{refreshStates.length} · {tr('失败','Failed')} {refreshStates.filter(value=>value==='error').length}</span>}
        </div>
        <div className="machine-section-tools">
          <div className="segmented">{['全部','NPU','GPU'].map(f=><button className={filter===f?'chosen':''} key={f} onClick={()=>setFilter(f)}>{f==='全部'?ui(f):f}</button>)}</div>
          {scope.length>0&&<button className="secondary compact" aria-label={tr('刷新所选机器','Refresh selected machines')} title={collectingHosts.length?tr('刷新所选机器','Refresh selected machines'):tr('所选机器均已暂停采集','Collection is paused on all selected machines')} disabled={!collectingHosts.length||collectionBusy||refreshInProgress} onClick={()=>void refreshMany(scope)}><RefreshCw size={15} className={refreshInProgress?'spin':''}/>{tr('刷新','Refresh')}</button>}
          {scope.length>1&&!isDemo&&<details className="machine-batch-menu" ref={machineActions}>
            <summary className="secondary compact">{tr('批量操作','Batch actions')}<ChevronDown size={14}/></summary>
            <div>
              <p>{tr(`已选 ${scope.length} 台机器`,`${scope.length} machines selected`)}</p>
              <button disabled={collectionBusy||!collectingHosts.length} onClick={()=>changeBatchCollection(collectingHosts,true)}><Pause size={15}/>{tr('批量暂停采集','Batch pause collection')}<span className="badge">{collectingHosts.length}</span></button>
              <button disabled={collectionBusy||!pausedHosts.length} onClick={()=>changeBatchCollection(pausedHosts,false)}><Play size={15}/>{tr('批量恢复采集','Batch resume collection')}<span className="badge">{pausedHosts.length}</span></button>
              <hr/>
              <button onClick={()=>{setGroupDraft({hostIds:scope.map(h=>h.id)});navigate('reservations')}}><CalendarClock size={15}/>{tr('预约所选机器','Reserve selected machines')}</button>
              <button onClick={()=>navigate('history',scope.map(h=>h.id))}><History size={15}/>{tr('查看所选机器历史','View selected machine history')}</button>
            </div>
          </details>}
        </div>
      </div>
      {shown.length===0&&<div className="empty"><Server size={32}/><h3>{state.hosts.length===0?ui("连接第一台机器"):scope.length===0?ui("选择要查看的机器"):ui("没有符合设备类型的机器")}</h3><p>{state.hosts.length===0?ui("从本机 SSH 配置选择，或输入主机和账号密码。"):ui("在机器列表中点击名称单选，或勾选多台机器。")}</p>{state.hosts.length===0?<button className="primary" onClick={()=>isDemo?setNotice(tr("演示模式不接入真实机器或凭据，请退出演示后配置。","The demo does not accept real machines or credentials. Exit demo to configure them.")):setAdding(true)}><Plus size={16}/>{ui("添加机器")}</button>:<button className="secondary" onClick={()=>showMachines(null)}>{ui("显示全部机器")}</button>}</div>}
      {shown.map(host=>{
        const snapshot=host.snapshot,ids=selected[host.id]||EMPTY_SELECTION;
        const logins=host.ssh_logins;
        const hasDefaultSSHAccount=!logins||logins.accounts.some(account=>account.id===logins.default_account_id);
        const defaultSSHAvailable=hasDefaultSSHAccount&&(host.auth==='key'||host.ssh_password?.password_saved===true||
          (host.auth==='password_session'&&snapshot.status==='online'));
        const sudoVerified=host.sudo?.enabled&&host.sudo.status==='ready';
        const sudoLabel=sudoVerified?tr('sudo 已验证','sudo verified'):'sudo';
        const SudoIcon=sudoVerified?ShieldCheck:Shield;
        const openSudo=()=>isDemo?setNotice(tr("演示模式不接入真实机器或凭据，请退出演示后配置。","The demo does not accept real machines or credentials. Exit demo to configure them.")):setSudoHost(host);
        return <MachineView key={host.id} dependencies={[host,ids,filter,minimum,clear,count,port,resourceKind,busy,locale,refreshing[host.id],collectionBusy,exportingSSH]} render={()=> <section className="machine" data-tour-panel={host.id==='demo-gpu-free'?'preflight':undefined} key={host.id} aria-label={ui("机器详情 ")+host.target}>
        <div className="machine-heading"><span className="machine-icon"><Server size={20}/></span><div className="machine-name"><h3>{host.alias||host.target}<Badge tone={!host.collection?.paused&&snapshot.fresh?'green':'amber'}>{host.collection?.paused?tr('采集已暂停','Collection paused'):snapshot.fresh?ui("在线"):snapshot.status==='error'?(snapshot.sections?.system?.fresh?tr("部分采集失败","Partial collection failure"):ui("采集失败")):snapshot.status==='connecting'?ui("连接中"):ui("数据过期")}</Badge></h3><p>{host.alias&&<>{host.target} · </>}{machineSummary(snapshot.devices)} <span>·</span> SSH {host.auth==='password_session'?ui("密码会话"):ui("免密连接")}</p></div><button data-tour={host.id==='demo-gpu-busy'?'reservation':undefined} className="ssh-open" aria-label={ui("预约 ")+host.target+ui(" 的卡")} title={ui("预约这台机器的卡")} onClick={()=>setReservationDraft({hostId:host.id,devices:ids.filter(id=>snapshot.devices.some(device=>device.id===id)),minimum})}><CalendarClock size={15}/><span>{ui("预约")}</span></button><button className="ssh-open" onClick={()=>navigate('history',[host.id])}>{tr("历史","History")}</button><button className="ssh-open" disabled={isDemo} onClick={()=>setAliasHost(host)}>{tr("别名","Alias")}</button><VSCodeButton host={host} disabled={isDemo}/><SSHTunnelButton host={host}/><button data-tour={host.id==='demo-gpu-busy'?'services':undefined} className="ssh-open" onClick={()=>setServiceHost(host)}>{tr("服务","Services")}</button><div className="ssh-account-tool">
          <button data-tour={host.id==='demo-gpu-busy'?'files':undefined} className="ssh-open" aria-label={ui("浏览 ")+host.target+ui(" 文件")} onClick={()=>openSSHWindow(host,'files')}><Database size={15}/><span>{ui("文件")}</span></button>
          {!isDemo && host.ssh_logins && host.ssh_logins.accounts.length > 1 && <button className="ssh-open" aria-label={tr("选择文件账号","Choose file account")} title={tr("选择文件账号","Choose file account")} onClick={()=>setSSHAccountChoice({host,tool:'files'})}><ChevronDown size={14}/></button>}
        </div><div className="ssh-account-tool">
          <button data-tour={host.id==='demo-gpu-busy'?'terminal':undefined} className="ssh-open" aria-label={ui("打开 ")+host.target+ui(" 终端")} onClick={()=>openSSHWindow(host,'terminal')}><Terminal size={15}/><span>{ui("终端")}</span></button>
          {!isDemo && host.ssh_logins && host.ssh_logins.accounts.length > 1 && <button className="ssh-open" aria-label={tr("选择终端账号","Choose terminal account")} title={tr("选择终端账号","Choose terminal account")} onClick={()=>setSSHAccountChoice({host,tool:'terminal'})}><ChevronDown size={14}/></button>}
        </div><button className={'sudo-button'+(defaultSSHAvailable?' enabled':'')} aria-label={host.target+' '+tr("SSH 账号","SSH accounts")} onClick={()=>isDemo?setNotice(tr("演示模式不接入真实机器或凭据，请退出演示后配置。","The demo does not accept real machines or credentials. Exit demo to configure them.")):setSSHAccountsHost(host)}><KeyRound size={15}/><span>{tr("SSH 账号","SSH accounts")}{host.ssh_logins && ' '+host.ssh_logins.accounts.length}</span></button><button className={'sudo-button'+(sudoVerified?' enabled':'')} title={ui("设置 sudo 进程详情")} aria-label={host.target+ui(" sudo 设置")} aria-description={sudoLabel} onClick={openSudo}><SudoIcon size={15}/><span>{sudoLabel}</span></button><button className="icon-button" aria-label={ui("刷新 ")+host.target} disabled={host.collection?.paused||refreshing[host.id]==='running'||refreshing[host.id]==='waiting'} onClick={()=>refreshHost(host)}><RefreshCw size={16} className={refreshing[host.id]==='running'?'spin':''}/></button><button className="secondary compact remove-host-button" aria-label={ui("移除机器 ")+host.target} title={ui("移除机器")} onClick={()=>setRemovalHosts([host])}><Trash2 size={15}/><span>{ui("移除")}</span></button></div>
        <div className="collection-summary">
          <button className="secondary compact" disabled={isDemo||collectionBusy} onClick={()=>setCollectionPaused([host],!host.collection?.paused)}>{host.collection?.paused?tr('恢复采集','Resume collection'):tr('暂停采集','Pause collection')}</button>
          {host.collection?.paused&&<span role="status">{tr('采集已暂停；正在进行的采集结束后停止更新，终端不受影响','Collection paused; an active sample may finish. Terminals remain connected.')}</span>}
          {refreshing[host.id]&&<span role="status">{refreshing[host.id]==='waiting'?tr('等待刷新','Waiting to refresh'):refreshing[host.id]==='running'?(host.collection?.status==='collecting'?tr('正在采集','Collecting'):tr('正在刷新或等待采集','Refreshing or waiting to collect')):refreshing[host.id]==='done'?tr('手动刷新已完成','Manual refresh completed'):refreshing[host.id]==='error'?tr('手动刷新失败','Manual refresh failed'):''}</span>}
          {host.collection?.duration_seconds!=null&&<details><summary>{tr('采集统计','Collection statistics')}</summary>
            <p>{host.collection.status==='queued'?tr('等待采集','Queued'):host.collection.status==='collecting'?tr('正在采集','Collecting'):''}</p>
            <p>{tr('上次耗时','Last duration')} {host.collection.duration_seconds.toFixed(2)} s · {tr('排队','Queue')} {(host.collection.queue_seconds??0).toFixed(2)} s · {tr('探针返回','Probe response')} {((host.collection.response_bytes??0)/1024).toFixed(1)} KiB</p>
            <p>{tr('统计自后台启动以来；字节数是探针命令与输出的 UTF-8 大小，不含 SSH 开销及 sudo 补充请求。','Since backend startup; bytes measure UTF-8 probe commands and output, excluding SSH overhead and sudo enrichment.')}</p>
            <p>{tr('实际采集间隔','Actual sample interval')}: {host.collection.actual_interval_seconds?.toFixed(2)??'—'} s · {tr('次数','Samples')}: {host.collection.samples} · {tr('本次发送','Sent this sample')}: {host.collection.request_bytes} B · {tr('累计返回','Total received')}: {host.collection.total_response_bytes} B</p>
          </details>}
        </div>
        <SystemSummary system={snapshot.system} fresh={snapshot.sections?.system?.fresh??snapshot.fresh} collectedAt={snapshot.sections?.system?.collected_at??snapshot.collected_at}/>
        {snapshot.error&&<div className="connection-error"><p>{snapshot.error_stage==='parse'?ui("SSH 已连接 · 设备信息解析失败："):snapshot.error_stage==='probe'?ui("SSH 已连接 · 远端采集失败："):''}{snapshot.error}</p>{snapshot.error_stage==='connection'?<button className="text-button" onClick={()=>isDemo?setNotice(tr("演示模式不接入真实机器或凭据，请退出演示后配置。","The demo does not accept real machines or credentials. Exit demo to configure them.")):setAdding(true)}>{ui("检查连接凭据 ")}<ArrowUpRight size={13}/></button>:<button className="text-button" disabled={host.collection?.paused||refreshing[host.id]==='running'||refreshing[host.id]==='waiting'} onClick={()=>refreshHost(host)}>{ui("重试采集 ")}<RefreshCw size={13}/></button>}</div>}
        {snapshot.devices.length>0&&<div className="device-table-scroll"><table className="device-table"><thead><tr><th>{ui("选择")}</th><th>{ui("设备")}</th><th>{ui("状态")}</th><th>{ui("显存已用 / 总量")}</th><th>{ui("计算利用率")}</th><th>{ui("温度")}</th><th>{ui("占用用户 / PID")}</th></tr></thead><tbody>
          {snapshot.devices.filter(d=>filter==='全部'||d.kind===filter).map(d=>{const suitable=snapshot.fresh&&isEligible(d,minimum,clear),occupied=d.processes.length>0;
            return <tr key={d.id} className={!snapshot.fresh?'stale':''} onClick={()=>inspect(host,d)}>
              <td onClick={e=>e.stopPropagation()}><input type="checkbox" aria-label={ui("选择 ")+host.target+ui(" 设备 ")+displayId(d)} checked={ids.includes(d.id)} onChange={()=>toggle(host.id,d.id)}/></td>
              <td><button data-tour={occupied?"device":undefined} className="device-open" aria-label={host.target+' '+d.kind+' '+displayId(d)+ui(" 详情")} onClick={e=>{e.stopPropagation();inspect(host,d)}}><span className="device-number">{d.kind} {displayId(d).padStart(2,'0')}</span>{(d.physical_id!=null||d.id.startsWith('chip:'))&&<small>{ui("卡 ")}{d.card_id} {ui(" / 芯片 ")}{d.chip_id}</small>}</button></td>
              <td><span className={'device-pill '+(!snapshot.fresh?'muted':d.health==='Alarm'?'danger':occupied?'amber':suitable?'green':'muted')}><i/>{!snapshot.fresh?ui("信息过期"):d.health==='Alarm'?ui("设备异常"):!d.processes_known?ui("进程未知"):occupied?ui("进程占用"):suitable?ui("满足条件"):ui("显存不足")}</span>{d.health==='Warning'&&<span className="health-warning" title={ui("仅提示，不影响资源推荐")}>Warning</span>}</td>
              <td className="memory-cell"><span>{gib(d.memory_used)} <small>/ {gib(d.memory_total)} GiB</small></span><div className={'meter '+(occupied?'busy-meter':'')}><i style={{width:Math.min(100,d.memory_used/d.memory_total*100)+'%'}}/></div></td>
              <td className="numeric">{d.utilization??'—'}<small>%</small></td><td className="numeric">{d.temperature??'—'}<small>°C</small></td><td><button className="process-link process-summary" aria-label={host.target+ui(" 设备 ")+displayId(d)+ui(" 占用进程")} onClick={e=>{e.stopPropagation();inspect(host,d)}}><span><strong>{d.processes.length?[...new Set(d.processes.map(p=>p.user||ui("用户未知")))].join(', '):d.processes_known?ui("无计算进程"):ui("未知 ")}</strong>{d.processes.length>0&&<small>PID {d.processes.slice(0,3).map(p=>p.pid).join(', ')}{d.processes.length>3?'…':''} · {d.processes.length} {ui(" 个")}</small>}</span><ChevronRight size={12}/></button></td>
            </tr>})}
        </tbody></table></div>}
        <div className="machine-footer"><span><i className={'dot '+(!snapshot.fresh?'muted-dot':'')}/>{snapshot.collected_at?ui("最近采集 ")+clock(snapshot.collected_at):ui("尚未采集")}{snapshot.fresh&&matches(host).length>=count&&<em>{ui("符合当前资源需求")}</em>}</span><div className="machine-ssh-actions">
          <button className="text-button" disabled={isDemo||exportingSSH} title={isDemo?tr('演示模式不会写入 SSH 配置','Demo mode does not write SSH config'):tr('写入本机 ~/.ssh/config','Write to local ~/.ssh/config')} onClick={()=>void addToSSHConfig(host)}>{tr('添加到 SSH 配置','Add to SSH config')}</button>
          <button className="text-button" onClick={()=>navigator.clipboard.writeText('ssh '+host.target).then(()=>setNotice(ui("SSH 命令已复制"))).catch(()=>setNotice(ui("复制失败，请手动使用 ssh ")+host.target))}><Terminal size={13}/>{ui("复制 SSH")}</button>
        </div></div>
        {ids.length>0&&<div className="selection-bar"><span>{ui("已选设备 ")}{ids.map(id=>displayId(snapshot.devices.find(d=>d.id===id))).join(', ')}</span><label>{ui("端口")}<input type="number" min="1" max="65535" aria-label={ui("训练端口")} value={port} onChange={e=>setPort(+e.target.value)}/></label><button className="secondary" disabled={!!busy} onClick={()=>act('check',async()=>{setCheck(await api('/preflight','POST',resourceBody(host)));setDetail({host:host.id,device:ids[0]})})}>{ui("训练前检查")}</button><button className="primary compact" disabled={!!busy} onClick={()=>act('rule',async()=>{await api('/rules','POST',resourceBody(host));setNotice(ui("监控已添加，可在右上角通知中心管理。"));setNotificationTab('rules')})}><Radio size={14}/>{ui("监控所选")}</button><button className="primary compact" disabled={!!busy||!snapshot.fresh} onClick={()=>setReservationDraft({hostId:host.id,devices:ids,minimum})}><CalendarClock size={14}/>{ui("预约所选")}</button></div>}
      </section>}/>})}
      <div className="footnote"><CircleHelp size={14}/>{ui("低利用率不代表空闲。筛选结果反映资源指标，不代表资源授权或预留。")}</div>
    </div></div>}
    {page==='settings'&&(isDemo?<div data-tour-panel="settings"><LanguageSettings/><DemoSettings/></div>:<RenderBoundary fallback={<RenderFailure title={tr("设置暂时无法打开","Settings could not open")}/>}><React.Suspense fallback={<p role="status">{ui("正在加载设置…")}</p>}><SettingsPage/></React.Suspense></RenderBoundary>)}

    {page==='history'&&<ResourceHistory hosts={state.hosts} initialHostIds={historyHostIds}/>}
    {page==='reservations'&&<GroupReservations hosts={state.hosts} draft={groupDraft} onDraft={setGroupDraft} refreshKey={isDemo?state.events.length:undefined}/>}
    {page==='reservations'&&<Reservations items={state.reservations} create={()=>setReservationDraft({})} edit={item=>setReservationDraft(draftFromReservation(item,true))} rebook={item=>setReservationDraft(draftFromReservation(item,false))} locate={locateReservation} remove={async(id)=>{await api('/reservations/'+id,'DELETE');await load()}} toggleNotifications={toggleNotifications} notify={notify}/>}
    <footer className="page-footer"><span><ShieldCheck size={13}/>{tr('私钥和密码保存在本机','Private keys and passwords stay on this computer')}</span><span aria-label={tr("软件版本","Software version")}>v<DesktopVersion/> · LOCAL WORKSPACE / {new Date().getFullYear()}</span></footer></div></main>
    <RenderBoundary fallback={assistantOpen?<RenderFailure title={tr("AI 助手暂时无法打开","AI assistant could not open")} floating close={()=>setAssistantOpen(false)}/>:null}><React.Suspense fallback={<p role="status">{ui("正在加载 AI 助手…")}</p>}><AssistantWindow open={assistantOpen} onClose={()=>setAssistantOpen(false)} onDockWidthChange={setAssistantWidth} selectedHostIds={scope.map(host=>host.id)} openSettings={()=>{setAssistantOpen(false);navigate('settings',undefined,modelSettingsHash)}} locate={(hostId,devices)=>{if(!state.hosts.some(host=>host.id===hostId)){setNotice(ui("这台机器已不在当前列表中。"));return}showMachines([hostId]);setSelected({[hostId]:devices});navigate('overview')}} openTerminal={hostId=>{const host=state.hosts.find(host=>host.id===hostId);if(host)openSSHWindow(host,'terminal',host.ssh_logins?.default_account_id);else setNotice(ui("这台机器已不在当前列表中。"))}}/></React.Suspense></RenderBoundary>
    {clusterPanel&&<ClusterPanel openTerminalBatch={id=>{setClusterPanel(null);setClusterTerminal({cluster:null,batchId:id})}} cluster={clusterPanel.cluster} hosts={state.hosts} close={()=>setClusterPanel(null)} terminal={host=>{
      const current=state.hosts.find(item=>item.id===host.id);
      if(current)openSSHWindow(current,'terminal');
    }}/>}
    {clusterTerminal&&<TerminalBoundary close={closeClusterTerminal}><React.Suspense fallback={<div className="terminal-loading" role="status">{ui("正在加载终端…")}</div>}><ClusterTerminalWorkspace cluster={clusterTerminal.cluster} batchId={clusterTerminal.batchId} hosts={state.hosts} close={closeClusterTerminal}/></React.Suspense></TerminalBoundary>}
    <TerminalBoundary close={()=>setTerminalRequest(null)}><React.Suspense fallback={<div className="terminal-loading" role="status">{ui("正在加载终端…")}</div>}>{terminalRequest&&(isDemo?<DemoTerminal hostId={terminalRequest.host.id} close={()=>setTerminalRequest(null)} openFiles={()=>{const host=state.hosts.find(h=>h.id===terminalRequest.host.id);if(host)openSSHWindow(host,'files',undefined,'/demo')}}/>:<TerminalDock request={terminalRequest} hosts={state.hosts} onDirectory={(hostId,path,accountId)=>{const host=state.hosts.find(host=>host.id===hostId);if(host)openSSHWindow(host,'files',accountId,path)}}/>)}</React.Suspense></TerminalBoundary>
    {notice&&<div role="status" className="toast"><Check size={17}/>{notice}<button className="icon-button" aria-label={ui("关闭提示")} onClick={()=>setNotice('')}><X size={15}/></button></div>}
    {aliasHost&&<HostAliasDialog host={aliasHost} close={()=>setAliasHost(null)} saved={()=>{void api("/state").then(setState).catch(e=>setNotice(e.message))}}/>}
    {adding&&<AddMachine close={()=>setAdding(false)} imported={async ids=>{setPreferences(old=>({...old,hostIds:old.hostIds===null?null:[...new Set([...old.hostIds,...ids])]}));await load()}} connected={async(message,hostId)=>{if(hostId)setPreferences(old=>({...old,hostIds:old.hostIds===null?null:[...new Set([...old.hostIds,hostId])]}));setNotice(message);setAdding(false);await load()}}/>}
    {reservationDraft&&<ReservationDialog countEnabled={state.reservation_modes?.includes('count')} hosts={state.hosts} draft={reservationDraft} close={()=>setReservationDraft(null)} openSettings={()=>{setReservationDraft(null);navigate('settings')}} save={async(body)=>{await api(reservationDraft.editingId?'/reservations/'+encodeURIComponent(reservationDraft.editingId):'/reservations',reservationDraft.editingId?'PATCH':'POST',body);await load();setNotice(reservationDraft.editingId?ui("预约已更新，按新条件重新计时。"):ui("预约已保存；所选设备连续空闲后会提醒一次。"))}}/>}
    {serviceHost&&state.hosts.some(h=>h.id===serviceHost.id)&&<ServicePanel host={serviceHost} close={()=>setServiceHost(null)}/>}
    {fileHost&&<RenderBoundary fallback={<RenderFailure title={tr("文件浏览器暂时无法打开","File browser could not open")} floating close={()=>setFileHost(null)}/>}><React.Suspense fallback={<p role="status">{ui("正在加载文件浏览器…")}</p>}><FileBrowser onTerminal={(hostId,cwd,accountId)=>{const host=state.hosts.find(host=>host.id===hostId);if(host)openSSHWindow(host,'terminal',accountId,cwd)}} initialPath={fileHost.path} host={fileHost.host} requestId={fileHost.requestId} hosts={state.hosts} close={()=>setFileHost(null)}/></React.Suspense></RenderBoundary>}
    {sshAccountsHost && <SSHAccountsDialog key={sshAccountsHost.id} host={sshAccountsHost} close={()=>setSSHAccountsHost(null)} updated={async()=>{await load()}}/>}
    {sshAccountChoice?.host.ssh_logins && <SSHAccountPicker
      host={{...sshAccountChoice.host, ssh_logins: sshAccountChoice.host.ssh_logins}}
      tool={sshAccountChoice.tool}
      close={()=>setSSHAccountChoice(null)}
      open={(id, saved)=>{
        const {host, tool} = sshAccountChoice;
        setSSHAccountChoice(null);
        openSSHWindow(saved ? {...host, ssh_logins: saved} : host, tool, id);
        if (saved) void load();
      }}
    />}
    {removalHosts.length>0&&<RemoveHostDialog hosts={removalHosts} close={()=>setRemovalHosts([])} remove={removeHost}/>}
    {sudoHost&&<SudoModal key={sudoHost.id} host={sudoHost} close={()=>setSudoHost(null)} updated={async()=>{await load()}} notify={setNotice}/>}
    {detail&&<DeviceDrawerFrame onClose={()=>{setDetail(null);setCheck(null)}}><section className="drawer" role="dialog" aria-label={ui("设备详情")} onClick={e=>e.stopPropagation()}><div className="drawer-heading"><div className="eyebrow">DEVICE INSPECTOR</div><button className="icon-button" aria-label={ui("关闭设备详情")} onClick={()=>{setDetail(null);setCheck(null)}}><X size={20}/></button></div><h2>{detailHost?.target}</h2><p className="subtle">{detailDevice?.kind} {detailDevice?displayId(detailDevice):''} · {detailDevice?.name}{detailDevice?.physical_id!=null&&tr(` · 卡 ${detailDevice.card_id} / 芯片 ${detailDevice.chip_id}`,` · Card ${detailDevice.card_id} / chip ${detailDevice.chip_id}`)}</p>{detailDevice&&<><div className="detail-metrics"><div>{ui("剩余显存")}<strong>{gib(detailDevice.memory_free)} <small>GiB</small></strong></div><div>{ui("计算利用率")}<strong>{detailDevice.utilization??'—'}<small>%</small></strong></div></div><h3>{ui("计算进程 ")}<Badge>{detailDevice.processes.length}</Badge></h3>{!detailDevice.processes_known?<div className="error-banner">{ui("进程信息无法完整读取，不能确认空闲。")}</div>:detailDevice.processes.length===0?<p className="subtle">{ui("采集工具未报告可见计算进程。")}</p>:detailDevice.processes.map(p=><React.Fragment key={p.pid}>{p.details_collected_at&&<p className="subtle">{tr("进程详情采样：","Process details sampled: ")}{clock(p.details_collected_at)}</p>}<ProcessDetails process={p} onCopy={text=>navigator.clipboard.writeText(text).then(()=>setNotice(ui("已复制"))).catch(()=>setNotice(ui("复制失败，可手动选择文本复制")))}/></React.Fragment>)}<button className="secondary wide" onClick={()=>toggle(detail.host,detail.device)}><Check size={15}/>{(selected[detail.host]||[]).includes(detail.device)?ui("取消选择此设备"):ui("选择此设备")}</button></>}{check&&<div className={'check-result '+(check.status==='PASS'?'pass':'')}><h3><ShieldCheck size={18}/>{ui("检查结果：")}{check.status}</h3>{check.reasons.map((r,i)=><p key={i}>{r}</p>)}</div>}<div className="drawer-note">{ui("数据来自最近一次采集。进程不可见时会明确标记，检查结果不构成资源预留。")}</div></section></DeviceDrawerFrame>}
    {!isDemo&&<FirstRunGuide ready={state.server_time>0} hasHosts={state.hosts.length>0} onAddMachine={()=>setAdding(true)}/>}
    {isDemo&&<DemoGuide onStepChange={showDemoStep} onReset={()=>{location.hash='overview';location.reload()}} onFinishTraining={()=>{demoRuntime!.finishTraining();void load()}}/>}
  </WorkspaceLayout>;
}

function SystemSummary({system,fresh,collectedAt}:{system?:SystemMetrics|null;fresh:boolean;collectedAt?:number|null}){
  useLocale();
  const cpu=system?.cpu_percent,memory=system?.memory;
  const percent=memory?memory.memory_used/memory.memory_total*100:null;
  return <div className={'system-summary '+(!fresh?'stale':'')} title={ui("CPU 为 250ms 采样窗口；内存已用 = MemTotal − MemAvailable。均为远端 /proc 系统视角，容器限额可能不同。")+(collectedAt?tr(" 系统采样："," System sampled: ")+new Date(collectedAt*1000).toLocaleString(dateLocale()):'')}>
    <div><Cpu size={15}/><span>CPU</span><strong>{cpu==null?ui("无法读取"):cpu.toFixed(1)+'%'}</strong><div className="system-meter"><i style={{width:(cpu??0)+'%'}}/></div><small>{system?.cpu_cores?system.cpu_cores+ui(" 逻辑核"):ui("核数未知")}</small></div>
    <div><Database size={15}/><span>{ui("内存")}</span><strong>{memory?gib(memory.memory_used)+' / '+gib(memory.memory_total)+' GiB':ui("无法读取")}</strong><div className="system-meter"><i style={{width:(percent??0)+'%'}}/></div><small>{percent==null?'—':percent.toFixed(1)+'%'}</small></div>
  </div>;
}

function ProcessDetails({process:p,onCopy}:{process:Proc;onCopy:(text:string)=>void}){
  useLocale();
  const container=p.container;
  const reason=(field:string)=>{
    if(p.detail_status==='process_changed')return ui("采集期间 PID 已被复用，请刷新");
    if(p.detail_status==='started_during_collection')return ui("进程在采集期间新启动，等待下次采集确认");
    if(p.detail_status==='not_visible_or_exited')return ui("进程已退出或当前 PID 命名空间不可见");
    if(field==='host_cwd'&&container?.host_cwd_status==='unmapped')return tr("未找到可验证的宿主目录","No verified host directory");
    if(field==='host_cwd'&&container?.host_cwd_status==='permission_denied')return ui("权限不足，无法读取");
    return p.errors?.[field]==='permission_denied'?ui("权限不足，无法读取"):p.errors?.[field]==='not_visible_or_exited'?ui("进程已退出或当前命名空间不可见"):ui("未获取");
  };
  const field=(label:string,value:string|number|null|undefined,key:string)=>
    <div><dt>{label}</dt><dd>{value!=null&&value!==''?<><span>{value}</span>{['cwd','host_cwd','executable','container_id'].includes(key)&&<button className="icon-button" aria-label={ui("复制 ")+label+' PID '+p.pid} onClick={()=>onCopy(String(value))}><Copy size={12}/></button>}</>:<span className="missing-field">{reason(key)}</span>}</dd></div>;
  const runtimeNames:Record<string,string>={docker:'Docker',containerd:'containerd','cri-o':'CRI-O',podman:'Podman'};
  const environment=[container?.orchestrator==='kubernetes'?'Kubernetes':null,container?.runtime?runtimeNames[container.runtime]:null].filter(Boolean).join(' · ');
  const cwdLabel=environment||container?.pid!=null
    ?tr("容器内目录","Container directory")
    :tr("隔离环境目录","Isolated directory");
  return <article className="process process-details"><div className="process-title"><Terminal size={16}/><strong>{p.name}</strong><Badge>PID {p.pid}</Badge></div>
    {['not_visible_or_exited','process_changed','started_during_collection'].includes(p.detail_status||'')?<p className="process-caution">{reason('identity')}</p>:null}
    <dl>
      {container&&<>
        {field(tr("宿主机目录","Host directory"),p.host_cwd,'host_cwd')}
        {field(cwdLabel,p.cwd,'cwd')}
        {field(tr("运行环境","Environment"),environment||tr("独立命名空间","Separate namespace"),'environment')}
        {container.name&&field(tr("容器名称","Container name"),container.name,'container_name')}
        {container.id&&field(tr("容器 ID","Container ID"),container.id,'container_id')}
        {container.pid!=null&&field(tr("容器内 PID","Container PID"),container.pid,'inner_pid')}
        {field(tr("登录账号","Login account"),container.audit_login_user,'audit_login_user')}
      </>}
      {field(ui("进程用户"),p.user,'user')}{field('UID',p.uid,'user')}
      {p.effective_uid!=null&&p.effective_uid!==p.uid&&field(ui("有效 UID"),p.effective_uid,'user')}
      {field(ui("父进程 PID"),p.parent_pid,'user')}{field(ui("设备显存"),gib(p.memory_used)+' GiB','memory')}
      {!container&&field(ui("工作目录"),p.cwd,'cwd')}
      {field(ui("可执行文件"),p.executable,'executable')}
    </dl>
    <div className="command-heading"><span>{ui("启动命令")}</span>{p.command&&<button className="text-button" onClick={()=>onCopy(p.command!)}><Copy size={12}/>{ui("复制")}</button>}</div>
    <pre className={!p.command?'missing-field':''}>{p.command||reason('command')}</pre>
    {p.command_truncated&&<p className="process-caution">{ui("命令过长，仅显示完整参数的前段。")}</p>}
    {container&&<p className="subtle">{tr("宿主机目录对应采样时的工作目录。系统记录的登录账号可以帮助判断谁启动了进程。","The host path maps to the working directory at sampling time. The login account recorded by the system can help identify who started the process.")}</p>}
    <small className="process-note">{p.detail_source==='sudo'?ui("已使用 sudo 补齐详情。"):ui("使用 SSH 当前账号读取。")}{ui("用户按进程 UID 解析；目录与可执行文件来自远端 /proc。常见密码、Token 参数已脱敏。")}</small>
  </article>;
}


function SudoModal({host,close,updated,notify}:{host:Host;close:()=>void;updated:()=>Promise<void>;notify:(message:string)=>void}){
  useLocale();
  const [settings,setSettings]=useState<SudoSettings|undefined>(host.sudo);
  const [password,setPassword]=useState('');
  const [pending,setPending]=useState(false),[loaded,setLoaded]=useState(false),[error,setError]=useState('');
  const account=host.ssh_logins?.accounts.find(item=>item.id===host.ssh_logins?.default_account_id);
  const user=account?.user||host.user||tr('SSH 配置中的账号','Account from SSH config');
  const path=sshAccountUrl('/hosts/'+host.id+'/sudo',host.ssh_logins?.default_account_id);
  useEffect(()=>{let active=true;api(path).then(value=>{if(active){setSettings(value);setLoaded(true)}}).catch(e=>{if(active)setError(ui(e.message))});return()=>{active=false}},[path]);
  const save=async(event:React.FormEvent)=>{
    event.preventDefault();setPending(true);setError('');
    try{
      const value=await api(path,'POST',{
        enabled:true,password:password||null,remember:settings?.can_remember!==false,
      });
      await updated();
      notify(value.password_saved?tr('sudo 已验证，密码已保存','sudo verified and password saved'):value.password_in_memory?tr('sudo 已验证，密码仅本次运行有效','sudo verified for this session'):tr('sudo 已验证','sudo verified'));
      close();
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setPassword('');setPending(false)}
  };
  const placeholder=settings?.password_saved?tr('留空使用已保存的 sudo 密码','Leave blank to use the saved sudo password'):
    settings?.ssh_password_saved?tr('留空可验证已保存的 SSH 密码','Leave blank to try the saved SSH password'):
    tr('支持免密 sudo 时可留空','Leave blank for passwordless sudo');
  const disabled=!loaded||pending;
  return <ModalDialog className="modal sudo-modal" labelledBy="sudo-title" onDismiss={()=>{if(!pending)close()}}>
    <div className="modal-header"><div><h2 id="sudo-title">{ui("sudo 进程详情")}</h2><p className="subtle">{host.alias||host.target} · {tr('默认 SSH 账号','Default SSH account')} {user}</p></div><button className="icon-button" aria-label={ui("关闭 sudo 设置")} disabled={pending} onClick={close}><X size={20}/></button></div>
    <form onSubmit={save}>
      <label className="form-label">{ui("sudo 密码")}<input type="password" autoComplete="off" maxLength={512} disabled={disabled} value={password} onChange={e=>setPassword(e.target.value)} placeholder={placeholder}/></label>
      {(error||settings?.credential_error)&&<div role="alert" className="connection-error">{error||settings?.credential_error}</div>}
      <div className="modal-footer">
        <button className="primary" disabled={disabled}>{pending&&<LoaderCircle size={16} className="spin"/>}{pending?tr('正在验证…','Verifying…'):tr('保存','Save')}</button>
      </div>
    </form>
  </ModalDialog>;
}

function AddMachine({close,connected,imported}:{close:()=>void;connected:(message:string,hostId?:string)=>void;imported:(ids:string[])=>void}){
  useLocale();
  const [bulk,setBulk]=useState(false);
  const [clusterId,setClusterId]=useState('');
  const [manual,setManual]=useState(false),[aliases,setAliases]=useState<string[]>([]),[query,setQuery]=useState(''),[target,setTarget]=useState(''),[user,setUser]=useState(''),[port,setPort]=useState(22),[password,setPassword]=useState(''),[provision,setProvision]=useState(false),[canRemember,setCanRemember]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState(''),[configPath,setConfigPath]=useState('');
  useEffect(()=>{api('/config-hosts').then(data=>{setAliases(data.aliases);setConfigPath(data.path);setCanRemember(data.can_remember_ssh_password===true)}).catch(e=>setError(e.message))},[]);
  const connect=async(e:React.FormEvent)=>{e.preventDefault();setLoading(true);setError('');try{const result=await api('/connect','POST',{target,user:user||null,port:manual?port:null,manual,password:password||null,provision,remember_password:!!password&&canRemember,auto_sudo:true,cluster_id:clusterId||null});setPassword('');connected(result.message,result.host_id)}catch(e){setPassword('');setError(e instanceof Error?e.message:String(e))}finally{setLoading(false)}};
  return <ModalDialog className={'modal '+(bulk?'import-modal':'')} labelledBy="add-title" onDismiss={()=>{if(!loading)close()}}><div className="modal-header"><div><div className="eyebrow">CONNECT / SSH</div><h2 id="add-title">{ui("添加机器")}</h2></div><button className="icon-button" disabled={loading} aria-label={ui("关闭添加机器")} onClick={close}><X size={20}/></button></div><div className="tabs"><button type="button" disabled={loading} className={!manual&&!bulk?'selected':''} onClick={()=>{setBulk(false);setManual(false);setTarget('');setError('')}}>{ui("从 SSH 配置选择")}</button><button type="button" disabled={loading} className={manual&&!bulk?'selected':''} onClick={()=>{setBulk(false);setManual(true);setTarget('');setError('')}}>{ui("手动添加")}</button><button type="button" disabled={loading} className={bulk?'selected':''} onClick={()=>{setBulk(true);setPassword('');setError('')}}>{ui("Excel 批量导入")}</button></div>{bulk?<RenderBoundary fallback={<RenderFailure title={tr("批量导入暂时无法打开","Bulk import could not open")}/>}><React.Suspense fallback={<p className="subtle">{ui("正在加载…")}</p>}><ServerImport onChanged={imported}/></React.Suspense></RenderBoundary>:<form onSubmit={connect}>
    {!manual?<><p className="config-path"><Terminal size={13}/>{configPath||ui("读取 ~/.ssh/config…")}</p><div className="search-input"><Search size={16}/><input data-dialog-focus aria-label={ui("搜索 SSH 机器")} placeholder={ui("搜索已保存的机器…")} value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="alias-list">{aliases.filter(a=>a.toLowerCase().includes(query.toLowerCase())).map(a=><button type="button" className={target===a?'selected':''} key={a} onClick={()=>setTarget(a)}><Server size={15}/><span>{a}</span>{target===a?<Check size={15}/>:<ChevronRight size={14}/>}</button>)}{aliases.length===0&&<p className="subtle">{ui("未找到机器，可切换到手动添加。")}</p>}</div></>:<><label className="form-label">{ui("主机地址")}<input required placeholder={ui("例如 192.168.1.10")} value={target} onChange={e=>setTarget(e.target.value.trim())}/></label><label className="form-label">{ui("SSH 端口")}<input required type="number" min="1" max="65535" value={port} onChange={e=>setPort(+e.target.value)}/></label></>}
    <ClusterTarget value={clusterId} onChange={setClusterId} disabled={loading}/>
    <div className="form-row"><label className="form-label">{ui("用户名 ")}{!manual&&<small>{ui("留空使用 SSH 配置")}</small>}<input required={manual} autoComplete="username" value={user} onChange={e=>setUser(e.target.value.trim())} placeholder={manual?ui("登录用户名"):ui("使用已有配置")}/></label><label className="form-label">{ui("密码 ")}<small>{ui("已有免密可留空")}</small><input type="password" autoComplete="off" value={password} onChange={e=>setPassword(e.target.value)} placeholder={canRemember?ui("连接成功后保存到系统凭据管理器"):ui("仅在本次连接时使用")}/></label></div>
    <label className="provision-option"><input type="checkbox" checked={provision} onChange={e=>setProvision(e.target.checked)}/><div><strong>{ui("登录后自动配置免密连接")}</strong><p>{ui("生成本机专用密钥，向远端追加公钥，再验证无密码登录。需要提供本次登录密码。")}</p></div><ShieldCheck size={20}/></label>{canRemember&&password&&<div className="privacy-note"><ShieldCheck size={14}/>{tr("登录后保存 SSH 密码，并尝试配置只读进程采集。","Saves the SSH password after login and tries to set up read-only process collection.")}</div>}
    {error&&<div role="alert" className="connection-error">{error}</div>}<div className="modal-footer"><span>{target?<><i className="dot"/>{target}</>:ui("选择一台机器开始")}</span><button className="primary" disabled={loading||!target||(provision&&!password)}>{loading?<LoaderCircle size={16} className="spin"/>:<ArrowUpRight size={16}/ >}{loading?ui("正在连接…"):ui("连接机器")}</button></div></form>}</ModalDialog>
}
async function boot(){
 const root=document.getElementById('root')!;root.textContent=ui("正在读取工作空间状态…");
 try{await initializeWorkspace({isolated:isDemo});initializeLocale();document.documentElement.dataset.theme=loadPreferences(workspaceStorage).theme}
 catch{root.textContent=ui("无法读取工作空间状态，请确认后台已更新并运行。");const retry=document.createElement('button');retry.textContent=ui("重试");retry.onclick=()=>{void boot()};root.append(retry);return}
 const quick=!isDemo&&new URLSearchParams(location.search).has('tool');
 createRoot(root).render(<RenderBoundary fallback={<RenderFailure title={tr("工作台界面暂时无法显示","Workbench could not display")}/>}>
   {quick?<React.Suspense fallback={<p role="status">{tr("正在加载工具窗口…","Loading tool window…")}</p>}><QuickWindow/></React.Suspense>:<App/>}
 </RenderBoundary>);
}
void boot();
