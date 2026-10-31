// Same UI interactions in both real clients. Inventory and SSH stay synthetic.
module.exports=async function measure(instance,fixture,openTerminal){
  const {page,context}=instance;
  // Each trial shares a profile but must start from the same terminal geometry.
  // A previous drag can otherwise cover the sidebar's real click targets.
  await page.evaluate(()=>localStorage.removeItem('infra-workbench:terminal-frame:v1'));
  const session=await context.newCDPSession(page);await session.send('Performance.enable');
  const errors=[];page.on('pageerror',error=>{errors.push(error.message);console.error('Measured page error:',error.message)});
  const snapshot=async()=>{
    const {metrics}=await session.send('Performance.getMetrics');
    return {...Object.fromEntries(metrics.map(({name,value})=>[name,value])),...await page.evaluate(()=>({commits:window.__benchCommits,writes:window.__geometryWrites||0}))};
  };
  const delta=(start,end)=>({commits:end.commits-start.commits,geometryWrites:end.writes-start.writes,scriptMs:Math.round((end.ScriptDuration-start.ScriptDuration)*100000)/100,layoutMs:Math.round((end.LayoutDuration-start.LayoutDuration)*100000)/100,taskMs:Math.round((end.TaskDuration-start.TaskDuration)*100000)/100});
  await page.waitForTimeout(1200);
  const entryAssets=await page.evaluate(()=>{
    const files=performance.getEntriesByType('resource').filter(item=>/\.(js|css)(?:\?|$)/.test(item.name)).map(item=>({path:new URL(item.name).pathname,decodedBytes:item.decodedBodySize}));
    return {files,decodedBytes:files.reduce((sum,file)=>sum+file.decodedBytes,0)};
  });
  let start=await snapshot();await page.waitForTimeout(13000);
  const unchangedPoll=delta(start,await snapshot());
  // A changed resource and freshness transition must still reach the DOM.
  const hosts=structuredClone(fixture.inventory);hosts[0].snapshot.fresh=false;
  await page.route('**/api/state',route=>route.fulfill({json:{hosts,rules:[],reservations:[],events:[],server_time:Date.now()/1000}}));
  await page.getByLabel('机器详情 bench-01',{exact:true}).getByText('信息过期',{exact:true}).first().waitFor();
  await page.unroute('**/api/state');
  await openTerminal();
  await page.evaluate(()=>{
    window.__geometryWrites=0;const original=Storage.prototype.setItem;
    Storage.prototype.setItem=function(key,value){if(key==='infra-workbench:terminal-frame:v1')window.__geometryWrites++;return original.call(this,key,value)};
  });
  const box=await page.locator('.terminal-brand').boundingBox();
  await page.mouse.move(box.x+28,box.y+12);await page.mouse.down();
  start=await snapshot();
  await page.mouse.move(box.x-48,box.y-36,{steps:100});
  await page.mouse.move(box.x+20,box.y+40,{steps:100});
  const during=await snapshot();await page.mouse.up();await page.waitForTimeout(100);
  const terminalDrag={...delta(start,await snapshot()),writesDuringGesture:during.writes-start.writes};
  const renderer=await page.locator('.terminal-screen.active').evaluate(el=>({mode:el.dataset.renderer||'dom',canvasCount:el.querySelectorAll('canvas').length}));
  let contextLossFallback=null;
  if(renderer.mode==='webgl'){
    contextLossFallback=await page.locator('.terminal-screen.active').evaluate(async el=>{
      const canvas=[...el.querySelectorAll('canvas')].find(canvas=>canvas.getContext('webgl2'));
      const extension=canvas?.getContext('webgl2')?.getExtension('WEBGL_lose_context');
      if(!extension)return false;extension.loseContext();
      // xterm waits 3s for context restoration before firing onContextLoss.
      const deadline=performance.now()+5000;
      while(el.dataset.renderer!=='dom'&&performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,50));
      return el.dataset.renderer==='dom';
    });
    if(!contextLossFallback)throw new Error('WebGL context loss did not restore DOM renderer');
  }
  await page.getByRole('button',{name:'最小化终端',exact:true}).click();
  const viewports=[];
  for(const width of [480,800,1440]){
    await page.setViewportSize({width,height:900});await page.waitForTimeout(150);
    viewports.push(await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth})));
  }
  for(const label of ['精度对比','设置','算力总览']){
    await page.getByRole('button',{name:label,exact:true}).click();
    if(label==='精度对比')await page.getByRole('heading',{name:'基准日志',exact:true}).waitFor();
    if(label==='设置')await page.getByRole('heading',{name:'外部 Agent（MCP）',exact:true}).waitFor();
  }
  await session.detach();
  if(errors.length)throw new Error('UI errors: '+errors.join('; '));
  return {entryAssets,unchangedPoll,terminalDrag,renderer,contextLossFallback,viewports,errors};
};
