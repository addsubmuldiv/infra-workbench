/** Browser-only demo. No request is ever forwarded to the application service. */
const GiB=1024**3;
const now=()=>Date.now()/1000;
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const blocked=()=>json({detail:'演示模式不支持此操作，不会连接真实服务。 / This action is unavailable in the isolated demo.'},403);
function device(id:number,kind:string,busy:boolean){return {id:String(id),display_id:String(id),kind,name:kind==='NPU'?'Ascend 910B':'NVIDIA A100 80GB',memory_total:80*GiB,memory_used:(busy?64:2)*GiB,memory_free:(busy?16:78)*GiB,utilization:busy?94:0,temperature:busy?68:36,health:'OK',processes_known:true,processes:busy?[{pid:4200+id,name:'python3',user:'demo',memory_used:64*GiB,cwd:'/demo',command:'torchrun --nproc_per_node=4 train.py --config demo.yaml',identity_verified:true,detail_status:'complete'}]:[]}}
function initialHosts(){return [
 {id:'demo-gpu-free',target:'gpu-idle-demo',kind:'GPU',busy:false,online:true},
 {id:'demo-gpu-busy',target:'gpu-training-demo',kind:'GPU',busy:true,online:true},
 {id:'demo-npu',target:'ascend-demo',kind:'NPU',busy:true,online:true},
 {id:'demo-offline',target:'offline-demo',kind:'GPU',busy:false,online:false},
 ].map(h=>({id:h.id,target:h.target,user:'demo',port:22,manual:true,auth:'key',snapshot:{status:h.online?'online':'error',fresh:h.online,collected_at:h.online?now():null,...(!h.online?{error:'演示离线场景 / Simulated offline host'}:{}),system:h.online?{cpu_percent:h.busy?68:6,cpu_cores:64,memory:{memory_total:256*GiB,memory_used:32*GiB,memory_available:224*GiB}}:null,devices:h.online?Array.from({length:4},(_,i)=>device(i,h.kind,h.busy&&(h.kind!=='NPU'||i<2))):[]}}))}
