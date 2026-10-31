const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const [beforeFile,afterFile,beforeUIFile,afterUIFile,destination]=process.argv.slice(2);
if(!destination)throw new Error('Usage: node scripts/compare-performance-followup.cjs BEFORE.json AFTER.json BEFORE_UI.json AFTER_UI.json OUTPUT.json');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const before=read(beforeFile),after=read(afterFile),beforeUI=read(beforeUIFile),afterUI=read(afterUIFile);
const median=values=>{const sorted=values.slice().sort((a,b)=>a-b);return sorted[Math.floor(sorted.length/2)]};
const stats=values=>({median:median(values),min:Math.min(...values),max:Math.max(...values),samples:values});
function validate(full,ui){
  assert.equal(full.smoke,false);assert.equal(full.frontendIndexSha256,ui.frontendIndexSha256);
  assert.equal(full.startup.length,12);
  for(const row of full.startup){assert.equal(row.ready.width,1440);assert.equal(row.ready.height,900);assert.equal(row.ready.visibility,'visible')}
  assert.equal(full.loads.length,6);assert.equal(ui.ui.length,6);
  for(const row of full.loads){
    assert.equal(row.phases.length,2);
    for(const phase of row.phases){
      assert.equal(phase.sentBytes,phase.ackBytes);assert.equal(phase.pendingMessages,0);
      assert.equal(phase.prematureClosures,0);assert.equal(phase.tabTimeouts,0);assert.deepEqual(phase.inputErrors,[]);
      if(phase.renderers)assert.ok(phase.renderers.every(renderer=>renderer.renderer==='dom'));
    }
  }
  for(const row of ui.ui){
    assert.deepEqual(row.errors,[]);assert.ok(row.terminalDrag.commits>=200,'React commit instrumentation must be active');
    assert.ok(row.viewports.every(v=>v.documentWidth<=v.width));
  }
}
validate(before,beforeUI);validate(after,afterUI);
for(const kind of ['desktop','browser'])assert.deepEqual([...new Set(before.loads.filter(row=>row.kind===kind).map(row=>row.version))],[...new Set(after.loads.filter(row=>row.kind===kind).map(row=>row.version))],kind+' engine version changed');
const result={date:'2026-10-31',platform:'Windows 11; actual headed Edge and Tauri Release WebView2',hardware:after.hardware,conditions:after.conditions,
  caveats:['Fresh snapshots before/after; Python backend already ready and excluded.','Private working set of full client process tree; not summed RSS.','Three output trials/client: 4 terminals x64KiB/s for45s, 8 x128KiB/s for60s.','Unchanged-poll UI scenario is13s with static48-host/384-device inventory; not every real sampling cycle is unchanged.','No OS cache flush or reboot; independent startup has5 subsequent launches.','Early baseline included short focused regression commands; small CPU/timing differences should be treated cautiously.','No native macOS execution; Windows WebKit port and API absence tests are supplementary only.'],
  beforeHash:before.frontendIndexSha256,afterHash:after.frontendIndexSha256,rawFiles:{before:beforeFile,after:afterFile,beforeUI:beforeUIFile,afterUI:afterUIFile},clients:{}};
for(const kind of ['desktop','browser']){
  const client={};
  for(const [name,full,ui] of [['before',before,beforeUI],['after',after,afterUI]]){
    const rows=full.loads.filter(row=>row.kind===kind),views=ui.ui.filter(row=>row.kind===kind);
    const startups=full.startup.filter(row=>row.kind===kind&&!row.firstProfileUse);
    assert.equal(rows.length,3);assert.equal(views.length,3);
    const assets=views[0].entryAssets.files.filter(file=>file.path!=='/__bench/init.js');
    client[name]={versions:[...new Set(rows.map(row=>row.version))],startupMs:stats(startups.map(row=>row.milliseconds)),navigationToReadyMs:stats(startups.map(row=>row.ready.navigationMs)),beforeNavigationEstimateMs:stats(startups.map(row=>Math.round((row.milliseconds-row.ready.navigationMs)*100)/100)),
      idleMiB:stats(rows.map(row=>row.idle.summary.privateWorkingSetMiB)),entryBytes:assets.reduce((n,file)=>n+file.decodedBytes,0),entryFiles:assets,
      unchangedPoll:{commits:stats(views.map(row=>row.unchangedPoll.commits)),scriptMs:stats(views.map(row=>row.unchangedPoll.scriptMs)),layoutMs:stats(views.map(row=>row.unchangedPoll.layoutMs))},
      terminalDrag:{writesDuringGesture:stats(views.map(row=>row.terminalDrag.writesDuringGesture)),totalWrites:stats(views.map(row=>row.terminalDrag.geometryWrites)),scriptMs:stats(views.map(row=>row.terminalDrag.scriptMs)),taskMs:stats(views.map(row=>row.terminalDrag.taskMs))},loads:{}};
    for(const count of [4,8]){
      const phases=rows.flatMap(row=>row.phases).filter(phase=>phase.terminals===count);
      const fields={privateWorkingSetMiB:p=>p.memory.privateWorkingSetMiB,privateCommitMiB:p=>p.memory.privateCommitMiB,cpuCores:p=>p.memory.cpuCoreEquivalent,writeP95Ms:p=>p.outputWriteLatencyMs.p95,tabP95Ms:p=>p.tabSwitchLatencyMs.p95,frameP95Ms:p=>p.frameIntervalMs.p95,receivedKiBPerSecond:p=>p.receivedKiBPerSecond};
      client[name].loads[count]=Object.fromEntries(Object.entries(fields).map(([field,get])=>[field,stats(phases.map(get))]));
      Object.assign(client[name].loads[count],{longTasks:phases.map(p=>p.longTasks),sentBytes:phases.reduce((n,p)=>n+p.sentBytes,0),ackBytes:phases.reduce((n,p)=>n+p.ackBytes,0),pendingMessages:0,inputErrors:0});
    }
  }
  result.clients[kind]=client;
}
result.webKitCompatibility=read(path.resolve(__dirname,'../work/performance-round2/webkit-compat.json'));
fs.writeFileSync(destination,JSON.stringify(result,null,2)+'\n');
console.log('Verified and wrote '+destination);
