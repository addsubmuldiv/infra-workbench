import {MONITORING_REFRESH_INTERVAL_SECONDS} from '../../internalDefaults.ts';
import type {Cluster} from '../hosts/clusterApi.ts';
import {createDemoGroups} from './demoGroups.ts';
import {demoHistory} from './demoHistory.ts';
import {createDemoPorts} from './demoPorts.ts';
import {compareDemoLogs,demoLogAt,demoLogRecord,demoPrecisionFiles,demoPrecisionSamples} from './demoPrecision.ts';
/** Browser-only demo. No request is ever forwarded to the application service. */
const GiB=1024**3;
const now=()=>Date.now()/1000;
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const blocked=()=>json({detail:'演示模式不支持此操作，不会连接真实服务。 / This action is unavailable in the isolated demo.'},403);
function device(id:number,kind:string,busy:boolean,model=kind==='NPU'?'Ascend 910B':'NVIDIA A100 80GB',memory=80){
 const inContainer=kind==='GPU'&&id<2;
 const used=busy?Math.floor(memory*.8):2;
 const process={pid:4200+id,name:'python3',user:inContainer?'root':'demo',memory_used:used*GiB,
  cwd:inContainer?(id===0?'/workspace/train':'/app'):'/demo',
  command:'torchrun --nproc_per_node=4 train.py --config demo.yaml',identity_verified:true,detail_status:'complete',
  ...(inContainer?{host_cwd:id===0?'/home/demo/projects/train':null,
   container:{runtime:'docker',id:(id===0?'d3e01234':'d3e05678').repeat(8),name:id===0?'demo-training':'demo-image-job',pid:12+id,
    audit_login_user:id===0?'demo':null,host_cwd_status:id===0?'mapped':'unmapped'}}:{})};
 return {id:String(id),display_id:String(id),kind,name:model,
  memory_total:memory*GiB,memory_used:used*GiB,memory_free:(memory-used)*GiB,utilization:busy?94:0,
  temperature:busy?68:36,health:'OK',processes_known:true,processes:busy?[process]:[]};
}
function initialHosts(){return [
 {id:'demo-gpu-free',target:'gpu-idle-demo',alias:'GPU Lab 01',kind:'GPU',count:4,busy:0},
 {id:'demo-gpu-busy',target:'gpu-training-demo',alias:'GPU Training 02',kind:'GPU',count:4,busy:4},
 {id:'demo-npu',target:'ascend-demo',alias:'Ascend Training 01',kind:'NPU',count:8,busy:4,model:'Ascend 910B',memory:64},
 {id:'demo-offline',target:'offline-demo',alias:'Offline Worker',kind:'GPU',count:0,busy:0,offline:true},
 {id:'demo-gpu-h100',target:'gpu-h100-demo',alias:'GPU Inference 03',kind:'GPU',count:8,busy:2,model:'NVIDIA H100 80GB'},
 {id:'demo-npu-free',target:'ascend-idle-demo',alias:'Ascend Lab 02',kind:'NPU',count:8,busy:0,model:'Ascend 910B',memory:64},
 {id:'demo-gpu-stale',target:'gpu-stale-demo',alias:'Stale GPU Worker',kind:'GPU',count:4,busy:0,stale:true},
 {id:'demo-gpu-edge',target:'gpu-edge-demo',alias:'GPU Edge 01',kind:'GPU',count:2,busy:1,model:'NVIDIA L40S',memory:48},
 ].map(h=>{
  const fresh=!h.offline&&!h.stale;
  return {id:h.id,target:h.target,alias:h.alias,user:'demo',port:22,manual:true,auth:'key',
   snapshot:{status:h.offline?'error':h.stale?'stale':'online',fresh,collected_at:h.offline?null:now()-(h.stale?900:0),
    ...(h.offline?{error:'演示离线场景 / Simulated offline host'}:{}),
    system:h.offline?null:{cpu_percent:h.busy?68:6,cpu_cores:64,memory:{memory_total:256*GiB,memory_used:32*GiB,memory_available:224*GiB}},
    devices:Array.from({length:h.count},(_,i)=>device(i,h.kind,i<h.busy,h.model,h.memory))}};
 })}
