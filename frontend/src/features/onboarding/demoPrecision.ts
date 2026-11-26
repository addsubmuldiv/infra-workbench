const metricNames=['loss','grad_norm','learning_rate'] as const;
type MetricName=typeof metricNames[number];
type Row={step:number;line:number;source:string;metrics:Record<MetricName,number>};

function sample(id:string,path:string,steps:number[],candidate=false){
 const rows:Row[]=steps.map((step,index)=>{
  const metrics={loss:Number((2.2/(1+step*.18)+(candidate ? .002*(step%5):0)).toFixed(5)),
   grad_norm:Number((8/(1+step*.08)+(candidate ? .004*(step%3):0)).toFixed(5)),learning_rate:6.7e-7*Math.min(step,8)};
  return {step,line:index+1,source:JSON.stringify({step,...metrics}),metrics};
 });
 const content=rows.map(r=>r.source).join('\n')+'\n';
 return {rows,content,snapshot:{id,path,demo:true,total_lines:rows.length,skipped_lines:0,invalid_values:0,
  file:{size:new TextEncoder().encode(content).length,mtime:null},
  groups:[{key:'rank0',rank:'0',segment:1,count:rows.length,duplicates:0,unique_steps:rows.length,start:rows[0].step,
   end:rows[rows.length-1].step,metrics:metricNames,preview:rows.slice(0,5)}]}};
}

const steps=Array.from({length:24},(_,i)=>i+1);
const baseline=sample('demo-baseline','/demo/baseline.log',steps);
const candidate=sample('demo-candidate','/demo/candidate.log',[...steps.filter(step=>step!==7),25],true);
const samples=[baseline,candidate];
export const demoPrecisionFiles=Object.fromEntries(samples.map(({content,snapshot})=>[snapshot.path,content]));
export const demoPrecisionSamples={baseline:baseline.snapshot,candidate:candidate.snapshot};
export const demoLogAt=(path:unknown)=>samples.find(s=>s.snapshot.path===path)?.snapshot;
export const demoLogRecord=(id:string,line:number)=>samples.find(s=>s.snapshot.id===id)?.rows.find(r=>r.line===line);

export function compareDemoLogs(body:Record<string,unknown>){
 const left=samples.find(s=>s.snapshot.id===body.baseline),right=samples.find(s=>s.snapshot.id===body.candidate);
 if(!left||!right)return null;
 const within=(row:Row)=>row.step>=Number(body.start??-Infinity)&&row.step<=Number(body.end??Infinity);
 const a=left.rows.filter(within),b=right.rows.filter(within);
 const rightSteps=new Map(b.map(row=>[row.step,row]));
 const shared=a.flatMap(row=>{const other=rightSteps.get(row.step);return other?[[row,other] as const]:[]});
 const names=metricNames.filter(name=>!Array.isArray(body.metrics)||!body.metrics.length||body.metrics.includes(name));
 if(!names.length||!shared.length)return null;
 const metrics=names.map(name=>{
  const points=shared.map(([x,y])=>{
   const baseline=x.metrics[name],candidate=y.metrics[name],difference=candidate-baseline;
   return {step:x.step,baseline,candidate,difference,absolute_error:Math.abs(difference),baseline_line:x.line,candidate_line:y.line};
  });
  const worst=points.reduce((max,point)=>point.absolute_error>max.absolute_error?point:max);
  const series=(rows:Row[])=>rows.map(({step,metrics})=>({step,value:metrics[name]}));
  return {name,points,count:points.length,missing_metric_steps:0,mae:points.reduce((sum,p)=>sum+p.absolute_error,0)/points.length,
   max_abs_error:worst.absolute_error,max_error_step:worst.step,baseline_series:series(a),candidate_series:series(b)};
 });
 return {baseline:body.baseline,candidate:body.candidate,metrics,alignment:{common_steps:shared.length,baseline_only:a.length-shared.length,candidate_only:b.length-shared.length},
  range:{start:shared[0][0].step,end:shared[shared.length-1][0].step},learning_rate_mismatch_count:0,learning_rate_first_mismatch:null};
}
