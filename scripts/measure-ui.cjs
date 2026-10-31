// Run with playwright-cli run-code --filename scripts/measure-ui.cjs.
// Uses synthetic machines only, intercepting every API request in this browser.
(function(){
const measure=async (page) => {
  const count = 48;
  const cull = new URL(page.url()).searchParams.has('perf-cull');
  const GiB = 1024 ** 3;
  let requests = 0;
  const hosts = Array.from({length: count}, (_, i) => ({
    id: `perf-${i}`, target: `demo-${String(i + 1).padStart(3, '0')}`, user: 'demo', port: 22,
    manual: true, auth: 'key',
    snapshot: {status: 'online', fresh: true, collected_at: 1700000000,
      system: {cpu_percent: 12, cpu_cores: 64, memory: {memory_total: 256 * GiB, memory_used: 32 * GiB, memory_available: 224 * GiB}},
      devices: Array.from({length: 8}, (_, j) => ({id: String(j), kind: 'GPU', name: 'Demo accelerator',
        memory_total: 80 * GiB, memory_used: 8 * GiB, memory_free: 72 * GiB, utilization: 10, temperature: 40,
        health: 'OK', processes: [], processes_known: true}))}
  }));
  await page.unroute('**/api/**');
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/state') {
      requests++;
      return route.fulfill({json: {hosts, rules: [], reservations: [], events: [], server_time: Date.now() / 1000}});
    }
    return route.fulfill({status: 200, json: {items: [], sessions: [], editing: true, upload: true, search: true}});
  });
  await page.addInitScript((cull) => {
    localStorage.clear();
    if (window.__uiPerf) return;
    if(cull)document.addEventListener('DOMContentLoaded',()=>{
      const style=document.createElement('style');
      style.textContent='.machine{content-visibility:auto;contain-intrinsic-size:auto 640px}';
      document.head.appendChild(style);
    });
    window.__uiPerf = {frames: [], longTasks: [], mutations: 0};
    let last = performance.now();
    const frame = now => {window.__uiPerf.frames.push(now-last); last=now; requestAnimationFrame(frame)};
    requestAnimationFrame(frame);
    new PerformanceObserver(list => {for (const item of list.getEntries()) window.__uiPerf.longTasks.push(item.duration)}).observe({type:'longtask',buffered:true});
    new MutationObserver(list => window.__uiPerf.mutations += list.length).observe(document, {subtree:true,childList:true,attributes:true,characterData:true});
  },cull);
  await page.setViewportSize({width: 1440, height: 900});
  await page.reload();
  await page.getByRole('button', {name:'只看机器 demo-001',exact:true}).waitFor();
  await page.waitForTimeout(1000);
  await page.evaluate(() => {window.__uiPerf.frames=[];window.__uiPerf.longTasks=[];window.__uiPerf.mutations=0});
  await page.waitForTimeout(6500);
  const poll = await page.evaluate(() => ({...window.__uiPerf}));
  const separator = page.getByRole('separator', {name:'调整左侧栏宽度'});
  const box = await separator.boundingBox();
  await page.evaluate(() => {window.__uiPerf.frames=[];window.__uiPerf.longTasks=[];window.__uiPerf.mutations=0});
  await page.mouse.move(box.x+box.width/2, box.y+box.height/2);
  await page.mouse.down();
  await page.mouse.move(540, box.y+box.height/2, {steps:120});
  await page.mouse.move(270, box.y+box.height/2, {steps:120});
  await page.mouse.up();
  const drag = await page.evaluate(() => ({...window.__uiPerf}));
  const summarize = value => {
    const sorted = value.frames.slice().sort((a,b)=>a-b);
    return {frames:sorted.length, frameP95Ms:Math.round((sorted[Math.floor(sorted.length*.95)]||0)*100)/100,
      maxFrameMs:Math.round((sorted.at(-1)||0)*100)/100,longTasks:value.longTasks.length,
      longTaskMs:Math.round(value.longTasks.reduce((a,b)=>a+b,0)),mutations:value.mutations};
  };
  return {hosts:count,devices:count*8,cull,stateRequests:requests,poll:summarize(poll),sidebarDrag:summarize(drag)};
};
if(typeof module!=='undefined')module.exports=measure;
return measure;
})()
