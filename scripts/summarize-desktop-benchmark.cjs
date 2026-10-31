const fs=require('node:fs');
const path=require('node:path');
const file=process.argv[2];
if(!file)throw new Error('Usage: node scripts/summarize-desktop-benchmark.cjs RESULTS.json');
const report=JSON.parse(fs.readFileSync(file,'utf8'));
const startupReport=process.argv[3]?JSON.parse(fs.readFileSync(process.argv[3],'utf8')):report;
if(startupReport.frontendIndexSha256!==report.frontendIndexSha256)throw new Error('Startup and load frontend snapshots differ');
const median=items=>{const values=items.filter(v=>Number.isFinite(v)).sort((a,b)=>a-b);return values.length?values[Math.floor(values.length/2)]:null};
const range=items=>({median:median(items),min:Math.min(...items),max:Math.max(...items)});
const output={conditions:report.conditions,hardware:report.hardware,frontendIndexSha256:report.frontendIndexSha256,versions:{},startup:{},idle:{},loads:{},existingBrowser:report.existingBrowser};
for(const kind of ['desktop','browser']){
  const starts=startupReport.startup.filter(item=>item.kind===kind),loads=report.loads.filter(item=>item.kind===kind);
  output.versions[kind]=[...new Set(starts.map(item=>item.version))];
  output.startup[kind]={newProfileMs:starts.find(item=>item.firstProfileUse)?.milliseconds,warmMs:range(starts.filter(item=>!item.firstProfileUse).map(item=>item.milliseconds))};
  output.idle[kind]={privateWorkingSetMiB:range(loads.map(item=>item.idle.summary.privateWorkingSetMiB)),privateCommitMiB:range(loads.map(item=>item.idle.summary.privateCommitMiB)),processCount:median(loads.map(item=>item.idle.summary.processCount))};
  for(const count of [4,8]){
    const phases=loads.flatMap(item=>item.phases).filter(item=>item.terminals===count);
    output.loads[kind+'-'+count]={trials:phases.length,requestedKiBPerSecond:phases[0]?.requestedKiBPerSecond,receivedKiBPerSecond:range(phases.map(item=>item.receivedKiBPerSecond)),privateWorkingSetMiB:range(phases.map(item=>item.memory.privateWorkingSetMiB)),privateCommitMiB:range(phases.map(item=>item.memory.privateCommitMiB)),cpuCoreEquivalent:range(phases.map(item=>item.memory.cpuCoreEquivalent)),outputWriteP95Ms:range(phases.map(item=>item.outputWriteLatencyMs.p95)),frameP95Ms:range(phases.map(item=>item.frameIntervalMs.p95)),tabSwitchP95Ms:range(phases.map(item=>item.tabSwitchLatencyMs.p95)),longTasks:phases.map(item=>item.longTasks),pendingMessages:phases.map(item=>item.pendingMessages),sentBytes:phases.reduce((n,item)=>n+item.sentBytes,0),ackBytes:phases.reduce((n,item)=>n+item.ackBytes,0),inputErrors:phases.reduce((n,item)=>n+item.inputErrors.length+item.tabTimeouts,0),prematureClosures:phases.reduce((n,item)=>n+item.prematureClosures,0),producerCpuCoreEquivalent:phases.map(item=>item.producerCpuCoreEquivalent),producerTickLagP95Ms:phases.map(item=>item.producerTickLagMs.p95)};
  }
}
const csv=['kind,trial,terminals,duration_seconds,requested_KiB_s,received_KiB_s,private_working_set_MiB,private_commit_MiB,cpu_cores,output_write_p95_ms,frame_p95_ms,tab_switch_p95_ms,long_tasks,pending_messages'];
for(const item of report.loads)for(const phase of item.phases)csv.push([item.kind,item.trial,phase.terminals,phase.elapsedSeconds,phase.requestedKiBPerSecond,phase.receivedKiBPerSecond,phase.memory.privateWorkingSetMiB,phase.memory.privateCommitMiB,phase.memory.cpuCoreEquivalent,phase.outputWriteLatencyMs.p95,phase.frameIntervalMs.p95,phase.tabSwitchLatencyMs.p95,phase.longTasks,phase.pendingMessages].join(','));
fs.writeFileSync(path.join(path.dirname(file),'summary.json'),JSON.stringify(output,null,2));
fs.writeFileSync(path.join(path.dirname(file),'terminal-results.csv'),csv.join('\n')+'\n');
console.log(JSON.stringify(output,null,2));
