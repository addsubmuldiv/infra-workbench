export type Cluster={id:string;name:string;revision:number;host_ids:string[]};
export type ClusterHost={id:string;target:string;alias?:string;user:string|null;snapshot:{fresh:boolean;status:string;devices:{kind:string}[]}};
export type BatchItem={id:string;host_id:string;name:string;status:string;error?:string;exit_code?:number|null;updated?:number};
export type ClusterBatch={id:string;batch_id?:string;cluster_id:string;cluster_name?:string;status:string;paused?:boolean;command?:string;cwd?:string;sudo?:boolean;timeout_seconds?:number;concurrency?:number;items:BatchItem[]};
export async function clusterApi(path:string,method='GET',body?:unknown){
 const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-IWB':'1'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail??data));return data;
}
export function clusterGroups<T extends ClusterHost>(hosts:T[],clusters:Cluster[],category:string,query:string){
 const q=query.trim().toLowerCase(),assigned=new Set(clusters.flatMap(c=>c.host_ids));
 return [...clusters.map(c=>({cluster:c,id:c.id,name:c.name,all:hosts.filter(h=>c.host_ids.includes(h.id))})),{cluster:null,id:'',name:'',all:hosts.filter(h=>!assigned.has(h.id))}].map(g=>({...g,matching:g.all.filter(h=>(category==='全部'||h.snapshot.devices.some(d=>d.kind===category))&&(!q||g.name.toLowerCase().includes(q)||h.target.toLowerCase().includes(q)||(h.alias??'').toLowerCase().includes(q)))}));
}
export function selectionState(ids:string[],selected:Set<string>){const count=ids.filter(id=>selected.has(id)).length;return {checked:ids.length>0&&count===ids.length,partial:count>0&&count<ids.length};}