const initialClusters=():Cluster[]=>[
 {id:'demo-gpu',name:'GPU Training',revision:1,host_ids:['demo-gpu-free','demo-gpu-busy','demo-gpu-stale']},
 {id:'demo-ascend',name:'Ascend Lab',revision:1,host_ids:['demo-npu','demo-npu-free']},
 {id:'demo-inference',name:'Inference',revision:1,host_ids:['demo-gpu-h100','demo-gpu-edge']},
];
type Reservation={id:string;host_id:string;target:string;devices:string[];labels:string[];mode:string;required_count:number;kind:string;minimum_gib:number;wait_seconds:number;status:string;idle_seconds:number;remaining_seconds:number;notified_at:number|null;email_notify:boolean;matched_devices:string[];available_count:number;url:string;desktop:{status:string}|null};
const sampleLog=Array.from({length:20},(_,i)=>`step=${i+1} loss=${(2.2/(1+i*.2)).toFixed(4)} tokens_per_second=${1200+i*12}`).join('\n')+'\n';
export function createDemoRuntime(){
 let hosts=initialHosts(),clusters=initialClusters(),values:Record<string,string>={},revision=0,serial=0,interval=MONITORING_REFRESH_INTERVAL_SECONDS;
 let reservations:Reservation[]=[],rules:{id:string;host_id:string;devices:string[];minimum_gib:number;port:number}[]=[],events:{id:number;created:number;host:string;message:string;notify:boolean;url:string}[]=[];
 const initialFiles:Record<string,string>={'/demo/train.log':sampleLog,'/demo/README.md':'# Demo workspace\n\nThese files exist only in browser memory.\n','/demo/demo.yaml':'model: demo-model\nbatch_size: 8\n',...demoPrecisionFiles};
 const files={...initialFiles};
 const fileVersions=new Map(Object.keys(initialFiles).map(name=>[name,1]));
 const idleSince=new Map<string,number>();
 const ports=createDemoPorts();
 const groups=createDemoGroups(()=>hosts,()=>clusters,(host,id)=>events.unshift({id:++serial,created:now(),host,
  message:'[DEMO] 集群预约条件已满足 / Cluster alert matched',notify:false,url:'#reservations?group='+id}));
 const logConfigs=new Map<string,Record<string,unknown>>();
 const update=()=>{for(const item of reservations){if(item.status==='ready')continue;const host=hosts.find(h=>h.id===item.host_id);if(!host?.snapshot.fresh){item.status='unknown';continue}
  const free=host.snapshot.devices.filter(d=>!d.processes.length&&d.memory_free>=item.minimum_gib*GiB);
  const chosen=item.mode==='count'?free.filter(d=>d.kind===item.kind).slice(0,item.required_count):free.filter(d=>item.devices.includes(d.id));
  item.available_count=free.length;item.matched_devices=chosen.map(d=>d.id);
  const ready=item.mode==='count'?chosen.length>=item.required_count:chosen.length===item.devices.length&&chosen.length>0;
  if(!ready){idleSince.delete(item.id);item.status='waiting';item.idle_seconds=0;item.remaining_seconds=item.wait_seconds;continue}
  if(!idleSince.has(item.id))idleSince.set(item.id,now());item.idle_seconds=Math.floor(now()-idleSince.get(item.id)!);item.remaining_seconds=Math.max(0,item.wait_seconds-item.idle_seconds);item.status=item.remaining_seconds?'settling':'ready';
  if(item.status==='ready'){if(item.mode==='count')item.labels=chosen.map(d=>d.display_id);item.desktop={status:'skipped'};item.notified_at=now();events.unshift({id:++serial,created:now(),host:host.target,message:'[DEMO] '+host.target+'：预约设备已空闲 / Reserved devices are idle',notify:false,url:item.url})}
 }};
 const reserve=(body:Record<string,unknown>,id='demo-reservation-'+(++serial))=>{const host=hosts.find(h=>h.id===body.host_id);if(!host)return null;const devices=Array.isArray(body.devices)?body.devices.map(String):[];
  if(devices.some(id=>!host.snapshot.devices.some(d=>d.id===id)))return null;
  return {id,host_id:host.id,target:host.target,devices,labels:devices,mode:String(body.mode??'fixed'),required_count:Number(body.required_count??1),kind:String(body.kind??'GPU'),minimum_gib:Number(body.minimum_gib??1),wait_seconds:Number(body.wait_seconds??0),status:'waiting',idle_seconds:0,remaining_seconds:Number(body.wait_seconds??0),notified_at:null,email_notify:false,matched_devices:[],available_count:0,url:'#overview?host='+host.id,desktop:null} satisfies Reservation;
 };
 const reset=()=>{hosts=initialHosts();clusters=initialClusters();values={'infra-workbench:assistant-open:v1':'false'};revision=0;serial=0;events=[];rules=[];idleSince.clear();reservations=[reserve({host_id:'demo-gpu-busy',devices:['0'],wait_seconds:0})!];Object.keys(files).forEach(key=>delete files[key]);Object.assign(files,initialFiles);fileVersions.clear();Object.keys(initialFiles).forEach(name=>fileVersions.set(name,1));groups.reset();ports.reset();logConfigs.clear();interval=MONITORING_REFRESH_INTERVAL_SECONDS};reset();
 const fetchDemo:typeof fetch=async(input,init)=>{
  const request=input instanceof Request?input:null;const url=new URL(request?.url??String(input),'https://demo.invalid');
  // Relative paths only. Absolute URLs, including the real origin, fail closed.
  if((request||/^[a-z][a-z\d+.-]*:|^\/\//i.test(String(input)))||!url.pathname.startsWith('/api/'))return blocked();
  if(init?.signal?.aborted)throw new DOMException('Aborted','AbortError');
  const method=(init?.method??'GET').toUpperCase();const path=url.pathname.slice(4);
  let body:Record<string,unknown>={};try{const raw=init?.body;if(raw)body=JSON.parse(String(raw))}catch{return json({detail:'Invalid demo request'},400)}
  if(path==='/workspace-state'){
   if(method==='PUT'){for(const [key,value] of Object.entries(body.values??{})){if(body.only_missing&&key in values)continue;if(value===null)delete values[key];else if(typeof value==='string')values[key]=value}revision++}
   else if(method!=='GET')return blocked();return json({revision,values});
  }
   if(path==='/state'&&method==='GET'){update();return json({hosts:hosts.map(h=>({...h,ssh_tunnels:ports.request(h.id,'tunnels',undefined,undefined,'GET',{})})),rules,reservations,group_reservations:groups.list(),events,server_time:now(),refresh_interval_seconds:interval,reservation_modes:['fixed','count']})}
   const [,namespace,id,feature,item,action]=path.split('/');
   if(namespace==='group-reservations'){const result=groups.request(method,id,feature,body);return result?json(result):blocked()}
   if(namespace==='hosts'&&['tunnels','services'].includes(feature)&&hosts.some(h=>h.id===id)){
    const result=ports.request(id,feature,item,action,method,body);return result?json(result):blocked();
   }
   if(namespace==='clusters'){
    if(!id&&method==='GET')return json({items:clusters});
    const name=typeof body.name==='string'?body.name.trim():'';
    if(!id&&method==='POST'&&name){const cluster={id:'demo-cluster-'+ ++serial,name,revision:1,host_ids:[]};clusters.push(cluster);return json(cluster)}
    const cluster=clusters.find(c=>c.id===id);
    if(!cluster)return blocked();
    if(!feature&&method==='PATCH'&&name){cluster.name=name;cluster.revision++;return json(cluster)}
    if(!feature&&method==='DELETE'){clusters=clusters.filter(c=>c.id!==id);return json({ok:true})}
    if(feature==='members'&&method==='PUT'&&Array.isArray(body.host_ids)){
     const ids=[...new Set(body.host_ids.map(String))];
     if(ids.some(hostId=>!hosts.some(h=>h.id===hostId)))return blocked();
     for(const peer of clusters){
      if(peer===cluster)continue;
      const remaining=peer.host_ids.filter(hostId=>!ids.includes(hostId));
      if(remaining.length!==peer.host_ids.length){peer.host_ids=remaining;peer.revision++}
     }
     cluster.host_ids=ids;cluster.revision++;return json(cluster);
    }
    return blocked();
   }
   if(path==='/resource-history'&&method==='GET'){const result=demoHistory(hosts,url.searchParams,now());return result?json(result):blocked()}
  if(path==='/settings/refresh'&&method==='PUT'){interval=Number(body.interval_seconds)||MONITORING_REFRESH_INTERVAL_SECONDS;return json({interval_seconds:interval})}
  if(path==='/settings/mail'&&method==='GET')return json({enabled:false,host:'',port:465,security:'ssl',username:'',sender:'',recipients:[],can_remember:false,has_password:false,password_saved:false,credential_error:'',last_test:null,last_delivery:null,reservation_available:false});
  if(path==='/settings/agent'&&method==='GET')return json({active_id:'demo',default_id:'demo',profiles:[{id:'demo',name:'Demo (preset)',model:'Demo'}],base_url:'',protocol:'responses',model:'Demo',timeout_seconds:45,can_remember:false,has_api_key:false,api_key_saved:false,credential_error:'',last_test:null});
  if(path==='/settings/launch'&&method==='GET')return json({mode:'browser',desktop_available:false,show_floating:false,floating_available:false});
  if(path==='/mcp-info'&&method==='GET')return json({path:'/mcp',transport:'disabled in demo',tools:[]});
  if(path==='/skills'&&method==='GET'||path==='/skills/drafts'&&method==='GET')return json({items:[]});
   if(path==='/logs/configs'&&method==='GET')return json([...logConfigs.values()]);
   if(path==='/logs/configs'&&method==='POST'){
    const config={...body,id:typeof body.id==='string'&&logConfigs.has(body.id)?body.id:'demo-log-'+ ++serial};
    logConfigs.set(config.id,config);return json(config);
   }
   if(namespace==='logs'&&id==='configs'&&feature&&method==='DELETE'){logConfigs.delete(feature);return json({ok:true})}
   if(path==='/logs/demo'&&method==='POST')return json(demoPrecisionSamples);
   if(path==='/logs/compare'&&method==='POST'){const result=compareDemoLogs(body);return result?json(result):blocked()}
   if(namespace==='logs'&&feature==='record'&&method==='GET'&&url.searchParams.get('group')==='rank0'){
    const record=demoLogRecord(id,Number(url.searchParams.get('line')));return record?json(record):blocked();
   }
   if(namespace==='logs'&&['read','browse'].includes(id)&&method==='POST'&&hosts.some(h=>h.id===body.host_id)){
    if(id==='browse')return json({path:'/demo',parent:'/demo',truncated:false,entries:Object.entries(demoPrecisionFiles).map(([path,content])=>({name:path.split('/').pop(),path,directory:false,size:new TextEncoder().encode(content).length}))});
    const log=demoLogAt(body.path);return log?json(log):blocked();
   }
  if(path==='/files/capabilities'&&method==='GET')return json({editing:true,search:false,upload:false,terminal_cwd:false,transfer_progress:false,folder_download:false,folder_upload:false});
  if(path==='/files/browse'&&method==='POST')return json({path:'/demo',parent:'/',entries:Object.entries(files).map(([path,content])=>({name:path.slice(path.lastIndexOf('/')+1),path,kind:'file',symlink:false,size:new TextEncoder().encode(content).length,modified:now(),accessible:true})),total:Object.keys(files).length,next_offset:null});
  if(path==='/files/operation'&&method==='POST'){
   const name=String(body.path);if(!hosts.some(h=>h.id===body.host_id)||!name.startsWith('/demo/')||name.includes('..'))return blocked();
   if(body.op==='read'&&name in files)return json({path:name,content:files[name],revision:String(fileVersions.get(name)),bytes:new TextEncoder().encode(files[name]).length,newline:'LF'});
   if(body.op==='save'&&name in files){if(body.revision!==String(fileVersions.get(name)))return json({detail:'Demo file changed; reload it.'},409);files[name]=String(body.content??'');fileVersions.set(name,fileVersions.get(name)!+1);return json({path:name,revision:String(fileVersions.get(name)),bytes:new TextEncoder().encode(files[name]).length,newline:'LF',content:files[name]})}return blocked();
  }
   if((path==='/files/download'||path==='/logs/download')&&method==='POST'&&hosts.some(h=>h.id===body.host_id)){
    const name=String(body.path);
    if(!Object.prototype.hasOwnProperty.call(files,name))return blocked();
    const content=files[name];
    return new Response(content,{headers:{'Content-Type':'text/plain; charset=utf-8',
     'Content-Disposition':`attachment; filename="${name.split('/').pop()}"`,'Content-Length':String(new TextEncoder().encode(content).length)}});
   }
   if(path==='/preflight'&&method==='POST'){
    const host=hosts.find(h=>h.id===body.host_id);
    const requested=Array.isArray(body.devices)?body.devices.map(String):[];
    const devices=host?.snapshot.devices.filter(d=>requested.includes(d.id))??[];
    const passed=host?.snapshot.fresh&&devices.length>0&&devices.length===requested.length&&
     devices.every(d=>!d.processes.length&&d.utilization===0&&d.memory_free>=Number(body.minimum_gib??0)*GiB);
    return json(passed?{status:'PASS',reasons:['[DEMO] 所选设备空闲，模拟端口可用。 / Selected devices are idle and the simulated port is free.']}:
     {status:'FAIL',reasons:['[DEMO] 所选设备有占用、显存不足或缺少有效采集。 / Selected devices are in use, low on memory, or lack a valid sample.']});
   }
  if(path==='/reservations'&&method==='POST'){const item=reserve(body);if(!item)return blocked();reservations.push(item);update();return json(item)}
  if(path.startsWith('/reservations/')){const id=decodeURIComponent(path.split('/')[2]);const index=reservations.findIndex(r=>r.id===id);if(index<0)return json({detail:'Demo reservation not found'},404);
   if(method==='DELETE'){reservations.splice(index,1);idleSince.delete(id);return json({ok:true})}
   if(method==='PATCH'){const item=reserve({...reservations[index],...body},id);if(!item)return blocked();idleSince.delete(id);reservations[index]=item;update();return json(item)}
  }
  if(path==='/rules'&&method==='POST'){if(!hosts.some(h=>h.id===body.host_id))return blocked();const rule={id:'demo-rule-'+(++serial),status:'active',host_id:String(body.host_id),devices:Array.isArray(body.devices)?body.devices.map(String):[],minimum_gib:Number(body.minimum_gib??1),port:Number(body.port??29500)};rules.push(rule);return json(rule)}
  if(path.startsWith('/rules/')&&method==='DELETE'){rules=rules.filter(r=>r.id!==path.split('/')[2]);return json({ok:true})}
   if(namespace==='hosts'&&id&&!feature&&method==='DELETE'){if(!hosts.some(h=>h.id===id))return blocked();hosts=hosts.filter(h=>h.id!==id);reservations=reservations.filter(r=>r.host_id!==id);rules=rules.filter(r=>r.host_id!==id);for(const cluster of clusters)if(cluster.host_ids.includes(id)){cluster.host_ids=cluster.host_ids.filter(h=>h!==id);cluster.revision++}return json({ok:true})}
  if(/^\/hosts\/[^/]+\/refresh$/.test(path)&&method==='POST'){const host=hosts.find(h=>h.id===decodeURIComponent(path.split('/')[2]));if(!host)return blocked();update();return json(host.snapshot)}
  if(path==='/refresh'&&method==='POST')return json({ok:true});
  return blocked();
 };
 return {fetch:fetchDemo,reset,finishTraining(){const host=hosts.find(h=>h.id==='demo-gpu-busy');if(host)host.snapshot.devices=host.snapshot.devices.map((_,i)=>device(i,'GPU',false));update()},getHosts:()=>JSON.parse(JSON.stringify(hosts)) as typeof hosts};
}
/** Replace application request transports. Never fall back to the workbench backend. */
export function installDemoNetwork(surface:object,runtime:ReturnType<typeof createDemoRuntime>){
 const target=surface as Record<string,unknown>;
 const bridge=target.__TAURI_INTERNALS__ as {convertFileSrc?:(command:string,protocol:string)=>string}|undefined;
 const nativeFetch=(target.fetch as typeof fetch|undefined)?.bind(surface);
 // Tauri uses fetch even for native window messages. Keep the ready handshake
 // and title bar working without forwarding application or other IPC requests.
 const windowCommands=bridge?.convertFileSrc
  ? ['desktop_ready','main_window_action'].map(command=>bridge.convertFileSrc!(command,'ipc'))
     .filter(url=>/^(?:https?:\/\/ipc\.localhost|ipc:\/\/localhost)\//.test(url)) : [];
 const demoFetch:typeof fetch=(input,init)=>{
  if(nativeFetch&&typeof input==='string'&&windowCommands.includes(input)&&init?.method==='POST'){
   const headers=new Headers(init.headers);
   if(headers.has('Tauri-Invoke-Key')&&headers.has('Tauri-Callback')&&headers.has('Tauri-Error'))return nativeFetch(input,init);
  }
  return runtime.fetch(input,init);
 };
 target.fetch=demoFetch;
 class BlockedTransport{constructor(){throw new Error('Demo mode blocks real network transports')}}
 for(const name of ['WebSocket','EventSource','XMLHttpRequest','WebTransport','RTCPeerConnection'])if(name in target)target[name]=BlockedTransport;
 const navigator=target.navigator as {sendBeacon?:(...args:unknown[])=>boolean}|undefined;
 if(navigator)Object.defineProperty(navigator,'sendBeacon',{configurable:true,value:()=>false});
 const document=target.document as Document|undefined;
 document?.addEventListener('click',event=>{
  const link=event.target instanceof Element?event.target.closest('a[href]'):null;
  if(link){const url=new URL(link.getAttribute('href')!,document.baseURI);if(/^\/(api(?:\/|$)|mcp(?:\/|$))/.test(url.pathname)){event.preventDefault();event.stopImmediatePropagation();document.dispatchEvent(new CustomEvent('demo-operation-blocked'))}}
 },true);
}
