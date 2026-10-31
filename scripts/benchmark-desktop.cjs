// Windows benchmark: isolated headed Edge and optimized Tauri/WebView2.
// No production configuration, backend or real SSH session is modified.
const fs=require('node:fs/promises');
const syncfs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const net=require('node:net');
const readline=require('node:readline');
const {spawn,spawnSync}=require('node:child_process');
const {performance}=require('node:perf_hooks');
const {createHash}=require('node:crypto');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'..');
const work=path.join(root,'work','desktop-benchmark');
const smoke=process.argv.includes('--smoke');
const startupOnly=process.argv.includes('--startup-only');
const uiOnly=process.argv.includes('--ui-only');
const flowsOnly=process.argv.includes('--flows-only');
const renderer=process.argv.find(argument=>argument.startsWith('--renderer='))?.slice('--renderer='.length);
if(renderer&&!['dom','webgl'].includes(renderer))throw new Error('renderer must be dom or webgl');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const percentile=(values,p)=>{const sorted=values.slice().sort((a,b)=>a-b);return sorted.length?sorted[Math.min(sorted.length-1,Math.floor(sorted.length*p))]:null};
const round=value=>value==null?null:Math.round(value*100)/100;
const distribution=values=>({n:values.length,median:round(percentile(values,.5)),p95:round(percentile(values,.95)),max:round(Math.max(0,...values))});
const log=message=>console.log(new Date().toISOString()+' '+message);