type Reservation={id:string;host_id:string;target:string;devices:string[];labels:string[];mode:string;required_count:number;kind:string;minimum_gib:number;wait_seconds:number;status:string;idle_seconds:number;remaining_seconds:number;notified_at:number|null;email_notify:boolean;matched_devices:string[];available_count:number;url:string;desktop:{status:string}|null};
const sampleLog=Array.from({length:20},(_,i)=>`step=${i+1} loss=${(2.2/(1+i*.2)).toFixed(4)} tokens_per_second=${1200+i*12}`).join('\n')+'\n';
export function createDemoRuntime(){
 let hosts=initialHosts(),values:Record<string,string>={},revision=0,serial=0,interval=15;
 let reservations:Reservation[]=[],rules:{id:string;host_id:string;devices:string[];minimum_gib:number;port:number}[]=[],events:{id:number;created:number;host:string;message:string;notify:boolean;url:string}[]=[];
 const initialFiles:Record<string,string>={'/demo/train.log':sampleLog,'/demo/README.md':'# Demo workspace\n\nThese files exist only in browser memory.\n','/demo/demo.yaml':'model: demo-model\nbatch_size: 8\n'};
 const files={...initialFiles};
 const fileVersions=new Map(Object.keys(initialFiles).map(name=>[name,1]));
 const idleSince=new Map<string,number>();
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
 const reset=()=>{hosts=initialHosts();values={'infra-workbench:assistant-open:v1':'false'};revision=0;serial=0;events=[];rules=[];idleSince.clear();reservations=[reserve({host_id:'demo-gpu-busy',devices:['0'],wait_seconds:0})!];Object.keys(files).forEach(key=>delete files[key]);Object.assign(files,initialFiles);fileVersions.clear();Object.keys(initialFiles).forEach(name=>fileVersions.set(name,1))};reset();
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
  if(path==='/state'&&method==='GET'){update();return json({hosts,rules,reservations,events,server_time:now(),refresh_interval_seconds:interval,reservation_modes:['fixed','count']})}
  if(path==='/settings/refresh'&&method==='PUT'){interval=Number(body.interval_seconds)||15;return json({interval_seconds:interval})}
  if(path==='/settings/mail'&&method==='GET')return json({enabled:false,host:'',port:465,security:'ssl',username:'',sender:'',recipients:[],can_remember:false,has_password:false,password_saved:false,credential_error:'',last_test:null,last_delivery:null,reservation_available:false});
  if(path==='/settings/agent'&&method==='GET')return json({active_id:'demo',default_id:'demo',profiles:[{id:'demo',name:'Demo (preset)',model:'Demo'}],base_url:'',protocol:'responses',model:'Demo',timeout_seconds:45,can_remember:false,has_api_key:false,api_key_saved:false,credential_error:'',last_test:null});
  if(path==='/settings/launch'&&method==='GET')return json({mode:'browser',desktop_available:false,show_floating:false,floating_available:false});
  if(path==='/mcp-info'&&method==='GET')return json({path:'/mcp',transport:'disabled in demo',tools:[]});
  if(path==='/skills'&&method==='GET'||path==='/skills/drafts'&&method==='GET')return json({items:[]});
  if(path==='/logs/configs'&&method==='GET')return json([]);
  if(path==='/files/capabilities'&&method==='GET')return json({editing:true,search:false,upload:false,terminal_cwd:false,transfer_progress:false,folder_download:false,folder_upload:false});
  if(path==='/files/browse'&&method==='POST')return json({path:'/demo',parent:'/',entries:Object.entries(files).map(([path,content])=>({name:path.slice(path.lastIndexOf('/')+1),path,kind:'file',symlink:false,size:new TextEncoder().encode(content).length,modified:now(),accessible:true})),total:Object.keys(files).length,next_offset:null});
  if(path==='/files/operation'&&method==='POST'){
   const name=String(body.path);if(!hosts.some(h=>h.id===body.host_id)||!name.startsWith('/demo/')||name.includes('..'))return blocked();
   if(body.op==='read'&&name in files)return json({path:name,content:files[name],revision:String(fileVersions.get(name)),bytes:new TextEncoder().encode(files[name]).length,newline:'LF'});
   if(body.op==='save'&&name in files){if(body.revision!==String(fileVersions.get(name)))return json({detail:'Demo file changed; reload it.'},409);files[name]=String(body.content??'');fileVersions.set(name,fileVersions.get(name)!+1);return json({path:name,revision:String(fileVersions.get(name)),bytes:new TextEncoder().encode(files[name]).length,newline:'LF',content:files[name]})}return blocked();
  }
  if(path==='/preflight'&&method==='POST')return json({status:'PASS',reasons:['[DEMO] 模拟检查通过；未执行 SSH。 / Simulated check; no SSH was executed.']});
  if(path==='/reservations'&&method==='POST'){const item=reserve(body);if(!item)return blocked();reservations.push(item);update();return json(item)}
  if(path.startsWith('/reservations/')){const id=decodeURIComponent(path.split('/')[2]);const index=reservations.findIndex(r=>r.id===id);if(index<0)return json({detail:'Demo reservation not found'},404);
   if(method==='DELETE'){reservations.splice(index,1);idleSince.delete(id);return json({ok:true})}
   if(method==='PATCH'){const item=reserve({...reservations[index],...body},id);if(!item)return blocked();idleSince.delete(id);reservations[index]=item;update();return json(item)}
  }
  if(path==='/rules'&&method==='POST'){if(!hosts.some(h=>h.id===body.host_id))return blocked();const rule={id:'demo-rule-'+(++serial),host_id:String(body.host_id),devices:Array.isArray(body.devices)?body.devices.map(String):[],minimum_gib:Number(body.minimum_gib??1),port:Number(body.port??29500)};rules.push(rule);return json(rule)}
  if(path.startsWith('/rules/')&&method==='DELETE'){rules=rules.filter(r=>r.id!==path.split('/')[2]);return json({ok:true})}
  if(path.startsWith('/hosts/')&&method==='DELETE'){const id=decodeURIComponent(path.split('/')[2]);if(!hosts.some(h=>h.id===id))return blocked();hosts=hosts.filter(h=>h.id!==id);reservations=reservations.filter(r=>r.host_id!==id);rules=rules.filter(r=>r.host_id!==id);return json({ok:true})}
  if(/^\/hosts\/[^/]+\/refresh$/.test(path)&&method==='POST'){const host=hosts.find(h=>h.id===decodeURIComponent(path.split('/')[2]));if(!host)return blocked();update();return json(host.snapshot)}
  if(path==='/refresh'&&method==='POST')return json({ok:true});
  return blocked();
 };
 return {fetch:fetchDemo,reset,finishTraining(){const host=hosts.find(h=>h.id==='demo-gpu-busy');if(host)host.snapshot.devices=host.snapshot.devices.map((_,i)=>device(i,'GPU',false));update()},getHosts:()=>JSON.parse(JSON.stringify(hosts)) as typeof hosts};
}
/** Replace all application request transports. Never retain a backend fallback. */
export function installDemoNetwork(surface:object,runtime:ReturnType<typeof createDemoRuntime>){
 const target=surface as Record<string,unknown>;
 target.fetch=runtime.fetch;
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
