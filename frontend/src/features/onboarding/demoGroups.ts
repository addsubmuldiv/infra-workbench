import type {Cluster} from '../hosts/clusterApi.ts';

type Host={id:string;target:string;snapshot:{fresh:boolean;devices:{id:string;kind:string;memory_free:number;processes:unknown[]}[]}};
type Rule={id:string;mode:string;cluster_id?:string;cluster_name_snapshot?:string;candidate_host_ids:string[];kind:string;
 required_devices:number;required_hosts:number;minimum_gib:number;wait_seconds:number;status:string;version:number;revision:number;
 email_notify:false;readySince?:number;notified_at?:number;request_id?:unknown};

export function createDemoGroups(hosts:()=>Host[],clusters:()=>Cluster[],notify:(name:string,id:string)=>void){
 const rules=new Map<string,Rule>();
 let serial=0;
 const update=(rule:Rule)=>{
  const current=hosts();
  const matched:{host_id:string;target:string;devices:string[]}[]=[];
  const host_states=rule.candidate_host_ids.map(host_id=>{
   const host=current.find(h=>h.id===host_id);
   const free=host?.snapshot.fresh?host.snapshot.devices.filter(d=>d.kind===rule.kind&&!d.processes.length&&d.memory_free>=rule.minimum_gib*1024**3):null;
   const status=free===null?'unknown':free.length>=rule.required_devices?'ready':'not_ready';
   if(status==='ready'&&host&&free)matched.push({host_id,target:host.target,devices:free.slice(0,rule.required_devices).map(d=>d.id)});
   return {host_id,target:host?.target,status,available_count:free?.length??null};
  });
  const counts={ready:matched.length,not_ready:host_states.filter(h=>h.status==='not_ready').length,unknown:host_states.filter(h=>h.status==='unknown').length};
  const now=Date.now()/1000;
  if(!['ready','cancelled'].includes(rule.status)){
   if(matched.length>=rule.required_hosts){
    rule.readySince??=now;
    rule.status=now-rule.readySince>=rule.wait_seconds?'ready':'settling';
    if(rule.status==='ready'){rule.notified_at=now;notify(rule.cluster_name_snapshot??'Demo group',rule.id)}
   }else{
    rule.readySince=undefined;
    rule.status=matched.length+counts.unknown>=rule.required_hosts?'unknown':'waiting';
   }
  }
  const confirmed_seconds=Math.floor((rule.notified_at??now)-(rule.readySince??now));
  const cluster=clusters().find(c=>c.id===rule.cluster_id);
  return {...rule,host_states,counts,confirmed_seconds,remaining_seconds:Math.max(0,rule.wait_seconds-confirmed_seconds),
   revision_changed:!!cluster&&cluster.revision!==rule.revision,cluster_deleted:!!rule.cluster_id&&!cluster,
   matched_hosts:rule.status==='ready'?matched:[],desktop:{status:'skipped'}};
 };
 const save=(body:Record<string,unknown>,previous?:Rule)=>{
  const mode=body.mode,ids=Array.isArray(body.candidate_host_ids)?[...new Set(body.candidate_host_ids.map(String))]:[];
  const cluster=clusters().find(c=>c.id===body.cluster_id);
  const required_hosts=mode==='specified'?ids.length:Number(body.required_hosts),required_devices=Number(body.required_devices);
  const minimum_gib=Number(body.minimum_gib),wait_seconds=Number(body.wait_seconds);
  if(!['specified','cluster_any'].includes(String(mode))||!ids.length||!ids.every(id=>hosts().some(h=>h.id===id))||
   (mode==='specified'&&ids.length<2)||(mode==='cluster_any'&&(!cluster||!ids.every(id=>cluster.host_ids.includes(id))))||
   !Number.isInteger(required_hosts)||required_hosts<1||required_hosts>ids.length||
   !Number.isInteger(required_devices)||required_devices<1||!['GPU','NPU'].includes(String(body.kind))||
   !Number.isFinite(minimum_gib)||minimum_gib<0||!Number.isFinite(wait_seconds)||wait_seconds<0)return null;
  const duplicate=!previous&&body.request_id?[...rules.values()].find(r=>r.request_id===body.request_id):null;
  if(duplicate)return update(duplicate);
  const rule:Rule={id:previous?.id??'demo-group-'+ ++serial,mode:String(mode),cluster_id:mode==='cluster_any'?cluster?.id:undefined,
   cluster_name_snapshot:cluster?.name,candidate_host_ids:ids,kind:String(body.kind),required_hosts,required_devices,minimum_gib,wait_seconds,
   revision:cluster?.revision??1,version:(previous?.version??0)+1,email_notify:false,status:'waiting',request_id:body.request_id};
  rules.set(rule.id,rule);
  return update(rule);
 };
 const list=()=>[...rules.values()].map(update);
 return {list,reset(){
  rules.clear();serial=0;
  save({mode:'cluster_any',cluster_id:'demo-gpu',candidate_host_ids:['demo-gpu-busy','demo-gpu-free'],kind:'GPU',
   required_devices:2,required_hosts:2,minimum_gib:24,wait_seconds:0});
 },request(method:string,id:string|undefined,action:string|undefined,body:Record<string,unknown>){
  if(!id&&method==='GET')return {items:list()};
  if(!id&&method==='POST')return save(body);
  const rule=id?rules.get(id):undefined;
  if(!rule)return null;
  if(action==='cancel'&&method==='POST'){rule.status='cancelled';return update(rule)}
  if(!action&&method==='PATCH'&&body.version===rule.version)return save(body,rule);
  if(!action&&method==='DELETE'){rules.delete(rule.id);return {ok:true}}
  return null;
 }};
}