function playwright(){
  const cache=path.join(process.env.LOCALAPPDATA,'npm-cache','_npx');
  for(const folder of syncfs.readdirSync(cache)){
    const pkg=path.join(cache,folder,'node_modules','playwright','package.json');
    if(syncfs.existsSync(pkg))return createRequire(pkg)('playwright');
  }
  throw new Error('Install Playwright CLI first (npx --package @playwright/cli playwright-cli --help)');
}
async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port}
function sampler(){
  const child=spawn('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'desktop-benchmark-processes.ps1')],{stdio:['pipe','pipe','inherit'],windowsHide:true});
  const pending=[];
  readline.createInterface({input:child.stdout}).on('line',line=>{const next=pending.shift();if(next){try{const result=JSON.parse(line);if(result.error)next.reject(new Error(result.error));else next.resolve(result)}catch(error){next.reject(error)}}});
  child.on('exit',()=>{for(const entry of pending)entry.reject(new Error('Memory sampler exited'))});
  return {sample(root){return new Promise((resolve,reject)=>{pending.push({resolve,reject});child.stdin.write(JSON.stringify({root})+'\n')})},close(){child.stdin.end()}};
}
function memorySummary(samples){
  const cpuByPid=new Map();let cpu=0;
  for(let i=0;i<samples.length;i++)for(const detail of samples[i].details){const previous=cpuByPid.get(detail.pid);if(previous!=null)cpu+=Math.max(0,detail.cpuSeconds-previous);cpuByPid.set(detail.pid,detail.cpuSeconds)}
  const elapsed=samples.length>1?(samples.at(-1).at-samples[0].at)/1000:0;
  return {samples:samples.length,privateWorkingSetMiB:round(percentile(samples.map(s=>s.privateWorkingSet/1024**2),.5)),peakPrivateWorkingSetMiB:round(Math.max(...samples.map(s=>s.privateWorkingSet/1024**2))),privateCommitMiB:round(percentile(samples.map(s=>s.privateBytes/1024**2),.5)),processCount:round(percentile(samples.map(s=>s.processCount),.5)),cpuCoreEquivalent:elapsed?round(cpu/elapsed):null};
}
const owned=new Set();
let fixture,collector;
let browserOuter={width:1456,height:1029};
let runDirectory;
async function launch(kind,profile,label,url='http://127.0.0.1:8765/'){
  const run=fixture.beginRun(label),port=await freePort();
  const flags=[`--remote-debugging-port=${port}`,`--proxy-server=http://127.0.0.1:${fixture.port}`,'--proxy-bypass-list=<-loopback>','--disable-backgrounding-occluded-windows','--disable-renderer-backgrounding','--disable-background-timer-throttling'];
  let executable,args,env={...process.env};
  if(kind==='desktop'){
    executable=path.join(root,'desktop/src-tauri/target/benchmark/release/infra-workbench-desktop.exe');args=[];
    env.WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=flags.join(' ');
    env.WEBVIEW2_USER_DATA_FOLDER=profile;
  }else{
    executable='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
    args=[...flags,`--user-data-dir=${profile}`,'--no-first-run','--no-default-browser-check','--disable-extensions','--disable-background-networking','--new-window',`--window-size=${browserOuter.width},${browserOuter.height}`,'--window-position=20,20',url];
  }
  const launchedAt=performance.now();
  const child=spawn(executable,args,{env,stdio:'ignore',windowsHide:false});
  log('Launched '+label+' PID '+child.pid+' CDP '+port);
  const instance={kind,child,rootPid:child.pid,launchedAt,run};owned.add(instance);
  instance.exited=new Promise(resolve=>child.once('exit',(code,signal)=>resolve({code,signal})));
  let endpoint;
  const deadline=performance.now()+30000;
  while(performance.now()<deadline){
    if(child.exitCode!=null)throw new Error(kind+' exited before readiness: '+child.exitCode);
    try{const response=await fetch(`http://127.0.0.1:${port}/json/version`);if(response.ok){endpoint=await response.json();break}}catch{}
    await delay(30);
  }
  if(!endpoint)throw new Error(kind+' CDP endpoint unavailable');
  instance.browser=await playwright().chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  instance.context=instance.browser.contexts()[0];
  const end=performance.now()+15000;
  while(!instance.page&&performance.now()<end){instance.page=instance.context.pages().find(page=>url==='about:blank'?page.url()==='about:blank':page.url().startsWith('http://127.0.0.1:8765/'));if(!instance.page)await delay(30)}
  if(!instance.page)throw new Error(kind+' workbench page unavailable');
  instance.page.setDefaultTimeout(5000);
  instance.cdp=await instance.browser.newBrowserCDPSession();
  instance.version=await instance.cdp.send('Browser.getVersion');
  if(kind==='browser'){
    const processes=await instance.cdp.send('SystemInfo.getProcessInfo');
    instance.rootPid=processes.processInfo.find(p=>p.type==='browser').id;
  }
  if(url!=='about:blank'){
    const ready=await Promise.race([run.readyPromise,delay(15000).then(()=>{throw new Error(kind+' instrumented UI readiness timed out')})]);
    instance.ready=ready;instance.startupMs=ready.observedAt-launchedAt;
    if(ready.width!==1440||ready.height!==900)log('Viewport mismatch '+kind+' '+ready.width+'x'+ready.height);
  }
  return instance;
}
async function close(instance){
  if(!instance||!owned.has(instance))return;
  try{
    let enginePids=[];
    try{enginePids=(await instance.cdp.send('SystemInfo.getProcessInfo')).processInfo.map(item=>item.id)}catch{}
    if(instance.kind==='desktop')await instance.page.evaluate(()=>{void window.__TAURI_INTERNALS__.invoke('close_desktop')}).catch(()=>{});
    else await instance.cdp.send('Browser.close').catch(()=>{});
    await Promise.race([instance.exited,delay(8000)]);
    if(instance.child.exitCode==null&&instance.child.signalCode==null)throw new Error('Owned '+instance.kind+' process did not exit normally');
    await instance.browser.close().catch(()=>{});
    const alive=id=>{try{process.kill(id,0);return true}catch{return false}};
    const shutdownBegin=performance.now(),deadline=shutdownBegin+15000;
    while(enginePids.some(alive)&&performance.now()<deadline)await delay(100);
    const remaining=enginePids.filter(alive);
    log(instance.run.label+' engine shutdown '+round(performance.now()-shutdownBegin)+'ms; remaining='+remaining.length);
    if(remaining.length)throw new Error('Owned engine processes remained after shutdown: '+remaining.join(','));
  }finally{owned.delete(instance)}
  // Allow renderer/GPU utility descendants to finish before the next sample.
  await delay(600);
}
async function sampleIdle(instance){
  await delay(smoke?1500:6000);
  const samples=[];for(let i=0;i<3;i++){samples.push(await collector.sample(instance.rootPid));await delay(400)}
  return {summary:memorySummary(samples),samples};
}
async function openTerminals(page,from,to){
  for(let i=from+1;i<=to;i++){
    if(i>1)await page.getByRole('button',{name:'最小化终端',exact:true}).click();
    const id='bench-'+String(i).padStart(2,'0');
    await page.getByRole('button',{name:'只看机器 '+id,exact:true}).click();
    await page.getByRole('button',{name:'打开 '+id+' 终端',exact:true}).click();
    await page.getByRole('tab').nth(i-1).waitFor();
    const deadline=performance.now()+5000;while(!fixture.connections.get(id)?.ready&&performance.now()<deadline)await delay(20);
    if(!fixture.connections.get(id)?.ready)throw new Error('Terminal did not become ready: '+id);
  }
  await page.getByRole('button',{name:'全选',exact:true}).click();
  await delay(800);
}
async function loadPhase(instance,count,rate,seconds){
  await instance.page.evaluate(()=>window.__bench.start());
  const cpuStart=process.cpuUsage(),stream=fixture.startPhase(count,rate);
  const samples=[],inputErrors=[];
  const start=performance.now();let nextTab=start+1500,nextMemory=start+Math.min(6000,seconds*300),tab=0;
  while(performance.now()-start<seconds*1000){
    if(performance.now()>=nextTab){
      try{await instance.page.getByRole('tab').nth(tab++%count).click({timeout:2000})}catch(error){inputErrors.push(error.message.slice(0,200))}
      nextTab=performance.now()+1500;
    }
    if(performance.now()>=nextMemory){samples.push(await collector.sample(instance.rootPid));nextMemory=performance.now()+(smoke?2000:12000)}
    await delay(40);
  }
  const output=await fixture.stopPhase();
  const ui=await instance.page.evaluate(()=>window.__bench.stop());
  if(!samples.length)samples.push(await collector.sample(instance.rootPid));
  const cpu=process.cpuUsage(cpuStart);
  const summary={terminals:count,requestedKiBPerSecond:count*rate/1024,receivedKiBPerSecond:round(output.ackBytes/output.elapsedSeconds/1024),elapsedSeconds:round(output.elapsedSeconds),sentBytes:output.sentBytes,ackBytes:output.ackBytes,acks:output.acks,pendingMessages:output.pendingMessages,outputWriteLatencyMs:distribution(output.latencies),producerTickLagMs:distribution(output.tickLag),maxInFlight:output.maxInFlight,creditLimitedTicks:output.creditLimitedTicks,prematureClosures:output.prematureClosures,frameIntervalMs:distribution(ui.frames),framesOver50ms:ui.frames.filter(value=>value>50).length,longTasks:ui.longTasks.length,longTaskMs:round(ui.longTasks.reduce((n,v)=>n+v,0)),eventLoopLagMs:distribution(ui.eventLoopLag),tabSwitchLatencyMs:distribution(ui.tabLatency),tabTimeouts:ui.tabTimeouts,inputErrors,memory:memorySummary(samples),producerCpuCoreEquivalent:round((cpu.user+cpu.system)/1e6/output.elapsedSeconds)};
  summary.renderers=ui.renderers;
  if(!output.ackBytes||ui.frames.length<20)throw new Error('Invalid terminal measurement: '+JSON.stringify(summary));
  await fs.writeFile(path.join(runDirectory,instance.run.label+'-'+count+'-raw.json'),JSON.stringify({summary,memory:samples,ui,stream:{...output,latencies:output.latencies,tickLag:output.tickLag}},null,2));
  return summary;
}

(async()=>{
  runDirectory=path.join(work,(uiOnly?'ui-':startupOnly?'startup-':smoke?'smoke-':'run-')+new Date().toISOString().replace(/[:.]/g,'-'));
  await fs.mkdir(runDirectory,{recursive:true});
  const frozenSource=process.argv.find(argument=>argument.startsWith('--snapshot='))?.slice('--snapshot='.length);
  const snapshot=path.join(runDirectory,'frontend');await fs.cp(frozenSource||path.join(root,'frontend/dist'),snapshot,{recursive:true});
  const WebSocketServer=require(path.join(work,'node_modules/ws')).WebSocketServer;
  fixture=await require('./desktop-benchmark-server.cjs')(snapshot,WebSocketServer,{renderer,ui:uiOnly});
  collector=sampler();
  const hardware=spawnSync('powershell.exe',['-NoProfile','-ExecutionPolicy','Bypass','-File',path.join(__dirname,'desktop-benchmark-processes.ps1'),'-SystemInfo'],{encoding:'utf8',windowsHide:true});
  const report={created:new Date().toISOString(),smoke,startupOnly,hardware:JSON.parse(hardware.stdout),frontendIndexSha256:createHash('sha256').update(await fs.readFile(path.join(snapshot,'index.html'))).digest('hex'),conditions:{viewport:'1440x900',hosts:48,devices:384,backend:'Existing Python service already ready; common backend excluded from client tree',output:'Local WebSocket fixture; 8 in-flight messages per terminal, real xterm write callbacks',browser:'Dedicated headed Edge, no extensions, isolated profile',desktop:'Optimized build; only application identifier differs to isolate single-instance/window state',flags:'Both engines disable background/occlusion throttling; isolated per-process loopback proxy',shutdown:'Wait for host and engine child processes to exit before reuse of profile'},startup:[],loads:[],existingBrowser:null};
  log('Calibration and isolated browser/window startup');
  const pilot=await launch('browser',path.join(runDirectory,'profile-pilot'),'pilot','about:blank');
  const dimensions=await pilot.page.evaluate(()=>({dw:outerWidth-innerWidth,dh:outerHeight-innerHeight,dpr:devicePixelRatio}));
  browserOuter={width:1440+dimensions.dw,height:900+dimensions.dh};
  const pageCDP=await pilot.context.newCDPSession(pilot.page),windowInfo=await pageCDP.send('Browser.getWindowForTarget');
  for(let attempt=0;attempt<3;attempt++){
    await pilot.cdp.send('Browser.setWindowBounds',{windowId:windowInfo.windowId,bounds:{...browserOuter,windowState:'normal'}});await delay(150);
    const actual=await pilot.page.evaluate(()=>({width:innerWidth,height:innerHeight}));
    if(actual.width===1440&&actual.height===900)break;
    browserOuter.width+=1440-actual.width;browserOuter.height+=900-actual.height;
  }
  report.conditions.browserOuter=browserOuter;await close(pilot);
  const profiles={desktop:path.join(runDirectory,'profile-desktop'),browser:path.join(runDirectory,'profile-browser')};
  const startups=uiOnly||flowsOnly?0:smoke?1:6;
  for(let iteration=0;iteration<startups;iteration++){
    for(const kind of iteration%2?['browser','desktop']:['desktop','browser']){
      const instance=await launch(kind,profiles[kind],kind+'-startup-'+iteration);
      report.startup.push({kind,round:iteration,firstProfileUse:iteration===0,milliseconds:round(instance.startupMs),ready:instance.ready,version:instance.version.product});
      log(kind+' startup '+iteration+': '+round(instance.startupMs)+'ms');await close(instance);
    }
  }
  if(flowsOnly){
    report.flows=[];
    for(const kind of ['desktop','browser']){
      const instance=await launch(kind,profiles[kind],kind+'-flows');
      const result=await require('./check-desktop-flows.cjs')(instance.page,fixture);report.flows.push({kind,...result});
      log(kind+' flows: '+JSON.stringify(result));await close(instance);
    }
    await fs.writeFile(path.join(runDirectory,'results.json'),JSON.stringify(report,null,2));log('RESULT '+path.join(runDirectory,'results.json'));return;
  }
  if(uiOnly){
    report.ui=[];
    for(let trial=0;trial<(smoke?1:3);trial++)for(const kind of trial%2?['browser','desktop']:['desktop','browser']){
      const instance=await launch(kind,profiles[kind],kind+'-ui-'+trial);
      const measurement=await require('./measure-shared-ui.cjs')(instance,fixture,()=>openTerminals(instance.page,0,1));
      report.ui.push({kind,trial,...measurement});log(kind+' UI '+trial+': '+JSON.stringify(measurement));
      await close(instance);await fs.writeFile(path.join(runDirectory,'results.json'),JSON.stringify(report,null,2));
    }
    log('RESULT '+path.join(runDirectory,'results.json'));return;
  }
  if(startupOnly){await fs.writeFile(path.join(runDirectory,'results.json'),JSON.stringify(report,null,2));log('RESULT '+path.join(runDirectory,'results.json'));return}
  const repetitions=smoke?1:3;
  for(let trial=0;trial<repetitions;trial++){
    for(const kind of trial%2?['browser','desktop']:['desktop','browser']){
      const instance=await launch(kind,profiles[kind],kind+'-load-'+trial);
      const idle=await sampleIdle(instance);log(kind+' trial '+trial+' idle private working set '+idle.summary.privateWorkingSetMiB+' MiB');
      const row={kind,trial,version:instance.version.product,idle,phases:[]};
      await openTerminals(instance.page,0,4);
      row.phases.push(await loadPhase(instance,4,64*1024,smoke?5:45));log(kind+' trial '+trial+' 4 terminals complete');
      await openTerminals(instance.page,4,8);
      row.phases.push(await loadPhase(instance,8,128*1024,smoke?7:60));log(kind+' trial '+trial+' 8 terminals complete');
      report.loads.push(row);await close(instance);
      await fs.writeFile(path.join(runDirectory,'results.json'),JSON.stringify(report,null,2));
    }
  }
  const existing=await launch('browser',profiles.browser,'existing-blank','about:blank');
  const baseline=await sampleIdle(existing);const nav=[];
  for(let i=0;i<(smoke?1:5);i++){
    const ready=fixture.beginRun('existing-tab-'+i),begin=performance.now();const page=await existing.context.newPage();await page.goto('http://127.0.0.1:8765/');
    const info=await Promise.race([ready.readyPromise,delay(10000).then(()=>{throw new Error('Existing browser tab ready timeout')})]);
    nav.push(info.observedAt-begin);
    if(i===(smoke?0:4)){
      const loaded=await sampleIdle(existing);report.existingBrowser={baseline,loaded,startupMs:nav.map(round),incrementalPrivateWorkingSetMiB:round(loaded.summary.privateWorkingSetMiB-baseline.summary.privateWorkingSetMiB),incrementalPrivateCommitMiB:round(loaded.summary.privateCommitMiB-baseline.summary.privateCommitMiB)};
    }
    await page.close();
  }
  await close(existing);
  await fs.writeFile(path.join(runDirectory,'results.json'),JSON.stringify(report,null,2));
  log('RESULT '+path.join(runDirectory,'results.json'));
})().catch(async error=>{log('ERROR '+error.stack);if(runDirectory)await fs.writeFile(path.join(runDirectory,'error.txt'),error.stack);process.exitCode=1}).finally(async()=>{
  for(const instance of [...owned])try{await close(instance)}catch(error){log('Cleanup: '+error.message)}
  collector?.close();await fixture?.close();
});
