import type {FleetSegment,HistoryResponse,HistorySegment,HistorySummary} from '../monitoring/resourceHistoryModel.ts';

type Host={id:string;target:string;alias?:string;snapshot:{fresh:boolean;devices:{id:string;kind:string}[]}};
const duration=(range:{start:number;end:number})=>range.end-range.start;

export function demoHistory(hosts:Host[],params:URLSearchParams,now:number):HistoryResponse|null{
 const timezone=params.get('timezone')||'UTC';
 const date=params.get('date');
 const kind=params.get('kind')||'GPU';
 if(!date||!/^\d{4}-\d{2}-\d{2}$/.test(date))return null;
 const ids=new Set((params.get('host_ids')??'').split(',').filter(Boolean));
 const selected=hosts.filter(h=>ids.has(h.id));
 if(!ids.size||selected.length!==ids.size)return null;

 // Convert the simulated date and time using the same zone the chart displays.
 let clock:Intl.DateTimeFormat;
 try{clock=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})}
 catch{return null}
 const zoned=(day:string,time:string)=>{
  const utc=Date.parse(day+'T'+time+'Z')/1000;
  if(!Number.isFinite(utc))return NaN;
  const offsetAt=(timestamp:number)=>{
   const parts=Object.fromEntries(clock.formatToParts(timestamp*1000).map(({type,value})=>[type,value]));
   return Date.parse(`${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}Z`)/1000-timestamp;
  };
  return utc-offsetAt(utc-offsetAt(utc));
 };
 const tomorrow=new Date((Date.parse(date)+86400000));
 if(!Number.isFinite(tomorrow.valueOf()))return null;
 let start=zoned(date,'00:00'),end=zoned(tomorrow.toISOString().slice(0,10),'00:00');
 const hours=Number(params.get('window_hours')??0);
 if([1,3,6,12].includes(hours)){
  if(now>start)end=Math.min(now,end);
  start=Math.max(start,end-hours*3600);
 }
 if(params.has('start_time'))start=zoned(date,params.get('start_time')!);
 if(params.has('end_time')&&params.get('end_time')!=='24:00')end=zoned(date,params.get('end_time')!);
 if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return null;
 const elapsed_end=Math.max(start,Math.min(now,end));
 const boundaries=[...new Set([start,Math.round(start+(elapsed_end-start)*.25),Math.round(start+(elapsed_end-start)*.5),
  Math.round(start+(elapsed_end-start)*.7),Math.round(start+(elapsed_end-start)*.82),elapsed_end,end])]
  .filter(point=>point>=start&&point<=end).sort((a,b)=>a-b);
 const ranges=boundaries.slice(1).map((to,i)=>({start:boundaries[i],end:to}));
 const summarize=(periods:{start:number;end:number;complete:boolean;idle:number;whole:boolean}[]):HistorySummary=>{
  const complete=periods.filter(p=>p.complete),complete_seconds=complete.reduce((sum,p)=>sum+duration(p),0);
  const idle_device_hours=periods.reduce((sum,p)=>sum+duration(p)*p.idle,0)/3600;
  return {complete_seconds,idle_device_hours,average_idle_count:complete_seconds?complete.reduce((sum,p)=>sum+duration(p)*p.idle,0)/complete_seconds:null,
   coverage:elapsed_end>start?complete_seconds/(elapsed_end-start):null,unknown_seconds:elapsed_end-start-complete_seconds,
   whole_idle_seconds:periods.filter(p=>p.whole).reduce((sum,p)=>sum+duration(p),0)};
 };
 const series=selected.map((host,index)=>{
  const devices=host.snapshot.devices.filter(d=>d.kind===kind);
  const segments:HistorySegment[]=ranges.map((range,i)=>{
   const future=range.start>=elapsed_end,known=devices.length>0&&!future;
   const complete=known&&host.snapshot.fresh&&i!==3;
   const idle=complete?[devices.length,Math.floor(devices.length/2),0,0,devices.length][(i+index)%5]:0;
   return {...range,idle_count:idle,busy_count:complete?devices.length-idle:0,unknown_count:known?(complete?0:devices.length):null,
    total_count:known?devices.length:null,inventory_known:known,complete,devices:known?devices:[],
    machine_state:!complete?'unknown':idle===devices.length?'whole_idle':idle?'partial_idle':'no_idle',
    reason:future?'future':!devices.length?'inventory_unknown':complete?null:'collection_failed'};
  });
  return {host_id:host.id,name:host.alias||host.target,segments,summary:summarize(segments.map(p=>({...p,idle:p.idle_count,whole:p.machine_state==='whole_idle'})))};
 });
 const segments:FleetSegment[]=ranges.map((range,i)=>{
  const peers=series.map(h=>h.segments[i]);
  return {...range,whole_idle:peers.filter(s=>s.machine_state==='whole_idle').length,partial_idle:peers.filter(s=>s.machine_state==='partial_idle').length,
   no_idle:peers.filter(s=>s.machine_state==='no_idle').length,unknown:peers.filter(s=>!s.complete).length,
   idle_count:peers.reduce((sum,s)=>sum+s.idle_count,0),unknown_count:peers.some(s=>s.unknown_count===null)?null:peers.reduce((sum,s)=>sum+(s.unknown_count??0),0),
   complete_hosts:peers.filter(s=>s.complete).length};
 });
 return {start,end,elapsed_end,timezone,kind,rule_version:1,recording_started_at:start,retention_started_at:start,truncated:false,
  sample_count:series.reduce((sum,h)=>sum+h.segments.filter(s=>s.complete).length,0),hosts:series,segments,
  summary:summarize(segments.map(p=>({...p,complete:!p.unknown,idle:p.idle_count,whole:p.whole_idle===series.length})))};
}
