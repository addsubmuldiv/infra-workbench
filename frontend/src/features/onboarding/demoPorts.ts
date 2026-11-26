import type {TunnelRule} from '../hosts/SSHTunnelPanel.tsx';

type Service={id:string;name:string;local_port:number;remote_port:number;bound_port:number|null;status:string;url:null;error:string};

export function createDemoPorts(){
 const tunnels=new Map<string,TunnelRule[]>(),services=new Map<string,Service[]>();
 let serial=0;
 const now=()=>Date.now()/1000;
 function tunnel(id:string,body:Record<string,unknown>):TunnelRule{
  return {id,name:String(body.name??'SSH tunnel'),direction:body.direction==='remote'?'remote':'local',local_port:Number(body.local_port),
   remote_port:Number(body.remote_port),auto_reconnect:!!body.auto_reconnect,auto_start:!!body.auto_start,before_vscode:!!body.before_vscode,
   status:'stopped',connected_at:null,next_retry_at:null,error:'',error_code:null,has_connected:false};
 }
 function service(id:string,body:Record<string,unknown>):Service{
  return {id,name:String(body.name??'HTTP'),local_port:Number(body.local_port),remote_port:Number(body.remote_port),
   bound_port:null,status:'stopped',url:null,error:''};
 }
 return {reset(){
  tunnels.clear();services.clear();serial=0;
  const notebook=tunnel('demo-notebook',{name:'JupyterLab',local_port:18888,remote_port:8888,auto_reconnect:true});
  tunnels.set('demo-gpu-busy',[{...notebook,status:'connected',connected_at:now()-720,has_connected:true},
   tunnel('demo-editor',{name:'Remote editor',direction:'remote',local_port:7890,remote_port:18899,before_vscode:true})]);
  services.set('demo-gpu-busy',[service('demo-tensorboard',{name:'TensorBoard',local_port:0,remote_port:6006})]);
 },request(host:string,feature:string,id:string|undefined,action:string|undefined,method:string,body:Record<string,unknown>){
  const port=(value:unknown,minimum:number)=>Number.isInteger(value)&&Number(value)>=minimum&&Number(value)<=65535;
  const valid=(minimum:number)=>typeof body.name==='string'&&!!body.name.trim()&&port(body.local_port,minimum)&&port(body.remote_port,1);
  if(feature==='tunnels'){
   const rules=tunnels.get(host)??[];
   if(!id&&method==='GET')return rules;
   if(!id&&method==='POST'&&valid(1)){
    const item=tunnel('demo-tunnel-'+ ++serial,body);tunnels.set(host,[...rules,item]);return item;
   }
   const item=rules.find(r=>r.id===id);
   if(!item)return null;
   if(!action&&method==='PUT'&&valid(1)&&item.status!=='connected'){Object.assign(item,tunnel(item.id,body),{has_connected:item.has_connected});return item}
   if(!action&&method==='DELETE'&&item.status!=='connected'){tunnels.set(host,rules.filter(r=>r!==item));return {ok:true}}
   if(action==='start'&&method==='POST'){Object.assign(item,{status:'connected',connected_at:now(),has_connected:true});return item}
   if(action==='stop'&&method==='POST'){Object.assign(item,{status:'stopped',connected_at:null});return item}
   if(action==='probe'&&method==='POST'&&item.status==='connected')return {reachable:true,message:'模拟端口可达 / Simulated target is reachable'};
   return null;
  }
  const rules=services.get(host)??[];
  if(!id&&method==='GET')return rules;
  if(!id&&method==='POST'&&valid(0)){
   const item=service('demo-service-'+ ++serial,body);services.set(host,[...rules,item]);return item;
  }
  const item=rules.find(r=>r.id===id);
  if(!item)return null;
  if(!action&&method==='DELETE'){services.set(host,rules.filter(r=>r!==item));return {ok:true}}
  if(action==='start'&&method==='POST'){Object.assign(item,{status:'active',bound_port:item.local_port||16006});return item}
  if(action==='stop'&&method==='POST'){Object.assign(item,{status:'stopped',bound_port:null});return item}
  return null;
 }};
}
