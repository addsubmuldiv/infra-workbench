export type HistorySegment={start:number;end:number;idle_count:number;busy_count:number;unknown_count:number|null;total_count:number|null;inventory_known:boolean;complete:boolean;machine_state:string;reason:string|null;devices:unknown[]};
export type HistorySummary={whole_idle_seconds:number;idle_device_hours:number;average_idle_count:number|null;complete_seconds:number;coverage:number|null;unknown_seconds:number};
export type FleetSegment={start:number;end:number;whole_idle:number;partial_idle:number;no_idle:number;unknown:number;idle_count:number;unknown_count:number|null;complete_hosts:number};
export type HistoryResponse={rule_version:number;kind:string;timezone:string;start:number;end:number;elapsed_end:number;recording_started_at:number|null;retention_started_at:number|null;sample_count:number;truncated:boolean;hosts:{host_id:string;name:string;segments:HistorySegment[];summary:HistorySummary}[];segments:FleetSegment[];summary:HistorySummary};
export function historyDeviceKind(hosts:readonly {id:string;snapshot:{devices:readonly {kind:string}[]}}[],ids:readonly string[],current:string):string{
 const selected=new Set(ids),kinds=new Set(hosts.filter(h=>selected.has(h.id)).flatMap(h=>h.snapshot.devices.map(d=>d.kind)).filter(kind=>kind==='GPU'||kind==='NPU'));
 return kinds.size===1?[...kinds][0]:current;
}
export type DisplayHistorySegment=HistorySegment&{bridged_unknown_seconds:number};
/** Presentation only. Never feed these inferred bridges into statistics or alerts. */
export function mergeHistoryDisplaySegments(segments:readonly HistorySegment[],maxGapSeconds=120):DisplayHistorySegment[]{
 const result:DisplayHistorySegment[]=[];
 const identity=(s:HistorySegment)=>JSON.stringify(s.devices.map(d=>{const item=d as {identity?:unknown;id?:unknown;uuid?:unknown;kind?:unknown};return item.identity??[item.id,item.uuid,item.kind]}).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))));
 const same=(a:HistorySegment,b:HistorySegment)=>a.complete&&b.complete&&a.inventory_known&&b.inventory_known&&a.total_count===b.total_count&&a.idle_count===b.idle_count&&a.busy_count===b.busy_count&&a.machine_state===b.machine_state&&(a as {run_id?:string}).run_id===(b as {run_id?:string}).run_id&&identity(a)===identity(b);
 for(let i=0;i<segments.length;i++){
  const current={...segments[i],bridged_unknown_seconds:0},previous=result[result.length-1];
  if(previous&&previous.end===current.start&&same(previous,current)){previous.end=current.end;continue}
  if(previous&&previous.complete&&previous.idle_count>0&&previous.end===current.start&&!current.complete){
   let j=i,end=current.start;
   while(j<segments.length&&!segments[j].complete&&['sampling_gap','collection_failed'].includes(segments[j].reason??'')&&segments[j].start===end){end=segments[j].end;j++}
   const next=segments[j];
   if(j>i&&next&&next.start===end&&end-current.start<=maxGapSeconds&&same(previous,next)){
    previous.bridged_unknown_seconds+=end-current.start;previous.end=next.end;i=j;continue;
   }
  }
  result.push(current);
 }
 return result;
}
export function localDate(now=new Date()){return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`}
export function shiftDate(date:string,days:number){const d=new Date(`${date}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10)}
export function heatColor(count:number,max:number){return `rgba(98, 189, 155, ${0.055+Math.min(1,Math.max(0,count)/Math.max(1,max))*.44})`}
export function segmentWidth(start:number,end:number,dayStart:number,dayEnd:number){return Math.max(0,Math.min(end,dayEnd)-Math.max(start,dayStart))/Math.max(1,dayEnd-dayStart)*100}
export function idleLabel(segment:Pick<HistorySegment,'idle_count'|'unknown_count'|'inventory_known'|'complete'>,en=false){if(!segment.inventory_known)return en?'Unknown inventory':'设备库存未知';if(segment.complete)return `${segment.idle_count}`;return en?`≥${segment.idle_count}, ${segment.unknown_count??'?'} unknown`:`≥${segment.idle_count}，${segment.unknown_count??'?'} 个未知`}
export function stepPath(segments:HistorySegment[],start:number,end:number,max:number,field:'idle_count'|'unknown_count'='idle_count'){return segments.filter(s=>s.inventory_known&&s.reason!=='future').map(s=>{const x=(s.start-start)/(end-start)*1000,w=(s.end-s.start)/(end-start)*1000;const value=field==='unknown_count'?s.idle_count+(s.unknown_count??0):s.idle_count;const y=180-value/Math.max(1,max)*160;return `M${x},180V${y}H${x+w}V180Z`}).join(' ')}
